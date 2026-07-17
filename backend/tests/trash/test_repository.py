"""TrashRepository 통합 테스트 (Task 1.2 / Req 1.4, 4.3).

design.md §Components and Interfaces #TrashRepository (Feature/Data) 계약을 실제 DB 로
검증한다:
- `get_retention_days` 는 워크스페이스의 `trash_retention_days`(s05 설정값)를 반환한다
  (만료 산정 근거, Req 1.4).
- `list_workspace_ids_with_trashed` 는 trashed 문서를 1개 이상 보유한 워크스페이스 id
  만을 DISTINCT 로 열거하고(스윕 스코프 축소, Req 4.3), 없으면 빈 목록을 반환한다.
  상태 전이·묶음 식별은 하지 않는다(엔진 위임, §4.3 무변경).

격리: tests/lock_version/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한
뒤 환경변수·캐시를 원복한다. 공유 테스트 DB 충돌을 피하려 이름/제목에 uuid4 접미사를 쓴다.
"""

import os
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.models import Document, User, Workspace
from app.trash.repository import TrashRepository

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


def _make_workspace(session, *, name="ws", trash_retention_days=30):
    """Workspace 행을 삽입하고 flush 한다(retention 조회·document FK 충족용)."""
    ws = Workspace(
        name=name,
        is_shareable=False,
        trash_retention_days=trash_retention_days,
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
    trashed_at=None,
):
    """Document 행을 직접 삽입하고 flush 한다(스윕 스코프 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        trashed_at=trashed_at,
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


# --- get_retention_days --------------------------------------------------


def test_get_retention_days_returns_configured_value(sessionmaker_factory):
    """get_retention_days 는 워크스페이스에 설정된 trash_retention_days 를 반환한다(Req 1.4)."""
    seed = sessionmaker_factory()
    try:
        ws7 = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=7
        )
        ws_default = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=30
        )
        seed.commit()
        ws7_id, ws_default_id = ws7.id, ws_default.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = TrashRepository()
        assert repo.get_retention_days(session, ws7_id) == 7
        assert repo.get_retention_days(session, ws_default_id) == 30
    finally:
        session.close()


# --- list_workspace_ids_with_trashed -------------------------------------


def test_list_workspace_ids_with_trashed_scopes_to_trashed_holders(
    sessionmaker_factory,
):
    """list_workspace_ids_with_trashed 는 trashed 문서 보유 WS 만 열거한다(Req 4.3).

    WS-A 는 trashed 문서를, WS-B 는 active 문서만 보유 → 결과는 A 를 포함하고 B 를 제외한다.
    """
    trashed_at = datetime(2026, 7, 17, 9, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws_a = _make_workspace(seed, name=f"wsA-{uuid4().hex}")
        ws_b = _make_workspace(seed, name=f"wsB-{uuid4().hex}")
        _make_document(
            seed,
            workspace_id=ws_a.id,
            created_by=user.id,
            title=f"trashed-{uuid4().hex}",
            status="trashed",
            trashed_at=trashed_at,
        )
        _make_document(
            seed,
            workspace_id=ws_b.id,
            created_by=user.id,
            title=f"active-{uuid4().hex}",
            status="active",
        )
        seed.commit()
        ws_a_id, ws_b_id = ws_a.id, ws_b.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = TrashRepository()
        result = repo.list_workspace_ids_with_trashed(session)
        assert ws_a_id in result, "trashed 문서 보유 WS 는 스윕 스코프에 포함되어야 한다"
        assert ws_b_id not in result, "active 문서만 있는 WS 는 제외되어야 한다"
    finally:
        session.close()


def test_list_workspace_ids_with_trashed_empty_when_no_trashed(
    sessionmaker_factory,
):
    """trashed 문서가 어디에도 없으면 빈 목록을 반환한다(Req 4.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            title=f"active-{uuid4().hex}",
            status="active",
        )
        # deleted 종착 문서는 trashed 가 아니므로 스코프에 잡히지 않아야 한다.
        _make_document(
            seed,
            workspace_id=ws.id,
            created_by=user.id,
            title=f"deleted-{uuid4().hex}",
            status="deleted",
        )
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = TrashRepository()
        assert repo.list_workspace_ids_with_trashed(session) == []
    finally:
        session.close()


def test_list_workspace_ids_with_trashed_is_distinct(sessionmaker_factory):
    """여러 trashed 문서를 보유한 WS 는 결과에 정확히 한 번만 나타난다(DISTINCT, Req 4.3)."""
    base = datetime(2026, 7, 17, 10, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        for i in range(3):
            _make_document(
                seed,
                workspace_id=ws.id,
                created_by=user.id,
                title=f"trashed-{i}-{uuid4().hex}",
                status="trashed",
                trashed_at=base,
                sort_order=Decimal(1000 + i),
            )
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = TrashRepository()
        result = repo.list_workspace_ids_with_trashed(session)
        assert result.count(ws_id) == 1, "다중 trashed 문서 WS 는 정확히 한 번만 열거되어야 한다"
    finally:
        session.close()
