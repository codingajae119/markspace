"""LockVersionRepository 통합 테스트 (Task 1.2 / Req 1.1, 1.3, 1.4, 2.1, 2.2,
2.3, 3.1, 4.1, 5.1, 6.4).

design.md §Components and Interfaces #LockVersionRepository 계약을 실제 DB 로 검증한다:
- `get`/`get_for_update` 는 PK·행 잠금(FOR UPDATE)으로 문서 행을 로드한다.
- `acquire_lock` 은 미잠금 문서에 보유자·획득 시각을 기록하고, `clear_lock` 은 잠금
  필드를 NULL 로 되돌린다(INV-9 단일 lock_user_id 컬럼, §4.3 status 무검사·무변경).
- `insert_version` 은 새 `document_version` 행을 만들고 flush 로 `.id` 를 채우며(커밋은
  service 소유), `set_current_version` 은 `current_version_id` 를 갱신한다.
- `list_versions` 는 최신 저장 순((created_at, id) desc)으로 메타데이터를 반환하고
  total 을 제공하며, append-only(기존 버전 미삭제)를 증명한다(INV-4·REQ-5.2).

격리: tests/document/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한
뒤 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.lock_version.repository import LockVersionRepository
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
    parent_id=None,
    title="문서",
    status="active",
    sort_order=Decimal("1000"),
    current_version_id=None,
    lock_user_id=None,
    lock_acquired_at=None,
    trashed_at=None,
):
    """Document 행을 직접 삽입하고 flush 한다(잠금·버전 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        current_version_id=current_version_id,
        lock_user_id=lock_user_id,
        lock_acquired_at=lock_acquired_at,
        trashed_at=trashed_at,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


def _make_version(session, *, document_id, created_by, content, created_at=None):
    """DocumentVersion 행을 삽입하고 flush 하여 id 를 확정한다(목록·본문 시드용)."""
    version = DocumentVersion(
        document_id=document_id,
        content=content,
        created_by=created_by,
        created_at=created_at or datetime.utcnow(),
    )
    session.add(version)
    session.flush()
    return version


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


# --- get / get_for_update ------------------------------------------------


def test_get_returns_document_or_none(sessionmaker_factory):
    """get 은 존재 시 행을, 미존재 시 None 을 반환한다(PK 로드)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="g")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        found = repo.get(session, doc_id)
        assert found is not None
        assert found.id == doc_id
        assert repo.get(session, 999999) is None
    finally:
        session.close()


def test_get_for_update_loads_row_with_row_lock(sessionmaker_factory):
    """get_for_update 는 FOR UPDATE 행 잠금으로 대상 문서 행을 로드한다(경합 안전, Req 1.4).

    단일 커넥션 테스트에서 잠금 자체(블로킹)를 증명할 수는 없으므로, 최소한 올바른 행을
    로드하고 미존재 시 None 임을 검증한다. 동시성(FOR UPDATE)은 DB 레벨에서 강제된다.
    """
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="lock")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id, title="대상")
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        locked = repo.get_for_update(session, doc_id)
        assert locked is not None
        assert locked.id == doc_id
        assert locked.title == "대상"
        assert repo.get_for_update(session, 999999) is None
        session.rollback()  # 행 잠금 해제.
    finally:
        session.close()


# --- acquire_lock / clear_lock -------------------------------------------


def test_acquire_lock_records_holder_and_time(sessionmaker_factory):
    """acquire_lock 은 미잠금 문서에 lock_user_id·lock_acquired_at 을 기록한다(Req 1.1).

    커밋은 service 소유이므로 리포지토리는 ORM 객체만 변이한다. 여기서는 테스트가 명시적으로
    commit 해 fresh 세션 재조회로 영속화를 증명한다. status 는 검사·변경하지 않는다(§4.3).
    """
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="acq")
        ws = _make_workspace(seed)
        doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, status="active"
        )
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    at = datetime(2026, 7, 17, 9, 30, 0)
    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        doc = repo.get(session, doc_id)
        returned = repo.acquire_lock(session, doc, user_id=user_id, at=at)
        assert returned.lock_user_id == user_id
        assert returned.lock_acquired_at == at
        session.commit()
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id == user_id
        assert reloaded.lock_acquired_at == at
        assert reloaded.status == "active", "status 는 잠금과 독립이라 유지되어야 한다"
    finally:
        verify.close()


def test_clear_lock_returns_fields_to_null(sessionmaker_factory):
    """clear_lock 은 잠긴 문서의 lock 필드를 NULL 로 되돌린다(Req 2.3·3.1·4.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="clr")
        ws = _make_workspace(seed)
        doc = _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            lock_user_id=user.id,
            lock_acquired_at=datetime(2026, 7, 17, 8, 0, 0),
        )
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        doc = repo.get(session, doc_id)
        assert doc.lock_user_id is not None  # 사전 조건: 잠겨 있음.
        returned = repo.clear_lock(session, doc)
        assert returned.lock_user_id is None
        assert returned.lock_acquired_at is None
        session.commit()
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.lock_user_id is None
        assert reloaded.lock_acquired_at is None
    finally:
        verify.close()


# --- insert_version / set_current_version --------------------------------


def test_insert_version_creates_row_and_populates_id_after_flush(sessionmaker_factory):
    """insert_version 은 새 버전 행을 만들고 flush 로 .id 를 채운다(커밋은 service, Req 2.1).

    리포지토리는 flush 만 하고 커밋하지 않는다(원자 저장 트랜잭션은 service 소유). 여기서는
    테스트가 커밋해 영속화를 확인한다.
    """
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="ins")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id, user_id = doc.id, user.id
    finally:
        seed.close()

    at = datetime(2026, 7, 17, 10, 0, 0)
    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        version = repo.insert_version(
            session,
            document_id=doc_id,
            content="# 저장 스냅샷\n본문",
            created_by=user_id,
            at=at,
        )
        assert version.id is not None, "flush 후 .id 가 채워져야 한다"
        assert version.document_id == doc_id
        assert version.created_by == user_id
        assert version.created_at == at
        version_id = version.id
        session.commit()
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(DocumentVersion, version_id)
        assert reloaded is not None, "버전 행이 영속화되어야 한다"
        assert reloaded.content == "# 저장 스냅샷\n본문"
    finally:
        verify.close()


def test_set_current_version_updates_pointer(sessionmaker_factory):
    """set_current_version 은 문서의 current_version_id 를 갱신한다(Req 2.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="cur")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        version = _make_version(
            seed, document_id=doc.id, created_by=user.id, content="본문"
        )
        seed.commit()
        doc_id, version_id = doc.id, version.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        doc = repo.get(session, doc_id)
        assert doc.current_version_id is None  # 사전 조건.
        returned = repo.set_current_version(session, doc, version_id)
        assert returned.current_version_id == version_id
        session.commit()
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.current_version_id == version_id
    finally:
        verify.close()


# --- list_versions (최신 저장 순 + total + append-only) -------------------


def test_list_versions_returns_latest_first_with_total(sessionmaker_factory):
    """list_versions 는 최신 저장 순 items 와 전체 total 을 반환한다(Req 5.1·5.4).

    seed ≥2 버전으로 순서를 검증하고, 기존 버전이 삭제되지 않았음(append-only, INV-4·5.2)을
    두 행이 모두 남아 있는 것으로 확인한다.
    """
    base = datetime(2026, 7, 17, 11, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="listv")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        other_doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="다른 문서"
        )
        v1 = _make_version(
            seed, document_id=doc.id, created_by=user.id, content="v1",
            created_at=base,
        )
        v2 = _make_version(
            seed, document_id=doc.id, created_by=user.id, content="v2",
            created_at=base + timedelta(minutes=5),
        )
        v3 = _make_version(
            seed, document_id=doc.id, created_by=user.id, content="v3",
            created_at=base + timedelta(minutes=10),
        )
        # 다른 문서의 버전은 이 문서 목록/total 에서 제외되어야 한다.
        _make_version(
            seed, document_id=other_doc.id, created_by=user.id, content="other",
            created_at=base,
        )
        seed.commit()
        doc_id = doc.id
        v1_id, v2_id, v3_id = v1.id, v2.id, v3.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        items, total = repo.list_versions(session, doc_id, limit=10, offset=0)
        assert total == 3, "total 은 해당 문서 전체 버전 수여야 한다(다른 문서 제외)"
        assert [v.id for v in items] == [v3_id, v2_id, v1_id], (
            "최신 저장 순(created_at desc, id desc)이어야 한다"
        )
        # append-only 증명: 세 버전 모두 여전히 존재.
        assert {v.id for v in items} == {v1_id, v2_id, v3_id}
    finally:
        session.close()


def test_list_versions_applies_limit_offset(sessionmaker_factory):
    """list_versions 는 limit/offset 을 items 에만 적용하고 total 은 전체를 유지한다(Req 5.1)."""
    base = datetime(2026, 7, 17, 12, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="page")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        for i in range(5):
            _make_version(
                seed, document_id=doc.id, created_by=user.id, content=f"v{i}",
                created_at=base + timedelta(minutes=i),
            )
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        items, total = repo.list_versions(session, doc_id, limit=2, offset=0)
        assert total == 5, "total 은 전체 개수여야 한다"
        assert len(items) == 2

        items2, total2 = repo.list_versions(session, doc_id, limit=2, offset=4)
        assert total2 == 5
        assert len(items2) == 1  # 마지막 페이지 잔여 1건.
    finally:
        session.close()


def test_list_versions_same_second_deterministic_by_id(sessionmaker_factory):
    """created_at 이 동일 초(second)여도 id desc 로 결정적 최신순을 보장한다.

    document_version.created_at 은 MySQL DATETIME(초 정밀도)이라 같은 초에 저장된 두 버전은
    created_at 만으로 순서가 비결정적이다. (created_at desc, id desc) 정렬로 안정 최신순을
    보장하는지 검증한다.
    """
    same_second = datetime(2026, 7, 17, 13, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="samesec")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        v1 = _make_version(
            seed, document_id=doc.id, created_by=user.id, content="a",
            created_at=same_second,
        )
        v2 = _make_version(
            seed, document_id=doc.id, created_by=user.id, content="b",
            created_at=same_second,
        )
        seed.commit()
        doc_id, v1_id, v2_id = doc.id, v1.id, v2.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = LockVersionRepository()
        items, total = repo.list_versions(session, doc_id, limit=10, offset=0)
        assert total == 2
        assert [v.id for v in items] == [v2_id, v1_id], (
            "동일 초라도 id desc 로 나중 저장분이 먼저여야 한다(결정적)"
        )
    finally:
        session.close()
