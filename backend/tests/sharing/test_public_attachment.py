"""PublicShareService.serve_public_attachment 단위 테스트
(Task 2.3 / Req 6.1, 6.2, 6.3, 6.4, 6.5, 7.7).

design.md §Components and Interfaces #PublicShareService(serve_public_attachment 계약)·
§System Flows(링크 경유 첨부 서빙 flowchart)·§Security(파일 격리·보관)를 실제 DB + 실제 파일
저장소로 검증한다:

- 공유 문서·그 현재 active 하위에 속한 미보관 첨부는 링크 경유로 실제 바이너리(스트림 +
  content-type)를 반환한다(Req 6.1).
- 게이트 off(is_shareable=False)·공유 문서 trashed 접근은 파일도 함께 404 로 차단한다(Req 6.2,
  공개 렌더와 동일한 실시간 게이트 재사용).
- 보관(is_archived=True) 첨부는 role·경로 무관 404 로 비노출한다(Req 6.3, s12 serve 위임).
- 공유 문서·active 하위에 속하지 않거나(범위 밖) 다른 워크스페이스 첨부는 404 로 차단한다
  (Req 6.4, INV-6 격리).
- 부재 첨부 id·미존재 토큰은 404(정보 비노출).
- 저장·격리·보관 판정은 s12 를 재사용하고 재구현하지 않는다(Req 6.5·7.7): 실제 s12
  AttachmentService.upload_attachment 로 파일을 저장하고 serve 를 s12 에 위임함을 관찰한다.

격리: tests/sharing/test_public_service.py 의 테스트 DB 패턴 + tests/attachment/test_service.py
의 tmp 저장 루트 monkeypatch 패턴을 결합한다. 공유 테스트 DB 충돌을 피하려 이름/제목에 uuid4
접미사를, DATETIME(0) 반올림을 피하려 초 정밀도 시각을 쓴다.
"""

import io
import os
import types
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.attachment.service as service_mod
import app.attachment.storage as storage_mod
import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.attachment.schemas import AttachmentKind
from app.attachment.service import AttachmentBinary, AttachmentService
from app.common.auth import AuthContext
from app.common.db import Base
from app.common.errors import ErrorCode
from app.models import Attachment, Document, User, Workspace
from app.sharing.public_service import PublicShareService
from app.sharing.repository import ShareLinkRepository

TEST_DB_NAME = "notion_lite_test"
_DEFAULT_MAX_BYTES = 26214400  # config 기본 25MiB

# DATETIME(0) 반올림을 피하기 위한 초 정밀도 고정 시각.
_FIXED_TIME = datetime(2026, 7, 17, 9, 0, 0)


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
    user = User(
        login_id=login_id,
        password_hash="hash-initial",
        name="테스트 사용자",
        email=None,
        is_admin=False,
        is_active=True,
        is_deleted=False,
        created_at=_FIXED_TIME,
    )
    session.add(user)
    session.flush()
    return user


def _make_workspace(session, *, name="ws", is_shareable=True):
    ws = Workspace(
        name=name,
        is_shareable=is_shareable,
        trash_retention_days=30,
        created_at=_FIXED_TIME,
    )
    session.add(ws)
    session.flush()
    return ws


def _make_document(
    session,
    *,
    workspace_id,
    created_by,
    parent_id=None,
    title="문서",
    status="active",
    sort_order=Decimal("1000"),
):
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        created_by=created_by,
        created_at=_FIXED_TIME,
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

    _drop_everything(engine)
    Base.metadata.create_all(engine)

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
    """저장/보관 루트를 tmp_path 하위로 격리한 settings 대역을 storage·service 에 주입한다.

    `AttachmentStorage`/`AttachmentService` 는 각 모듈의 `get_settings()` 를 호출 시점에
    읽으므로, 두 모듈을 tmp 루트로 돌리면 업로드가 실제 파일을 tmp 로 저장하고 링크 경유 서빙이
    그 파일을 실제 스트림으로 연다(실제 config.yml 저장 루트 비오염).
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


def _upload_attachment(
    sessionmaker_factory, ctx, *, document_id, kind, upload_filename, data
):
    """실제 s12 AttachmentService 로 파일을 저장하고 첨부 레코드를 생성해 id 를 반환한다."""
    session = sessionmaker_factory()
    try:
        result = AttachmentService().upload_attachment(
            session,
            ctx,
            document_id,
            kind=kind,
            upload_filename=upload_filename,
            stream=io.BytesIO(data),
            size=len(data),
        )
        return result.id
    finally:
        session.close()


def _assert_404(exc_value) -> None:
    """공개 경로 거부는 항상 404 NOT_FOUND(정보 비노출)임을 단언한다."""
    assert getattr(exc_value, "http_status", None) == 404
    assert getattr(exc_value, "code", None) == ErrorCode.NOT_FOUND


# --- (a) 공유 문서에 속한 미보관 첨부 → 바이너리 ---------------------------


def test_serve_attachment_on_shared_document_returns_binary(
    sessionmaker_factory, roots, ctx
):
    """공유 문서에 속한 미보관 첨부는 링크 경유로 실제 바이너리를 반환한다(Req 6.1·7.7)."""
    data = b"\x89PNG\r\n\x1a\n-shared-root-image"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        root_id = root.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=root_id,
        kind=AttachmentKind.IMAGE,
        upload_filename="photo.png",
        data=data,
    )

    session = sessionmaker_factory()
    try:
        binary = PublicShareService().serve_public_attachment(
            session, token, att_id
        )
        assert isinstance(binary, AttachmentBinary)
        assert binary.content_type == "image/png"
        assert binary.filename == "photo.png"
        with binary.stream as fh:
            assert fh.read() == data
    finally:
        session.close()


# --- (b) active 하위 문서에 속한 첨부 → 바이너리 ---------------------------


def test_serve_attachment_on_active_descendant_returns_binary(
    sessionmaker_factory, roots, ctx
):
    """공유 문서의 active 하위에 속한 미보관 첨부도 링크 경유로 서빙된다(Req 6.1·INV-6 소속)."""
    data = b"child-doc-file-bytes"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        child = _make_document(
            session,
            workspace_id=ws.id,
            created_by=user.id,
            parent_id=root.id,
            title="자식",
            sort_order=Decimal("2000"),
        )
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        child_id = child.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=child_id,
        kind=AttachmentKind.FILE,
        upload_filename="report.pdf",
        data=data,
    )

    session = sessionmaker_factory()
    try:
        binary = PublicShareService().serve_public_attachment(
            session, token, att_id
        )
        assert binary.filename == "report.pdf"
        with binary.stream as fh:
            assert fh.read() == data
    finally:
        session.close()


# --- (c) 게이트 off → 404 --------------------------------------------------


def test_gate_off_blocks_attachment_access(sessionmaker_factory, roots, ctx):
    """게이트 off(is_shareable=False)면 링크 경유 첨부 접근도 함께 404 로 차단된다(Req 6.2)."""
    data = b"gated-image-bytes"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}", is_shareable=True)
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        root_id = root.id
        ws_id = ws.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=root_id,
        kind=AttachmentKind.IMAGE,
        upload_filename="pic.png",
        data=data,
    )

    # 게이트 off(s05 가 만든 상태를 관측).
    session = sessionmaker_factory()
    try:
        session.get(Workspace, ws_id).is_shareable = False
        session.commit()
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(session, token, att_id)
        _assert_404(exc.value)
    finally:
        session.close()


# --- (d) 공유 문서 trashed → 404 ------------------------------------------


def test_trashed_document_blocks_attachment_access(
    sessionmaker_factory, roots, ctx
):
    """공유 문서가 trashed 이면 링크 경유 첨부 접근도 404 로 차단된다(Req 6.2)."""
    data = b"trashed-doc-image"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        root_id = root.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=root_id,
        kind=AttachmentKind.IMAGE,
        upload_filename="pic.png",
        data=data,
    )

    # 문서 trashed 처리.
    session = sessionmaker_factory()
    try:
        session.get(Document, root_id).status = "trashed"
        session.commit()
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(session, token, att_id)
        _assert_404(exc.value)
    finally:
        session.close()


# --- (e) 보관 첨부 → 404 (s12 위임, role 무관) ----------------------------


def test_archived_attachment_returns_404(sessionmaker_factory, roots, ctx):
    """보관(is_archived=True) 첨부는 s12 serve 위임으로 role·경로 무관 404(Req 6.3)."""
    data = b"archived-secret-bytes"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        root_id = root.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=root_id,
        kind=AttachmentKind.IMAGE,
        upload_filename="secret.png",
        data=data,
    )

    # 첨부를 보관 상태로 표시(범위·게이트는 유효하나 보관 차단으로 404).
    session = sessionmaker_factory()
    try:
        session.get(Attachment, att_id).is_archived = True
        session.commit()
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(session, token, att_id)
        _assert_404(exc.value)
    finally:
        session.close()


# --- (f) 범위 밖(비-member) 문서 첨부 → 404 --------------------------------


def test_out_of_scope_document_attachment_returns_404(
    sessionmaker_factory, roots, ctx
):
    """공유 서브트리에 속하지 않는 문서의 첨부는 범위 밖으로 404(Req 6.4·INV-6)."""
    data = b"unrelated-doc-bytes"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        # 같은 WS 이지만 공유 루트의 하위가 아닌 무관한 문서.
        unrelated = _make_document(
            session,
            workspace_id=ws.id,
            created_by=user.id,
            title="무관",
            sort_order=Decimal("5000"),
        )
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        unrelated_id = unrelated.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=unrelated_id,
        kind=AttachmentKind.IMAGE,
        upload_filename="other.png",
        data=data,
    )

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(session, token, att_id)
        _assert_404(exc.value)
    finally:
        session.close()


def test_trashed_descendant_attachment_returns_404(
    sessionmaker_factory, roots, ctx
):
    """trashed 하위(현재 active 서브트리에서 제외)의 첨부는 범위 밖으로 404(Req 6.4·INV-6)."""
    data = b"trashed-child-bytes"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        child = _make_document(
            session,
            workspace_id=ws.id,
            created_by=user.id,
            parent_id=root.id,
            title="자식",
            sort_order=Decimal("2000"),
        )
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        child_id = child.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=child_id,
        kind=AttachmentKind.IMAGE,
        upload_filename="child.png",
        data=data,
    )

    # 하위를 trashed 로 전환 → 현재 active 서브트리에서 제외됨.
    session = sessionmaker_factory()
    try:
        session.get(Document, child_id).status = "trashed"
        session.commit()
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(session, token, att_id)
        _assert_404(exc.value)
    finally:
        session.close()


# --- (g) 다른 워크스페이스 첨부 → 404 ------------------------------------


def test_different_workspace_attachment_returns_404(
    sessionmaker_factory, roots, ctx
):
    """다른 워크스페이스에 속한 첨부는 링크 범위 밖으로 404(Req 6.4·INV-6 격리)."""
    data = b"other-workspace-bytes"
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        # 다른 워크스페이스 + 그 안의 문서.
        other_ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        other_doc = _make_document(
            session, workspace_id=other_ws.id, created_by=user.id, title="타 WS 문서"
        )
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        other_doc_id = other_doc.id
    finally:
        session.close()

    att_id = _upload_attachment(
        sessionmaker_factory,
        ctx,
        document_id=other_doc_id,
        kind=AttachmentKind.IMAGE,
        upload_filename="foreign.png",
        data=data,
    )

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(session, token, att_id)
        _assert_404(exc.value)
    finally:
        session.close()


# --- (h) 부재 첨부 id → 404 -----------------------------------------------


def test_missing_attachment_returns_404(sessionmaker_factory, roots, ctx):
    """존재하지 않는 attachment_id 는 404(부재, 정보 비노출)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(
                session, token, 999_999_999
            )
        _assert_404(exc.value)
    finally:
        session.close()


# --- (i) 미존재 토큰 → 404 ------------------------------------------------


def test_unknown_token_returns_404(sessionmaker_factory, roots, ctx):
    """존재하지 않는 토큰은 404(무효 링크, 정보 비노출)."""
    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().serve_public_attachment(
                session, "no-such-token", 1
            )
        _assert_404(exc.value)
    finally:
        session.close()
