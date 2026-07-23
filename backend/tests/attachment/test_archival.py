"""ArchivalSweepService.archive_for_deleted_documents 단위 테스트
(Task 2.3 / Req 4.1, 4.2, 4.3, 4.4, 4.5, 7.7).

design.md §Components and Interfaces #ArchivalSweepService(Feature/Service)와 §System Flows
"완전삭제 반응 보관 이동 (8.6)" 판정을 실제 DB + tmp 저장소로 검증한다:
- deleted 문서에 연결된 미보관 첨부가 보관 폴더로 이동되고 `is_archived=true`가 되며, 파일이
  물리 삭제되지 않고 보관 위치에 존재한다(Req 4.1·4.2, INV-4). 반환 건수는 이동한 첨부 수다.
- 반복 실행은 이미 보관된 첨부를 스코프에서 제외해 두 번째 실행이 0을 반환하며 중복 이동/오류가
  없다(멱등, Req 4.4).
- 비-deleted(active/trashed) 문서의 미보관 첨부는 불변이다(스코프 격리, Req 4.5).
- 이미 보관된 첨부(deleted 문서)는 재처리하지 않는다.
- s12는 상태 전이·버전 생성을 하지 않으며 deleted 문서의 status 는 스윕 후에도 'deleted' 그대로다
  (관측만, Req 4.3·7.7).
- 첨부 단위 예외는 격리되어 한 첨부의 실패가 나머지 보관을 막지 않는다.

격리: tests/attachment/test_repository.py·test_service.py 의 확립된 테스트 DB 패턴을 재사용한다
(`DB_NAME` 을 `markspace_test` 로 swap, 새 엔진·create_all, uuid4 접미사 시드, 초 정밀도 시각).
저장/보관 루트는 tmp_path 하위를 가리키는 settings 대역을 storage 모듈에 monkeypatch 해 실제
config.yml 저장 루트에 의존하지 않는다. 물리 파일은 저장 루트에 직접 기록해 실제 이동을 관찰한다.
"""

import os
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.attachment.storage as storage_mod
import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.attachment.archival import ArchivalSweepService
from app.attachment.storage import AttachmentStorage
from app.common.db import Base
from app.models import Attachment, Document, DocumentVersion, User, Workspace

TEST_DB_NAME = "markspace_test"


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
    """Document 행을 직접 삽입하고 flush 한다(스코프 시드용)."""
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


def _make_attachment(
    session,
    *,
    workspace_id,
    document_id,
    kind="image",
    file_path=None,
    original_name="orig.png",
    is_archived=False,
    created_at=None,
):
    """Attachment 행을 직접 삽입하고 flush 한다(스코프 시드용)."""
    att = Attachment(
        workspace_id=workspace_id,
        document_id=document_id,
        file_path=file_path or f"{workspace_id}/{uuid4().hex}.png",
        original_name=original_name,
        kind=kind,
        is_archived=is_archived,
        created_at=created_at or datetime(2026, 7, 17, 9, 0, 0),
    )
    session.add(att)
    session.flush()
    return att


def _make_version(session, *, document_id, created_by, content, created_at):
    """DocumentVersion 행을 삽입하고 flush 한다(8.7 현재 버전 본문 시드용).

    현재 버전 본문에 `/attachments/{id}` 토큰을 담아 참조 관측을, created_at 을 조절해
    붙여넣기 보호 판정을 시드한다. DateTime(0) 초 정밀도이므로 초 단위 시각만 쓴다.
    """
    ver = DocumentVersion(
        document_id=document_id,
        content=content,
        created_by=created_by,
        created_at=created_at,
    )
    session.add(ver)
    session.flush()
    return ver


def _set_current_version(session, doc, version):
    """문서의 current_version_id 를 지정 버전으로 설정하고 flush 한다(현재 버전 관측 시드용)."""
    doc.current_version_id = version.id
    session.add(doc)
    session.flush()


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
    """저장/보관 루트를 tmp_path 하위로 격리한 settings 대역을 storage 모듈에 주입한다.

    AttachmentStorage 는 `app.attachment.storage.get_settings` 로 저장/보관 루트를 해석하므로,
    그 모듈의 get_settings 를 tmp 루트를 가리키는 namespace 로 대체해 실제 config.yml 루트에
    의존하지 않고 보관 이동을 관찰한다.
    """
    storage_root = tmp_path / "storage"
    archive_root = tmp_path / "archive"
    settings = types.SimpleNamespace(
        file_storage_root=str(storage_root),
        attachment_archive_root=str(archive_root),
    )
    monkeypatch.setattr(storage_mod, "get_settings", lambda: settings)
    return storage_root, archive_root


def _save_file(storage_root: Path, file_path: str, data: bytes) -> Path:
    """저장 루트 하위의 상대 경로에 실제 파일을 기록하고 그 절대 경로를 반환한다(시드용)."""
    dest = storage_root / file_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


# --- deleted 문서 첨부: 보관 이동 + 물리 삭제 없음(INV-4) -----------------


def test_archive_moves_unarchived_attachment_on_deleted_document(
    sessionmaker_factory, roots
):
    """deleted 문서의 미보관 첨부가 보관 이동·is_archived=true 가 되고 파일이 물리 삭제되지 않는다
    (Req 4.1·4.2, INV-4). 반환 건수는 1."""
    storage_root, archive_root = roots
    data = b"\x89PNG\r\n\x1a\n-deleted-doc-image"

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=rel_path,
            is_archived=False,
        )
        session.commit()
        att_id = att.id
        ws_id = ws.id
    finally:
        session.close()

    # 실제 저장 파일을 저장 루트에 기록(이동 관찰용).
    storage_file = _save_file(storage_root, rel_path, data)
    assert storage_file.is_file()

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_for_deleted_documents(session)
    finally:
        session.close()

    assert moved == 1, "deleted 문서의 미보관 첨부 1건이 보관 이동되어야 한다"

    # 새 세션 재조회로 영속화 확인(캐시 아님).
    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is True, "보관 이동 후 is_archived=true"
        archived_rel = f"{ws_id}/{Path(rel_path).name}"
        assert row.file_path == archived_rel, "file_path 가 보관 경로로 갱신되어야 한다"
    finally:
        verify.close()

    # INV-4: 파일은 물리 삭제되지 않고 보관 위치에 존재하며, 저장 위치에는 더 이상 없다.
    archived_file = archive_root / f"{ws_id}/{Path(rel_path).name}"
    assert archived_file.is_file(), "보관 파일은 물리적으로 존재해야 한다(INV-4)"
    assert archived_file.read_bytes() == data, "보관 파일 내용은 원본과 동일해야 한다"
    assert not storage_file.exists(), "저장 위치의 파일은 보관 위치로 이동되어야 한다"


# --- 멱등성: 두 번째 실행은 0(이미 보관 제외) --------------------------


def test_archive_is_idempotent_second_run_returns_zero(sessionmaker_factory, roots):
    """스윕을 두 번 실행하면 두 번째는 이미 보관된 첨부를 제외해 0 을 반환하고 오류가 없다
    (멱등, Req 4.4)."""
    storage_root, archive_root = roots
    data = b"idempotent-bytes"

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=rel_path,
            is_archived=False,
        )
        session.commit()
        att_id = att.id
        ws_id = ws.id
    finally:
        session.close()

    _save_file(storage_root, rel_path, data)

    service = ArchivalSweepService()
    session = sessionmaker_factory()
    try:
        first = service.archive_for_deleted_documents(session)
    finally:
        session.close()
    session = sessionmaker_factory()
    try:
        second = service.archive_for_deleted_documents(session)
    finally:
        session.close()

    assert first == 1, "첫 실행은 1건 이동"
    assert second == 0, "둘째 실행은 이미 보관되어 0건(멱등)"

    # 보관 파일이 이중 이동 없이 그대로 존재하고 내용이 온전하다.
    archived_file = archive_root / f"{ws_id}/{Path(rel_path).name}"
    assert archived_file.is_file()
    assert archived_file.read_bytes() == data

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is True
    finally:
        verify.close()


# --- 스코프 격리: 비-deleted 문서 첨부는 불변 ---------------------------


def test_archive_leaves_non_deleted_document_attachments_untouched(
    sessionmaker_factory, roots
):
    """active/trashed 문서의 미보관 첨부는 스윕 후에도 불변이다(스코프 격리, Req 4.5)."""
    storage_root, archive_root = roots

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        active_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        trashed_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="trashed"
        )
        active_rel = f"{ws.id}/{uuid4().hex}.png"
        trashed_rel = f"{ws.id}/{uuid4().hex}.png"
        active_att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=active_doc.id,
            file_path=active_rel,
            is_archived=False,
        )
        trashed_att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=trashed_doc.id,
            file_path=trashed_rel,
            is_archived=False,
        )
        session.commit()
        active_id = active_att.id
        trashed_id = trashed_att.id
    finally:
        session.close()

    active_file = _save_file(storage_root, active_rel, b"active-bytes")
    trashed_file = _save_file(storage_root, trashed_rel, b"trashed-bytes")

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_for_deleted_documents(session)
    finally:
        session.close()

    assert moved == 0, "비-deleted 문서 첨부는 스코프에서 제외되어 이동 대상이 없다"

    verify = sessionmaker_factory()
    try:
        assert verify.get(Attachment, active_id).is_archived is False
        assert verify.get(Attachment, active_id).file_path == active_rel
        assert verify.get(Attachment, trashed_id).is_archived is False
        assert verify.get(Attachment, trashed_id).file_path == trashed_rel
    finally:
        verify.close()

    # 파일은 저장 위치에 그대로 있고 보관 위치로 이동되지 않았다.
    assert active_file.is_file()
    assert trashed_file.is_file()
    assert not (archive_root / active_rel).exists()
    assert not (archive_root / trashed_rel).exists()


# --- 이미 보관된 첨부(deleted 문서)는 재처리 안 함 ----------------------


def test_archive_skips_already_archived_attachment_on_deleted_document(
    sessionmaker_factory, roots
):
    """deleted 문서라도 이미 보관된 첨부는 스코프에서 제외되어 재처리하지 않는다(Req 4.4)."""
    storage_root, archive_root = roots

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        # 이미 보관 표시된 첨부: file_path 는 보관 경로를 가리킨다.
        archived_rel = f"{ws.id}/{uuid4().hex}.png"
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=archived_rel,
            is_archived=True,
        )
        session.commit()
        att_id = att.id
    finally:
        session.close()

    # 보관 위치에만 파일 배치(이미 이동된 상태를 모사). 저장 위치엔 파일 없음.
    archived_file = _save_file(archive_root, archived_rel, b"already-archived")

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_for_deleted_documents(session)
    finally:
        session.close()

    assert moved == 0, "이미 보관된 첨부는 스코프에서 제외되어 재처리하지 않는다"
    assert archived_file.is_file(), "보관 파일은 그대로 유지된다"

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is True
        assert row.file_path == archived_rel
    finally:
        verify.close()


# --- 상태 전이·버전 생성 없음(관측만) ----------------------------------


def test_archive_does_not_transition_document_status(sessionmaker_factory, roots):
    """스윕은 deleted 문서의 status 를 전이하지 않고 관측만 한다(Req 4.3·7.7).

    보관 이동 후에도 deleted 문서의 status 는 'deleted' 그대로여야 한다(s12 가 상태를 만들지
    않음). 소스에 Document/version 쓰기가 없다는 구조적 사실과 함께 관측만임을 보증한다.
    """
    storage_root, _ = roots
    data = b"observe-only-bytes"

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=rel_path,
            is_archived=False,
        )
        session.commit()
        doc_id = deleted_doc.id
    finally:
        session.close()

    _save_file(storage_root, rel_path, data)

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        service.archive_for_deleted_documents(session)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        row = verify.get(Document, doc_id)
        assert row.status == "deleted", "s12 는 status 를 전이하지 않고 관측만 한다"
    finally:
        verify.close()


# --- 첨부 단위 예외 격리 ------------------------------------------------


class _FailingStorage:
    """특정 file_path 이동에서 예외를 던지고 나머지는 실제 스토리지에 위임하는 대역."""

    def __init__(self, real: AttachmentStorage, fail_path: str) -> None:
        self._real = real
        self._fail_path = fail_path

    def move_to_archive(self, *, workspace_id: int, file_path: str) -> str:
        if file_path == self._fail_path:
            raise RuntimeError("의도된 보관 이동 실패")
        return self._real.move_to_archive(
            workspace_id=workspace_id, file_path=file_path
        )


def test_archive_isolates_per_attachment_failure(sessionmaker_factory, roots):
    """한 첨부의 보관 이동 실패가 나머지 첨부의 보관을 막지 않고, 성공 건수만 반환한다(Req 4.4·4.5).

    실패 대상 첨부는 불변으로 남고, 나머지는 정상 보관된다.
    """
    storage_root, archive_root = roots

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        fail_rel = f"{ws.id}/{uuid4().hex}.png"
        ok_rel = f"{ws.id}/{uuid4().hex}.png"
        # id 오름차순(스코프 정렬)으로 실패 첨부가 먼저 처리되도록 먼저 시드.
        fail_att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=fail_rel,
            is_archived=False,
        )
        ok_att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=ok_rel,
            is_archived=False,
        )
        session.commit()
        fail_id = fail_att.id
        ok_id = ok_att.id
        ws_id = ws.id
    finally:
        session.close()

    fail_file = _save_file(storage_root, fail_rel, b"fail-bytes")
    _save_file(storage_root, ok_rel, b"ok-bytes")

    storage = _FailingStorage(AttachmentStorage(), fail_rel)
    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService(storage=storage)
        moved = service.archive_for_deleted_documents(session)
    finally:
        session.close()

    assert moved == 1, "실패 1건을 격리하고 성공 1건만 카운트한다"

    verify = sessionmaker_factory()
    try:
        failed = verify.get(Attachment, fail_id)
        succeeded = verify.get(Attachment, ok_id)
        assert failed.is_archived is False, "실패 첨부는 불변으로 남는다"
        assert failed.file_path == fail_rel
        assert succeeded.is_archived is True, "나머지 첨부는 정상 보관된다"
        assert succeeded.file_path == f"{ws_id}/{Path(ok_rel).name}"
    finally:
        verify.close()

    # 실패 첨부의 파일은 저장 위치에 그대로 있고, 성공 첨부만 보관으로 이동됐다.
    assert fail_file.is_file()
    assert (archive_root / f"{ws_id}/{Path(ok_rel).name}").is_file()


# ======================================================================
# 저장 참조 소멸 이미지 아카이브(8.7) — archive_dereferenced_images
# (Task 2.4 / Req 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.7)
#
# design.md §System Flows "저장 참조 소멸 아카이브 (8.7)" 판정을 실제 DB + tmp 저장소로
# 검증한다. 판정은 현재 버전 본문 참조 관측으로만 하며(붙여넣기 보호 포함) s12 는 저장·버전
# 생성·상태 전이를 수행하지 않는다.
# ======================================================================

# 붙여넣기 보호가 통과(proceed)하도록 att.created_at <= current_version.created_at.
_CUR_VER_AT = datetime(2026, 7, 17, 10, 0, 0)
_ATT_BEFORE = datetime(2026, 7, 17, 9, 0, 0)   # <= 현재 버전(저장 반영됨) → proceed
_ATT_AFTER = datetime(2026, 7, 17, 11, 0, 0)   # > 현재 버전(미저장 새 붙여넣기) → skip


# --- 참조 소멸 image: 보관 이동 + 물리 삭제 없음(Req 5.1) ------------------


def test_dereferenced_image_is_archived(sessionmaker_factory, roots):
    """현재 버전이 참조하지 않는 image(att.created_at<=현재버전)가 보관 이동·is_archived=true 되고
    파일이 물리 삭제되지 않는다(Req 5.1·5.2, INV-4). 반환 건수 1."""
    storage_root, archive_root = roots
    data = b"\x89PNG\r\n\x1a\n-dereferenced-image"

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            file_path=rel_path,
            is_archived=False,
            created_at=_ATT_BEFORE,
        )
        # 현재 버전 본문은 이 첨부를 참조하지 않는다(다른 첨부만 언급).
        ver = _make_version(
            session,
            document_id=doc.id,
            created_by=user.id,
            content="본문에 다른 이미지 /attachments/999999 만 있고 대상은 없음",
            created_at=_CUR_VER_AT,
        )
        _set_current_version(session, doc, ver)
        session.commit()
        att_id = att.id
        ws_id = ws.id
    finally:
        session.close()

    storage_file = _save_file(storage_root, rel_path, data)
    assert storage_file.is_file()

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_dereferenced_images(session)
    finally:
        session.close()

    assert moved == 1, "참조 소멸 image 1건이 보관 이동되어야 한다"

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is True, "참조 소멸 image 는 is_archived=true"
        assert row.file_path == f"{ws_id}/{Path(rel_path).name}"
    finally:
        verify.close()

    archived_file = archive_root / f"{ws_id}/{Path(rel_path).name}"
    assert archived_file.is_file(), "보관 파일은 물리적으로 존재해야 한다(INV-4)"
    assert archived_file.read_bytes() == data
    assert not storage_file.exists(), "저장 위치의 파일은 보관 위치로 이동되어야 한다"


# --- 현재 버전이 참조하는 image: 보관하지 않음(Req 5.5) --------------------


def test_referenced_image_is_kept(sessionmaker_factory, roots):
    """현재 버전 본문이 `/attachments/{id}` 로 참조하는 image 는 보관 이동하지 않는다(Req 5.5)."""
    storage_root, archive_root = roots

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            file_path=rel_path,
            is_archived=False,
            created_at=_ATT_BEFORE,
        )
        # 현재 버전 본문이 이 첨부를 참조한다.
        ver = _make_version(
            session,
            document_id=doc.id,
            created_by=user.id,
            content=f"![img](/attachments/{att.id}) 여전히 참조 중",
            created_at=_CUR_VER_AT,
        )
        _set_current_version(session, doc, ver)
        session.commit()
        att_id = att.id
    finally:
        session.close()

    storage_file = _save_file(storage_root, rel_path, b"referenced-bytes")

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_dereferenced_images(session)
    finally:
        session.close()

    assert moved == 0, "현재 버전이 참조하는 image 는 보관 대상이 아니다"

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is False, "참조되는 image 는 불변"
        assert row.file_path == rel_path
    finally:
        verify.close()

    assert storage_file.is_file(), "파일은 저장 위치에 그대로 있어야 한다"
    assert not (archive_root / rel_path).exists()


# --- 붙여넣기 보호: 미저장 새 붙여넣기 image 는 보관하지 않음(Req 5.3) -------


def test_unsaved_paste_image_is_not_archived(sessionmaker_factory, roots):
    """att.created_at > current_version.created_at 인 미저장 새 붙여넣기 image 는 참조되지 않아도
    보관 이동하지 않는다(붙여넣기 보호, Req 5.3)."""
    storage_root, archive_root = roots

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        # 첨부가 현재 버전보다 나중에 생성됨(방금 붙여넣었으나 아직 저장 안 됨).
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            file_path=rel_path,
            is_archived=False,
            created_at=_ATT_AFTER,
        )
        # 현재 버전 본문은 이 첨부를 참조하지 않는다(아직 저장 안 됨).
        ver = _make_version(
            session,
            document_id=doc.id,
            created_by=user.id,
            content="아직 이 붙여넣기가 반영되지 않은 이전 저장 본문",
            created_at=_CUR_VER_AT,
        )
        _set_current_version(session, doc, ver)
        session.commit()
        att_id = att.id
    finally:
        session.close()

    storage_file = _save_file(storage_root, rel_path, b"unsaved-paste-bytes")

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_dereferenced_images(session)
    finally:
        session.close()

    assert moved == 0, "미저장 새 붙여넣기 image 는 보관 대상이 아니다(붙여넣기 보호)"

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is False, "미저장 붙여넣기 image 는 불변"
        assert row.file_path == rel_path
    finally:
        verify.close()

    assert storage_file.is_file()
    assert not (archive_root / rel_path).exists()


# --- 이미지 한정: 일반 파일(kind='file')은 8.7 대상 아님(Req 5.6) ----------


def test_dereferenced_general_file_is_not_archived_by_87(sessionmaker_factory, roots):
    """참조되지 않는 일반 파일(kind='file')은 archive_dereferenced_images 스코프에서 제외되어
    보관 이동하지 않는다(이미지 한정, Req 5.6). 일반 파일은 8.6 으로만 처리된다."""
    storage_root, archive_root = roots

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.bin"
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            kind="file",  # 일반 파일 — 8.7 스코프 제외
            file_path=rel_path,
            original_name="doc.pdf",
            is_archived=False,
            created_at=_ATT_BEFORE,
        )
        # 현재 버전이 참조하지 않아도 image 가 아니라 보관 대상이 아니다.
        ver = _make_version(
            session,
            document_id=doc.id,
            created_by=user.id,
            content="일반 파일을 참조하지 않는 본문",
            created_at=_CUR_VER_AT,
        )
        _set_current_version(session, doc, ver)
        session.commit()
        att_id = att.id
    finally:
        session.close()

    storage_file = _save_file(storage_root, rel_path, b"general-file-bytes")

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_dereferenced_images(session)
    finally:
        session.close()

    assert moved == 0, "일반 파일은 8.7 참조 소멸 아카이브 대상이 아니다"

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is False, "일반 파일은 8.7 로 보관되지 않는다"
        assert row.file_path == rel_path
    finally:
        verify.close()

    assert storage_file.is_file()
    assert not (archive_root / rel_path).exists()


# --- wrong-version-join 방어: 현재 버전만으로 판정 -------------------------


def test_judgment_uses_current_version_not_older_version(sessionmaker_factory, roots):
    """현재 버전 문서에 참조하던 더 오래된 버전과 참조 안 하는 현재(최신) 버전이 둘 다 있을 때,
    판정은 현재 버전만 사용해 image 를 보관한다(잘못된 버전 조인 회귀 방어)."""
    storage_root, archive_root = roots
    data = b"current-version-judgment"

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            file_path=rel_path,
            is_archived=False,
            created_at=_ATT_BEFORE,
        )
        # 더 오래된 버전은 이 첨부를 참조했다(과거).
        _make_version(
            session,
            document_id=doc.id,
            created_by=user.id,
            content=f"과거 버전이 참조 ![img](/attachments/{att.id})",
            created_at=datetime(2026, 7, 17, 8, 0, 0),
        )
        # 현재(최신) 버전은 더 이상 참조하지 않는다.
        current = _make_version(
            session,
            document_id=doc.id,
            created_by=user.id,
            content="현재 버전은 그 이미지를 참조하지 않음",
            created_at=_CUR_VER_AT,
        )
        _set_current_version(session, doc, current)
        session.commit()
        att_id = att.id
        ws_id = ws.id
    finally:
        session.close()

    _save_file(storage_root, rel_path, data)

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        moved = service.archive_dereferenced_images(session)
    finally:
        session.close()

    assert moved == 1, "현재 버전이 참조하지 않으므로 보관 이동되어야 한다(현재 버전만 판정)"

    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is True
        assert row.file_path == f"{ws_id}/{Path(rel_path).name}"
    finally:
        verify.close()

    assert (archive_root / f"{ws_id}/{Path(rel_path).name}").is_file()


# --- 통합 스윕: 8.6 then 8.7, 멱등 ----------------------------------------


def test_sweep_runs_both_reactions_and_is_idempotent(sessionmaker_factory, roots):
    """sweep(db, now) 가 완전삭제 반응(8.6)과 참조 소멸(8.7)을 모두 수행해 합산 건수를 반환하고,
    두 번째 실행은 0 을 반환한다(멱등, Req 5.4)."""
    storage_root, archive_root = roots
    deleted_data = b"deleted-doc-8.6"
    deref_data = b"dereferenced-8.7"

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")

        # 8.6 대상: deleted 문서의 미보관 첨부.
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        deleted_rel = f"{ws.id}/{uuid4().hex}.png"
        deleted_att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=deleted_rel,
            is_archived=False,
        )

        # 8.7 대상: active 문서의 참조 소멸 image.
        active_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        deref_rel = f"{ws.id}/{uuid4().hex}.png"
        deref_att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=active_doc.id,
            file_path=deref_rel,
            is_archived=False,
            created_at=_ATT_BEFORE,
        )
        ver = _make_version(
            session,
            document_id=active_doc.id,
            created_by=user.id,
            content="현재 버전은 그 이미지를 참조하지 않음",
            created_at=_CUR_VER_AT,
        )
        _set_current_version(session, active_doc, ver)
        session.commit()
        deleted_id = deleted_att.id
        deref_id = deref_att.id
        ws_id = ws.id
    finally:
        session.close()

    _save_file(storage_root, deleted_rel, deleted_data)
    _save_file(storage_root, deref_rel, deref_data)

    now = datetime(2026, 7, 17, 12, 0, 0)
    service = ArchivalSweepService()

    session = sessionmaker_factory()
    try:
        first = service.sweep(session, now)
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        second = service.sweep(session, now)
    finally:
        session.close()

    assert first == 2, "sweep 은 8.6 1건 + 8.7 1건 = 2건을 처리해야 한다"
    assert second == 0, "두 번째 sweep 은 이미 보관되어 0(멱등)"

    verify = sessionmaker_factory()
    try:
        assert verify.get(Attachment, deleted_id).is_archived is True
        assert verify.get(Attachment, deref_id).is_archived is True
    finally:
        verify.close()

    assert (archive_root / f"{ws_id}/{Path(deleted_rel).name}").is_file()
    assert (archive_root / f"{ws_id}/{Path(deref_rel).name}").is_file()


# --- 상태/버전 무변경(관측만, Req 7.7) ------------------------------------


def test_sweep_does_not_mutate_document_state(sessionmaker_factory, roots):
    """sweep 후에도 문서 status·current_version_id 가 불변이다(s12 는 상태 전이·버전 생성 없음,
    Req 5.4·7.7)."""
    storage_root, _ = roots

    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            file_path=rel_path,
            is_archived=False,
            created_at=_ATT_BEFORE,
        )
        ver = _make_version(
            session,
            document_id=doc.id,
            created_by=user.id,
            content="참조 없음",
            created_at=_CUR_VER_AT,
        )
        _set_current_version(session, doc, ver)
        session.commit()
        doc_id = doc.id
        ver_id = ver.id
    finally:
        session.close()

    _save_file(storage_root, rel_path, b"state-immutable")

    session = sessionmaker_factory()
    try:
        service = ArchivalSweepService()
        service.sweep(session, datetime(2026, 7, 17, 12, 0, 0))
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        row = verify.get(Document, doc_id)
        assert row.status == "active", "s12 는 문서 status 를 전이하지 않는다"
        assert row.current_version_id == ver_id, "s12 는 current_version_id 를 바꾸지 않는다"
        # 버전이 새로 생성되지 않았음을 확인(버전 1개 유지).
        count = verify.scalar(
            text("SELECT COUNT(*) FROM document_version WHERE document_id = :d"),
            {"d": doc_id},
        )
        assert count == 1, "s12 는 버전을 생성하지 않는다"
    finally:
        verify.close()
