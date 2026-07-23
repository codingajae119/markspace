"""AttachmentService.upload_attachment 단위 테스트 (Task 2.1 / Req 1.1, 1.2, 1.3, 1.5, 2.1, 2.2, 2.5, 3.2).

design.md §Components and Interfaces #AttachmentService(Feature/Service) 업로드 계약을 실제
DB + tmp 저장소로 검증한다:
- 이미지 붙여넣기가 base64 인라인이 아니라 **파일**로 저장되고 kind='image'·원본명 보존·소속
  문서/WS 기록·응답 url이 `/attachments/{id}` 이다(Req 1.1·1.2·1.3·2.1·2.2).
- 파일 첨부는 kind='file'·원본명 보존으로 기록된다(Req 2.1·2.2).
- `kind=None` 이면 방어적 기본값 FILE 로 기록한다(content-type 추론은 라우터 소관).
- 소속 `workspace_id` 는 클라이언트 입력이 아니라 대상 **문서에서 확정**된다(Req 3.2·8.3).
  서비스 시그니처에 workspace 파라미터가 없다는 사실 자체가 위조를 차단하며, 영속된 값이
  문서의 workspace 와 일치함을 함께 확인한다.
- 존재하지 않는 문서 업로드 → `DomainError` 404(Req 1.5).
- 업로드 크기 한도 초과 → `DomainError` 422(Req 2.5). 이때 파일 저장이 발생하지 않는다.

격리: tests/attachment/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다(`DB_NAME` 을
`markspace_test` 로 swap, 새 엔진·create_all, uuid4 접미사 시드, 초 정밀도 시각). 저장/보관
루트는 test_storage.py 처럼 tmp_path 하위를 가리키는 settings 대역을 storage·service 두 모듈에
monkeypatch 해 실제 config.yml 저장 루트에 의존하지 않는다.
"""

import io
import os
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.attachment.service as service_mod
import app.attachment.storage as storage_mod
import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.attachment.schemas import AttachmentKind, AttachmentRead
from app.attachment.service import AttachmentService
from app.common.auth import AuthContext
from app.common.db import Base
from app.common.errors import DomainError, ErrorCode
from app.models import Attachment, Document, User, Workspace

TEST_DB_NAME = "markspace_test"
_DEFAULT_MAX_BYTES = 26214400  # config 기본 25MiB


def _drop_everything(engine) -> None:
    """대상 DB 의 모든 테이블을 FK 무시하고 제거해 빈 상태로 만든다(견고한 teardown)."""
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        names = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ]
        for name in names:
            conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def _make_user(session, *, login_id):
    """테스트 DB 에 User 를 삽입하고 flush 하여 id 를 확정한다(FK 충족용)."""
    user = User(
        login_id=login_id,
        password_hash="hash-initial",
        name="테스트 사용자",
        email=None,
        is_admin=False,
        is_active=True,
        is_deleted=False,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def _make_workspace(session, *, name="ws"):
    """Workspace 행을 삽입하고 flush 한다(attachment/document FK 충족용)."""
    ws = Workspace(
        name=name,
        is_shareable=False,
        trash_retention_days=30,
        created_at=datetime.utcnow(),
    )
    session.add(ws)
    session.flush()
    return ws


def _make_document(session, *, workspace_id, created_by, title="문서", status="active"):
    """Document 행을 직접 삽입하고 flush 한다(업로드 대상 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=None,
        title=title,
        status=status,
        sort_order=Decimal("1000"),
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


@pytest.fixture
def sessionmaker_factory():
    """테스트 DB 를 마이그레이션하고 세션 팩토리를 제공한다(격리·원복 보증)."""
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    TestSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    _drop_everything(engine)  # 시작 전 빈 상태 보증(격리 전제).
    Base.metadata.create_all(engine)  # 마이그레이션된 DB 계약을 물리적으로 생성.

    try:
        yield TestSessionLocal
    finally:
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """저장/보관 루트를 tmp_path 하위로, 크기 한도를 기본값으로 격리한 settings 대역을 주입한다.

    storage 모듈(파일 저장 루트)과 service 모듈(크기 한도) 양쪽 `get_settings` 를 동일한
    가변 namespace 로 대체해, 저장 파일이 tmp 로 떨어지고 크기 한도를 테스트가 조정할 수 있게 한다.
    """
    storage_root = tmp_path / "storage"
    archive_root = tmp_path / "archive"
    settings = types.SimpleNamespace(
        file_storage_root=str(storage_root),
        attachment_archive_root=str(archive_root),
        attachment_max_bytes=_DEFAULT_MAX_BYTES,
    )
    monkeypatch.setattr(storage_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(service_mod, "get_settings", lambda: settings)
    return storage_root, archive_root, settings


@pytest.fixture
def ctx():
    """업로드 호출용 인증 컨텍스트(비-admin)."""
    return AuthContext(user_id=1, is_admin=False)


def _seed_document(sessionmaker_factory):
    """user·workspace·active 문서를 시드하고 (workspace_id, document_id) 를 반환한다."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        session.commit()
        return ws.id, doc.id
    finally:
        session.close()


# --- 이미지 붙여넣기: 파일 저장 ------------------------------------------


def test_upload_image_saves_as_file_and_records_metadata(
    sessionmaker_factory, roots, ctx
):
    """이미지 붙여넣기는 파일로 저장되고 kind='image'·원본명·문서/WS·url 이 기록된다
    (Req 1.1·1.2·1.3·2.1·2.2·3.2)."""
    storage_root, _, _ = roots
    ws_id, doc_id = _seed_document(sessionmaker_factory)
    data = b"\x89PNG\r\n\x1a\n-fake-image-bytes"

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        result = service.upload_attachment(
            session,
            ctx,
            doc_id,
            kind=AttachmentKind.IMAGE,
            upload_filename="사진.png",
            stream=io.BytesIO(data),
            size=len(data),
        )
    finally:
        session.close()

    # 응답 계약: AttachmentRead + url 파생 규약.
    assert isinstance(result, AttachmentRead)
    assert result.kind == AttachmentKind.IMAGE
    assert result.original_name == "사진.png"
    assert result.document_id == doc_id
    assert result.workspace_id == ws_id, "WS 는 대상 문서에서 확정되어야 한다"
    assert result.is_archived is False
    assert result.url == f"/attachments/{result.id}"

    # 영속화된 레코드와 디스크 파일을 새 세션에서 확인(캐시 아님).
    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, result.id)
        assert row is not None
        assert row.kind == "image"
        assert row.original_name == "사진.png"
        assert row.workspace_id == ws_id
        assert row.document_id == doc_id
        assert row.is_archived is False
        # base64 인라인이 아니라 실제 파일로 저장되고, 그 파일에 업로드 바이트가 담긴다.
        saved = storage_root / row.file_path
        assert saved.is_file(), "붙여넣기 이미지는 실제 파일로 저장되어야 한다"
        assert saved.read_bytes() == data
        # 워크스페이스 격리: 파일이 해당 workspace_id 디렉터리 아래에 있다.
        assert saved.parent == storage_root / str(ws_id)
        # 디스크 파일명은 서버 생성이라 원본명과 다르다(트래버설 방지, 원본명은 DB 에만).
        assert Path(row.file_path).name != "사진.png"
    finally:
        verify.close()


# --- 파일 첨부 -----------------------------------------------------------


def test_upload_file_records_kind_file_and_original_name(
    sessionmaker_factory, roots, ctx
):
    """파일 첨부는 kind='file' 로 기록되고 원본 파일명을 보존한다(Req 2.1·2.2)."""
    storage_root, _, _ = roots
    ws_id, doc_id = _seed_document(sessionmaker_factory)
    data = b"%PDF-1.7 fake-pdf-bytes"

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        result = service.upload_attachment(
            session,
            ctx,
            doc_id,
            kind=AttachmentKind.FILE,
            upload_filename="보고서.pdf",
            stream=io.BytesIO(data),
            size=len(data),
        )
        assert result.kind == AttachmentKind.FILE
        assert result.original_name == "보고서.pdf"
        assert result.url == f"/attachments/{result.id}"
        att_id = result.id
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.kind == "file"
        assert row.original_name == "보고서.pdf"
        assert (storage_root / row.file_path).read_bytes() == data
    finally:
        verify.close()


# --- kind 미지정 기본값 --------------------------------------------------


def test_upload_kind_none_defaults_to_file(sessionmaker_factory, roots, ctx):
    """kind 미지정 시 방어적 기본값 FILE 로 기록한다(content-type 추론은 라우터 소관)."""
    _, _, _ = roots
    _ws_id, doc_id = _seed_document(sessionmaker_factory)
    data = b"unknown-bytes"

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        result = service.upload_attachment(
            session,
            ctx,
            doc_id,
            kind=None,
            upload_filename="blob.dat",
            stream=io.BytesIO(data),
            size=len(data),
        )
        assert result.kind == AttachmentKind.FILE
    finally:
        session.close()


# --- workspace_id 는 문서에서 확정(위조 불가) ---------------------------


def test_workspace_id_is_derived_from_document(sessionmaker_factory, roots, ctx):
    """소속 WS 는 클라이언트 입력이 아니라 대상 문서의 WS 로 확정된다(Req 3.2·8.3).

    서비스 시그니처에 workspace 파라미터가 없다는 사실이 위조를 차단하며, 영속된
    attachment.workspace_id 가 문서의 workspace 와 정확히 일치함을 확인한다.
    """
    _, _, _ = roots
    ws_id, doc_id = _seed_document(sessionmaker_factory)
    data = b"x"

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        result = service.upload_attachment(
            session,
            ctx,
            doc_id,
            kind=AttachmentKind.IMAGE,
            upload_filename="a.png",
            stream=io.BytesIO(data),
            size=len(data),
        )
        att_id = result.id
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.workspace_id == ws_id
    finally:
        verify.close()


# --- 존재하지 않는 문서 → 404 -------------------------------------------


def test_upload_missing_document_raises_404(sessionmaker_factory, roots, ctx):
    """대상 문서가 없으면 DomainError 404(NOT_FOUND)를 던진다(Req 1.5)."""
    _, _, _ = roots
    # 문서를 시드하지 않고 존재하지 않는 id 사용.
    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        with pytest.raises(DomainError) as exc:
            service.upload_attachment(
                session,
                ctx,
                999_999_999,
                kind=AttachmentKind.FILE,
                upload_filename="x.bin",
                stream=io.BytesIO(b"x"),
                size=1,
            )
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- 크기 한도 초과 → 422 -----------------------------------------------


def test_upload_exceeding_size_limit_raises_422(sessionmaker_factory, roots, ctx):
    """업로드 크기가 한도를 초과하면 DomainError 422(UNPROCESSABLE)이고 파일이 저장되지 않는다
    (Req 2.5)."""
    storage_root, _, settings = roots
    ws_id, doc_id = _seed_document(sessionmaker_factory)
    settings.attachment_max_bytes = 8  # 작은 한도로 조정.
    data = b"this-payload-is-larger-than-eight-bytes"

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        with pytest.raises(DomainError) as exc:
            service.upload_attachment(
                session,
                ctx,
                doc_id,
                kind=AttachmentKind.IMAGE,
                upload_filename="big.png",
                stream=io.BytesIO(data),
                size=len(data),
            )
        assert exc.value.http_status == 422
        assert exc.value.code == ErrorCode.UNPROCESSABLE
    finally:
        session.close()

    # 크기 위반은 저장 이전에 거부되므로 워크스페이스 저장 디렉터리에 파일이 생기지 않는다.
    ws_dir = storage_root / str(ws_id)
    if ws_dir.exists():
        assert list(ws_dir.iterdir()) == [], "크기 초과 업로드는 파일을 저장하지 않아야 한다"


# =====================================================================
# serve_attachment 단위 테스트 (Task 2.2 / Req 3.3, 6.2, 6.3)
#
# design.md §System Flows "첨부 조회 서빙 — 보관 비노출" flowchart 판정 순서를 실제 DB +
# tmp 저장소로 검증한다:
# - 미보관 첨부는 실제 저장 바이트를 담은 스트림과 원본명 기반 content-type 을 반환한다(Req 3.3).
# - 보관된 첨부는 요청자 role 과 무관하게(serve 는 role 인자를 받지 않으므로 admin 포함 무조건)
#   404 로 차단해 보관 파일을 노출하지 않는다(Req 6.2·6.3, 8.10, INV-7).
# - 존재하지 않는 attachment_id → 404(Req 3.3/부재).
# =====================================================================


def _upload_saved(sessionmaker_factory, ctx, *, kind, upload_filename, data):
    """서비스 업로드로 실제 파일 저장 + 레코드 생성 후 attachment id 를 반환한다(서빙 시드용)."""
    session = sessionmaker_factory()
    try:
        _ws_id, doc_id = _seed_document(sessionmaker_factory)
        service = AttachmentService()
        result = service.upload_attachment(
            session,
            ctx,
            doc_id,
            kind=kind,
            upload_filename=upload_filename,
            stream=io.BytesIO(data),
            size=len(data),
        )
        return result.id
    finally:
        session.close()


# --- 미보관 첨부: 실제 바이트 + content-type -----------------------------


def test_serve_unarchived_returns_bytes_and_content_type(
    sessionmaker_factory, roots, ctx
):
    """미보관 첨부 서빙은 저장된 실제 바이트를 담은 스트림과 원본명 기반 content-type 을 반환한다
    (Req 3.3)."""
    _, _, _ = roots
    data = b"\x89PNG\r\n\x1a\n-real-image-bytes"
    att_id = _upload_saved(
        sessionmaker_factory, ctx, kind=AttachmentKind.IMAGE,
        upload_filename="photo.png", data=data,
    )

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        binary = service.serve_attachment(session, att_id)
    finally:
        session.close()

    # 원본명(photo.png)에서 파생된 content-type + 서버가 서빙에 쓸 원본 파일명.
    assert binary.content_type == "image/png"
    assert binary.filename == "photo.png"
    # 스트림은 저장된 정확한 바이트를 그대로 방출한다(base64 인라인 아님).
    with binary.stream as fh:
        assert fh.read() == data


# --- content-type fallback (확장자 미상) ---------------------------------


def test_serve_unknown_extension_falls_back_to_octet_stream(
    sessionmaker_factory, roots, ctx
):
    """원본명에서 content-type 을 추론할 수 없으면 application/octet-stream 으로 폴백한다."""
    _, _, _ = roots
    data = b"unknown-binary-payload"
    att_id = _upload_saved(
        sessionmaker_factory, ctx, kind=AttachmentKind.FILE,
        upload_filename="blob", data=data,
    )

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        binary = service.serve_attachment(session, att_id)
    finally:
        session.close()

    assert binary.content_type == "application/octet-stream"
    assert binary.filename == "blob"
    with binary.stream as fh:
        assert fh.read() == data


# --- 보관된 첨부: role 무관 404(admin 포함) ------------------------------


def test_serve_archived_raises_404_role_agnostic(sessionmaker_factory, roots, ctx):
    """보관된 첨부는 요청자 role 과 무관하게 404 로 차단된다(Req 6.2·6.3, 8.10, INV-7).

    serve_attachment 은 role 인자를 받지 않으므로, admin 이 라우터 권한 게이트를 bypass 해
    이 지점에 도달하더라도 보관 첨부는 무조건 404 가 된다(권한 판정 이전 차단). 즉 role 을
    바꿔 넣을 여지가 없다는 사실 자체가 admin 포함 role-agnostic 성질을 보증한다.
    """
    _, _, _ = roots
    data = b"archived-image-bytes"
    att_id = _upload_saved(
        sessionmaker_factory, ctx, kind=AttachmentKind.IMAGE,
        upload_filename="secret.png", data=data,
    )

    # 첨부를 보관 상태로 표시(is_archived=True). 파일 이동 여부와 무관하게 DB 표시만으로 차단된다.
    mark = sessionmaker_factory()
    try:
        row = mark.get(Attachment, att_id)
        row.is_archived = True
        mark.commit()
    finally:
        mark.close()

    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        with pytest.raises(DomainError) as exc:
            service.serve_attachment(session, att_id)
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- 존재하지 않는 첨부 → 404 -------------------------------------------


def test_serve_missing_attachment_raises_404(sessionmaker_factory, roots, ctx):
    """존재하지 않는 attachment_id 서빙은 DomainError 404(NOT_FOUND)를 던진다(Req 3.3/부재)."""
    _, _, _ = roots
    session = sessionmaker_factory()
    try:
        service = AttachmentService()
        with pytest.raises(DomainError) as exc:
            service.serve_attachment(session, 999_999_999)
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()
