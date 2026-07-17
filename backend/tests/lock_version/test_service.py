"""LockVersionService 통합 테스트 (Task 2.1 / Req 1.1, 1.2, 1.3, 1.4, 1.6, 6.1).

design.md §Components and Interfaces #LockVersionService 의 `start_edit` 계약을 실제 DB 로
검증한다(§System Flows 편집 시작(획득) flowchart, §Error Handling):
- 미잠금 문서 → 요청자·획득 시각 기록, fresh 세션 재조회로 영속화 증명(1.1).
- 동일 보유자 재시작 → 멱등 성공, 잠금 불변(획득 시각 미변경)(1.3·1.4).
- 타인 잠금 문서 → 409 conflict, 잠금 불변(1.2).
- 문서 미존재 → 404 not_found(1.6).
- start 는 문서 `status` 를 검사·변경하지 않는다(잠금·삭제 독립, §4.3·6.1).

격리: tests/document/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 원복한다.
"""

import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.auth import AuthContext
from app.common.db import Base
from app.common.errors import DomainError, ErrorCode
from app.lock_version.repository import LockVersionRepository
from app.lock_version.schemas import DocumentSaveRequest
from app.lock_version.service import LockVersionService
from app.models import Document, DocumentVersion, User, Workspace

TEST_DB_NAME = "notion_lite_test"


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
    """Workspace 행을 삽입하고 flush 한다(document.workspace_id FK 충족용)."""
    ws = Workspace(
        name=name,
        is_shareable=False,
        trash_retention_days=30,
        created_at=datetime.utcnow(),
    )
    session.add(ws)
    session.flush()
    return ws


def _make_document(
    session,
    *,
    workspace_id,
    created_by,
    status="active",
    lock_user_id=None,
    lock_acquired_at=None,
):
    """Document 행을 직접 삽입하고 flush 한다(잠금 상태 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=None,
        title="문서",
        status=status,
        sort_order=Decimal("1000"),
        current_version_id=None,
        trashed_at=None,
        lock_user_id=lock_user_id,
        lock_acquired_at=lock_acquired_at,
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


def _service() -> LockVersionService:
    return LockVersionService(LockVersionRepository())


# --- start_edit: 미잠금 문서 획득 ----------------------------------------


def test_start_edit_acquires_lock_on_unlocked_document(sessionmaker_factory):
    """미잠금 문서에 start_edit → 요청자·획득 시각 기록, fresh 세션 재조회로 영속화 증명 (Req 1.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="acq")
        ws = _make_workspace(seed, name="ws-acq")
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().start_edit(session, ctx, doc_id)
        assert result.document_id == doc_id
        assert result.lock_user_id == user_id
        assert result.lock_acquired_at is not None
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id == user_id, "잠금이 영속화되어야 한다"
        assert reloaded.lock_acquired_at is not None
    finally:
        verify.close()


# --- start_edit: 동일 보유자 재시작(멱등) --------------------------------


def test_start_edit_same_holder_is_idempotent_and_unchanged(sessionmaker_factory):
    """동일 보유자 재시작 → 멱등 성공, 잠금·획득 시각 불변(bump 없음) (Req 1.3·1.4)."""
    known_at = datetime(2026, 7, 16, 9, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="holder")
        ws = _make_workspace(seed, name="ws-idem")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            lock_user_id=user.id,
            lock_acquired_at=known_at,
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().start_edit(session, ctx, doc_id)
        assert result.lock_user_id == user_id
        assert result.lock_acquired_at == known_at, "획득 시각을 bump 하지 않아야 한다"
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id == user_id
        assert reloaded.lock_acquired_at == known_at, "잠금은 불변이어야 한다"
    finally:
        verify.close()


# --- start_edit: 타인 잠금 → 409 -----------------------------------------


def test_start_edit_other_holder_raises_conflict(sessionmaker_factory):
    """타인 잠금 문서에 start_edit → 409 conflict, 잠금 불변 (Req 1.2)."""
    other_at = datetime(2026, 7, 16, 8, 0, 0)
    seed = sessionmaker_factory()
    try:
        holder = _make_user(seed, login_id="other-holder")
        requester = _make_user(seed, login_id="requester")
        ws = _make_workspace(seed, name="ws-conflict")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=holder.id,
            lock_user_id=holder.id,
            lock_acquired_at=other_at,
        )
        seed.commit()
        doc_id, holder_id, requester_id = doc.id, holder.id, requester.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=requester_id, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().start_edit(session, ctx, doc_id)
        assert excinfo.value.http_status == 409
        assert excinfo.value.code == ErrorCode.CONFLICT
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id == holder_id, "타인 잠금은 변경되지 않아야 한다"
        assert reloaded.lock_acquired_at == other_at
    finally:
        verify.close()


# --- start_edit: 문서 미존재 → 404 ---------------------------------------


def test_start_edit_missing_document_raises_not_found(sessionmaker_factory):
    """존재하지 않는 문서에 start_edit → 404 not_found (Req 1.6)."""
    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=1, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().start_edit(session, ctx, 999999)
        assert excinfo.value.http_status == 404
        assert excinfo.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- start_edit: status 무검사·무변경(잠금·삭제 독립, §4.3) --------------


def test_start_edit_does_not_touch_status(sessionmaker_factory):
    """start_edit 은 문서 status 를 검사·변경하지 않는다 (잠금·삭제 독립, §4.3·6.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="statindep")
        ws = _make_workspace(seed, name="ws-status")
        # trashed 문서에도 잠금 획득이 status 와 무관하게 동작해야 한다.
        doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, status="trashed"
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().start_edit(session, ctx, doc_id)
        assert result.lock_user_id == user_id
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.status == "trashed", "status 는 start_edit 로 변경되지 않아야 한다"
        assert reloaded.lock_user_id == user_id, "status 와 무관하게 잠금은 획득되어야 한다"
    finally:
        verify.close()


# --- save 헬퍼 ------------------------------------------------------------


def _count_versions(session, document_id) -> int:
    """해당 문서의 `document_version` 행 개수를 반환한다(버전 미생성 증명용)."""
    return (
        session.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .count()
    )


# --- save: 보유자 저장(버전 생성·current 갱신·잠금 해제) -----------------


def test_save_by_holder_creates_version_updates_current_and_clears_lock(
    sessionmaker_factory,
):
    """보유자 저장 → 새 버전 생성·current 갱신·잠금 해제가 fresh 세션에서 함께 관찰됨 (Req 2.1·2.2·2.3·2.6)."""
    locked_at = datetime(2026, 7, 16, 9, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="saver")
        ws = _make_workspace(seed, name="ws-save")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            lock_user_id=user.id,
            lock_acquired_at=locked_at,
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().save(
            session, ctx, doc_id, DocumentSaveRequest(content="새 본문")
        )
        assert result.document_id == doc_id
        assert result.created_by == user_id
        assert result.id is not None
        assert result.created_at is not None
        returned_version_id = result.id
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        # 세 효과가 fresh 세션에서 함께 관찰됨 → 한 트랜잭션으로 커밋됨을 증명.
        versions = (
            verify.query(DocumentVersion)
            .filter(DocumentVersion.document_id == doc_id)
            .all()
        )
        assert len(versions) == 1, "저장으로 정확히 한 버전만 생성되어야 한다"
        version = versions[0]
        assert version.id == returned_version_id, "반환된 Read 가 영속 행과 일치해야 한다"
        assert version.content == "새 본문"
        assert version.created_by == user_id

        reloaded = verify.get(Document, doc_id)
        assert reloaded.current_version_id == version.id, "current_version_id 갱신"
        assert reloaded.lock_user_id is None, "잠금 해제되어야 한다"
        assert reloaded.lock_acquired_at is None, "잠금 획득 시각도 NULL"
    finally:
        verify.close()


def test_save_by_holder_allows_empty_content(sessionmaker_factory):
    """빈 문자열 본문도 유효한 저장이다 → 버전 생성됨 (Req 2.6)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="emptysaver")
        ws = _make_workspace(seed, name="ws-empty")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            lock_user_id=user.id,
            lock_acquired_at=datetime(2026, 7, 16, 9, 0, 0),
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().save(
            session, ctx, doc_id, DocumentSaveRequest(content="")
        )
        version_id = result.id
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        version = verify.get(DocumentVersion, version_id)
        assert version is not None
        assert version.content == "", "빈 문자열 본문이 그대로 저장되어야 한다"
        reloaded = verify.get(Document, doc_id)
        assert reloaded.current_version_id == version_id
        assert reloaded.lock_user_id is None
    finally:
        verify.close()


# --- save: 미잠금 문서 저장 → 409, 버전 미생성 ---------------------------


def test_save_on_unlocked_document_raises_conflict_and_creates_no_version(
    sessionmaker_factory,
):
    """미잠금 문서에 비보유자 저장 → 409, 버전 미생성, 잠금 여전히 NULL (Req 2.5)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="nolock")
        ws = _make_workspace(seed, name="ws-nolock")
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().save(
                session, ctx, doc_id, DocumentSaveRequest(content="변경")
            )
        assert excinfo.value.http_status == 409
        assert excinfo.value.code == ErrorCode.CONFLICT
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        assert _count_versions(verify, doc_id) == 0, "409 경로는 버전을 만들지 않는다"
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id is None, "잠금은 여전히 NULL"
        assert reloaded.current_version_id is None, "current 도 갱신되지 않는다"
    finally:
        verify.close()


# --- save: 타인 잠금 문서 저장 → 409, 버전 미생성 -----------------------


def test_save_on_other_holder_raises_conflict_and_leaves_lock_unchanged(
    sessionmaker_factory,
):
    """타인 잠금 문서에 저장 → 409, 버전 미생성, 타인 잠금 불변 (Req 2.5)."""
    other_at = datetime(2026, 7, 16, 8, 0, 0)
    seed = sessionmaker_factory()
    try:
        holder = _make_user(seed, login_id="save-holder")
        requester = _make_user(seed, login_id="save-requester")
        ws = _make_workspace(seed, name="ws-otherlock")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=holder.id,
            lock_user_id=holder.id,
            lock_acquired_at=other_at,
        )
        seed.commit()
        doc_id, holder_id, requester_id = doc.id, holder.id, requester.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=requester_id, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().save(
                session, ctx, doc_id, DocumentSaveRequest(content="침범")
            )
        assert excinfo.value.http_status == 409
        assert excinfo.value.code == ErrorCode.CONFLICT
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        assert _count_versions(verify, doc_id) == 0, "409 경로는 버전을 만들지 않는다"
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id == holder_id, "타인 잠금은 변경되지 않아야 한다"
        assert reloaded.lock_acquired_at == other_at
        assert reloaded.current_version_id is None
    finally:
        verify.close()


# --- save: 문서 미존재 → 404 ---------------------------------------------


def test_save_missing_document_raises_not_found(sessionmaker_factory):
    """존재하지 않는 문서 저장 → 404 not_found (Req 2 / §Error Handling)."""
    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=1, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().save(
                session, ctx, 999999, DocumentSaveRequest(content="x")
            )
        assert excinfo.value.http_status == 404
        assert excinfo.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- save: status 무검사·무변경(잠금·삭제 독립, §4.3) --------------------


def test_save_does_not_touch_status(sessionmaker_factory):
    """trashed+locked 문서 저장 성공, status 는 여전히 trashed (잠금·삭제 독립, §4.3·6.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="save-statindep")
        ws = _make_workspace(seed, name="ws-save-status")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            status="trashed",
            lock_user_id=user.id,
            lock_acquired_at=datetime(2026, 7, 16, 9, 0, 0),
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().save(
            session, ctx, doc_id, DocumentSaveRequest(content="trashed 저장")
        )
        version_id = result.id
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.status == "trashed", "status 는 save 로 변경되지 않아야 한다"
        assert reloaded.current_version_id == version_id, "status 와 무관하게 저장 성공"
        assert reloaded.lock_user_id is None, "잠금 해제됨"
    finally:
        verify.close()


# --- cancel_edit: 보유자 취소 → 잠금 해제, 버전 미생성 -------------------


def test_cancel_edit_by_holder_clears_lock_and_creates_no_version(
    sessionmaker_factory,
):
    """보유자 취소 → 잠금 필드 NULL, fresh 세션 재조회로 증명, 버전 미생성 (Req 3.1·3.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="cancel-holder")
        ws = _make_workspace(seed, name="ws-cancel")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            lock_user_id=user.id,
            lock_acquired_at=datetime(2026, 7, 16, 9, 0, 0),
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().cancel_edit(session, ctx, doc_id)
        assert result is None
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id is None, "잠금 해제되어야 한다"
        assert reloaded.lock_acquired_at is None, "잠금 획득 시각도 NULL"
        assert _count_versions(verify, doc_id) == 0, "취소는 버전을 만들지 않는다"
    finally:
        verify.close()


# --- cancel_edit: 미잠금 문서 → 멱등 no-op -------------------------------


def test_cancel_edit_on_unlocked_document_is_idempotent(sessionmaker_factory):
    """미잠금 문서 취소 → 멱등 성공(변경 없음), 여전히 NULL, 버전 미생성 (Req 3.2·3.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="cancel-noop")
        ws = _make_workspace(seed, name="ws-cancel-noop")
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().cancel_edit(session, ctx, doc_id)
        assert result is None
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id is None, "여전히 미잠금이어야 한다"
        assert reloaded.lock_acquired_at is None
        assert _count_versions(verify, doc_id) == 0, "취소는 버전을 만들지 않는다"
    finally:
        verify.close()


# --- cancel_edit: 타인 잠금 → 409, 잠금 불변 ----------------------------


def test_cancel_edit_on_other_holder_raises_conflict_and_leaves_lock(
    sessionmaker_factory,
):
    """타인 잠금 문서 취소 → 409, 타인 잠금 불변, 버전 미생성 (Req 3.3·3.4)."""
    other_at = datetime(2026, 7, 16, 8, 0, 0)
    seed = sessionmaker_factory()
    try:
        holder = _make_user(seed, login_id="cancel-holder2")
        requester = _make_user(seed, login_id="cancel-requester")
        ws = _make_workspace(seed, name="ws-cancel-conflict")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=holder.id,
            lock_user_id=holder.id,
            lock_acquired_at=other_at,
        )
        seed.commit()
        doc_id, holder_id, requester_id = doc.id, holder.id, requester.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=requester_id, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().cancel_edit(session, ctx, doc_id)
        assert excinfo.value.http_status == 409
        assert excinfo.value.code == ErrorCode.CONFLICT
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id == holder_id, "타인 잠금은 변경되지 않아야 한다"
        assert reloaded.lock_acquired_at == other_at
        assert _count_versions(verify, doc_id) == 0, "취소 거부는 버전을 만들지 않는다"
    finally:
        verify.close()


# --- cancel_edit: 문서 미존재 → 404 -------------------------------------


def test_cancel_edit_missing_document_raises_not_found(sessionmaker_factory):
    """존재하지 않는 문서 취소 → 404 not_found (Req 3 / §Error Handling)."""
    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=1, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().cancel_edit(session, ctx, 999999)
        assert excinfo.value.http_status == 404
        assert excinfo.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- force_unlock: 비보유자 강제 해제 → 잠금 해제(보유자 무관) ----------


def test_force_unlock_by_non_holder_clears_lock_and_creates_no_version(
    sessionmaker_factory,
):
    """비보유자(타인) 강제 해제 → 보유자 무관 잠금 해제, 버전 미생성 (Req 4.1)."""
    other_at = datetime(2026, 7, 16, 8, 0, 0)
    seed = sessionmaker_factory()
    try:
        holder = _make_user(seed, login_id="force-holder")
        actor = _make_user(seed, login_id="force-actor")
        ws = _make_workspace(seed, name="ws-force")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=holder.id,
            lock_user_id=holder.id,
            lock_acquired_at=other_at,
        )
        seed.commit()
        doc_id, actor_id = doc.id, actor.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        # actor 는 잠금 보유자가 아니지만 강제 해제는 보유자와 무관하게 성공해야 한다.
        ctx = AuthContext(user_id=actor_id, is_admin=False)
        result = _service().force_unlock(session, ctx, doc_id)
        assert result is None
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id is None, "보유자 무관 잠금 해제되어야 한다"
        assert reloaded.lock_acquired_at is None
        assert _count_versions(verify, doc_id) == 0, "강제 해제는 버전을 만들지 않는다"
    finally:
        verify.close()


# --- force_unlock: 미잠금 문서 → 멱등 no-op ------------------------------


def test_force_unlock_on_unlocked_document_is_idempotent(sessionmaker_factory):
    """미잠금 문서 강제 해제 → 멱등 성공, 여전히 NULL, 버전 미생성 (Req 4.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="force-noop")
        ws = _make_workspace(seed, name="ws-force-noop")
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        result = _service().force_unlock(session, ctx, doc_id)
        assert result is None
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id is None, "여전히 미잠금이어야 한다"
        assert reloaded.lock_acquired_at is None
        assert _count_versions(verify, doc_id) == 0, "강제 해제는 버전을 만들지 않는다"
    finally:
        verify.close()


# --- force_unlock: 문서 미존재 → 404 ------------------------------------


def test_force_unlock_missing_document_raises_not_found(sessionmaker_factory):
    """존재하지 않는 문서 강제 해제 → 404 not_found (Req 4 / §Error Handling)."""
    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=1, is_admin=False)
        with pytest.raises(DomainError) as excinfo:
            _service().force_unlock(session, ctx, 999999)
        assert excinfo.value.http_status == 404
        assert excinfo.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- cancel/force: status 독립(trashed+locked) --------------------------


def test_cancel_edit_does_not_touch_status(sessionmaker_factory):
    """trashed+locked 문서 보유자 취소 → 잠금 해제, status 는 여전히 trashed, 버전 미생성 (§4.3·6.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="cancel-statindep")
        ws = _make_workspace(seed, name="ws-cancel-status")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            status="trashed",
            lock_user_id=user.id,
            lock_acquired_at=datetime(2026, 7, 16, 9, 0, 0),
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=user_id, is_admin=False)
        _service().cancel_edit(session, ctx, doc_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.status == "trashed", "status 는 cancel 로 변경되지 않아야 한다"
        assert reloaded.lock_user_id is None, "status 와 무관하게 잠금 해제됨"
        assert _count_versions(verify, doc_id) == 0
    finally:
        verify.close()


def test_force_unlock_does_not_touch_status(sessionmaker_factory):
    """trashed+locked 문서 강제 해제 → 잠금 해제, status 는 여전히 trashed, 버전 미생성 (§4.3·6.1)."""
    seed = sessionmaker_factory()
    try:
        holder = _make_user(seed, login_id="force-statindep")
        actor = _make_user(seed, login_id="force-status-actor")
        ws = _make_workspace(seed, name="ws-force-status")
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=holder.id,
            status="trashed",
            lock_user_id=holder.id,
            lock_acquired_at=datetime(2026, 7, 16, 9, 0, 0),
        )
        seed.commit()
        doc_id, actor_id = doc.id, actor.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        ctx = AuthContext(user_id=actor_id, is_admin=False)
        _service().force_unlock(session, ctx, doc_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.status == "trashed", "status 는 force_unlock 로 변경되지 않아야 한다"
        assert reloaded.lock_user_id is None, "status 와 무관하게 잠금 해제됨"
        assert _count_versions(verify, doc_id) == 0
    finally:
        verify.close()
