"""WorkspaceRepository 통합 테스트 (Task 2.1 / Req 1.3, 1.4, 2.1, 2.5).

design.md §Components and Interfaces #WorkspaceRepository 계약을 검증한다:
- `create` 는 `is_shareable=False`·주어진 `trash_retention_days` 로 워크스페이스 행을
  생성하고 `created_at` 을 설정하며 fresh 세션 재조회로 영속화를 증명한다(Req 2.1).
- `list_for_user` 는 요청자가 멤버인 워크스페이스만 반환하고(다른 사용자의 워크스페이스
  제외) total 은 멤버 스코프 개수다. limit/offset 은 items 에만 적용한다(Req 1.3).
- `list_all` 은 전체 워크스페이스를 반환하고 total 은 전체 개수다(admin, Req 1.4).
- `apply_updates` 는 제공된 키(name/is_shareable/trash_retention_days)만 부분 갱신하고
  `updated_at` 을 설정한다(Req 2.1·2.2·2.3).
- `delete` 는 워크스페이스 행을 물리적으로 제거한다(INV-4 비대상, Req 2.5).

격리: tests/admin_account/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한
뒤 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.models import User, Workspace, WorkspaceMember
from app.workspace.repository import WorkspaceRepository

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
    """테스트 DB 에 User 를 삽입하고 flush 하여 id 를 확정한다(멤버십 FK 충족용)."""
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


def _make_member(session, *, workspace_id, user_id, role="owner"):
    """(workspace, user) 멤버십 행을 삽입하고 flush 한다."""
    member = WorkspaceMember(
        workspace_id=workspace_id, user_id=user_id, role=role
    )
    session.add(member)
    session.flush()
    return member


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


# --- create --------------------------------------------------------------


def test_create_sets_is_shareable_false_and_persists(sessionmaker_factory):
    """create 는 is_shareable=False·주어진 retention 으로 생성하고 영속화한다 (Req 2.1)."""
    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        created = repo.create(session, name="내 워크스페이스", trash_retention_days=45)
        assert created.is_shareable is False, "생성 기본값은 is_shareable=False 여야 한다"
        assert created.trash_retention_days == 45
        assert created.name == "내 워크스페이스"
        assert created.created_at is not None, "created_at 은 명시적으로 설정되어야 한다"
        ws_id = created.id
        assert ws_id is not None
    finally:
        session.close()

    # fresh 세션 재조회로 commit 영속화를 증명한다.
    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Workspace, ws_id)
        assert reloaded is not None, "생성된 워크스페이스 행이 영속되어야 한다"
        assert reloaded.is_shareable is False
        assert reloaded.trash_retention_days == 45
        assert reloaded.name == "내 워크스페이스"
    finally:
        verify.close()


# --- get_by_id -----------------------------------------------------------


def test_get_by_id_returns_workspace_or_none(sessionmaker_factory):
    """get_by_id 는 존재 시 행을, 미존재 시 None 을 반환한다."""
    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        created = repo.create(session, name="ws", trash_retention_days=30)
        ws_id = created.id

        found = repo.get_by_id(session, ws_id)
        assert found is not None
        assert found.id == ws_id
        assert repo.get_by_id(session, 999999) is None
    finally:
        session.close()


# --- list_for_user -------------------------------------------------------


def test_list_for_user_returns_only_member_workspaces(sessionmaker_factory):
    """list_for_user 는 요청자가 멤버인 워크스페이스를 (Workspace, role) 로만 반환한다 (Req 1.3, 1.1)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        # 요청자 user 와 다른 user.
        me = _make_user(seed, login_id="me")
        other = _make_user(seed, login_id="other")

        ws_mine_a = repo.create(seed, name="mine-a", trash_retention_days=30)
        ws_mine_b = repo.create(seed, name="mine-b", trash_retention_days=30)
        ws_other = repo.create(seed, name="other-ws", trash_retention_days=30)

        _make_member(seed, workspace_id=ws_mine_a.id, user_id=me.id)
        _make_member(seed, workspace_id=ws_mine_b.id, user_id=me.id)
        _make_member(seed, workspace_id=ws_other.id, user_id=other.id)
        seed.commit()

        me_id = me.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        items, total = repo.list_for_user(session, me_id, limit=100, offset=0)
        names = {ws.name for ws, _role in items}
        assert total == 2, "total 은 요청자가 멤버인 워크스페이스 개수여야 한다"
        assert names == {"mine-a", "mine-b"}
        assert "other-ws" not in names, "다른 사용자의 워크스페이스는 제외되어야 한다"
    finally:
        session.close()


def test_list_for_user_returns_actual_membership_role(sessionmaker_factory):
    """list_for_user 의 각 항목은 호출자의 실제 멤버십 role 을 함께 반환한다 (Req 1.1)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        me = _make_user(seed, login_id="me-roles")

        ws_owner = repo.create(seed, name="ws-owner", trash_retention_days=30)
        ws_editor = repo.create(seed, name="ws-editor", trash_retention_days=30)
        ws_viewer = repo.create(seed, name="ws-viewer", trash_retention_days=30)

        _make_member(seed, workspace_id=ws_owner.id, user_id=me.id, role="owner")
        _make_member(seed, workspace_id=ws_editor.id, user_id=me.id, role="editor")
        _make_member(seed, workspace_id=ws_viewer.id, user_id=me.id, role="viewer")
        seed.commit()

        me_id = me.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        items, total = repo.list_for_user(session, me_id, limit=100, offset=0)
        assert total == 3
        role_by_name = {ws.name: role for ws, role in items}
        assert role_by_name == {
            "ws-owner": "owner",
            "ws-editor": "editor",
            "ws-viewer": "viewer",
        }, "각 항목은 호출자의 실제 멤버십 role 을 반환해야 한다"
    finally:
        session.close()


def test_list_for_user_applies_limit_and_offset(sessionmaker_factory):
    """limit/offset 은 items 에만 적용되고 total 은 멤버 스코프 전체를 반영한다 (Req 1.3)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        me = _make_user(seed, login_id="pager")
        for i in range(5):
            ws = repo.create(seed, name=f"page-{i}", trash_retention_days=30)
            _make_member(seed, workspace_id=ws.id, user_id=me.id)
        seed.commit()
        me_id = me.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        items, total = repo.list_for_user(session, me_id, limit=2, offset=0)
        assert total == 5
        assert len(items) == 2
        # items 는 (Workspace, role) 튜플이며 정렬은 Workspace.id 오름차순으로 유지한다.
        ids = [ws.id for ws, _role in items]
        assert ids == sorted(ids)

        items2, total2 = repo.list_for_user(session, me_id, limit=2, offset=4)
        assert total2 == 5
        assert len(items2) == 1  # 마지막 페이지 잔여 1건
    finally:
        session.close()


# --- list_all ------------------------------------------------------------


def test_list_all_returns_all_workspaces(sessionmaker_factory):
    """list_all 은 멤버 여부와 무관하게 전체 워크스페이스를 (Workspace, role|None) 로 반환한다 (Req 1.4)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        admin = _make_user(seed, login_id="admin-caller")
        for i in range(3):
            repo.create(seed, name=f"all-{i}", trash_retention_days=30)
        seed.commit()
        admin_id = admin.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        items, total = repo.list_all(session, admin_id, limit=100, offset=0)
        assert total == 3, "total 은 전체 워크스페이스 개수여야 한다"
        assert {ws.name for ws, _role in items} == {"all-0", "all-1", "all-2"}
    finally:
        session.close()


def test_list_all_returns_role_for_member_and_none_for_non_member(sessionmaker_factory):
    """list_all 은 호출자 멤버 WS 는 실제 role, 비멤버 WS 는 None 을 반환하고 admin 상승이 없다 (Req 1.2, 1.3)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        # 호출자는 admin 이지만 한 WS 에서만 viewer 멤버다.
        caller = _make_user(seed, login_id="admin-viewer")
        other = _make_user(seed, login_id="other-owner")

        ws_member = repo.create(seed, name="ws-member", trash_retention_days=30)
        ws_non_member = repo.create(seed, name="ws-nonmember", trash_retention_days=30)

        # 호출자는 ws_member 에서 viewer 이며, ws_non_member 에는 멤버십이 없다.
        _make_member(seed, workspace_id=ws_member.id, user_id=caller.id, role="viewer")
        # 다른 사용자가 ws_non_member 의 owner (호출자 role 로 새어들면 안 됨).
        _make_member(seed, workspace_id=ws_non_member.id, user_id=other.id, role="owner")
        seed.commit()

        caller_id = caller.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        items, total = repo.list_all(session, caller_id, limit=100, offset=0)
        assert total == 2, "total 은 전체 워크스페이스 개수여야 한다(멤버 여부 무관)"
        role_by_name = {ws.name: role for ws, role in items}
        assert role_by_name["ws-member"] == "viewer", (
            "호출자가 멤버인 WS 는 실제 멤버십 role 을 반환해야 한다(admin 상승 없음)"
        )
        assert role_by_name["ws-nonmember"] is None, (
            "호출자가 비멤버인 WS 는 None 이어야 한다(다른 멤버의 role 이 새면 안 됨)"
        )
    finally:
        session.close()


def test_list_all_applies_limit_and_offset(sessionmaker_factory):
    """list_all 의 limit/offset 은 items 에만 적용되고 total 은 전체다 (Req 1.4)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        caller = _make_user(seed, login_id="pager-admin")
        for i in range(5):
            repo.create(seed, name=f"a-{i}", trash_retention_days=30)
        seed.commit()
        caller_id = caller.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        items, total = repo.list_all(session, caller_id, limit=2, offset=0)
        assert total == 5
        assert len(items) == 2
        # items 는 (Workspace, role|None) 튜플이며 정렬은 Workspace.id 오름차순이다.
        ids = [ws.id for ws, _role in items]
        assert ids == sorted(ids)
    finally:
        session.close()


# --- apply_updates -------------------------------------------------------


def test_apply_updates_partial_flips_provided_keys(sessionmaker_factory):
    """apply_updates 는 제공된 키(name/is_shareable/retention)만 갱신하고 updated_at 설정 (Req 2.1)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        ws = repo.create(seed, name="원래이름", trash_retention_days=30)
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        ws = repo.get_by_id(session, ws_id)
        repo.apply_updates(
            session,
            ws,
            {"name": "바뀐이름", "is_shareable": True, "trash_retention_days": 7},
        )
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Workspace, ws_id)
        assert reloaded.name == "바뀐이름"
        assert reloaded.is_shareable is True
        assert reloaded.trash_retention_days == 7
        assert reloaded.updated_at is not None, "updated_at 이 설정되어야 한다"
    finally:
        verify.close()


def test_apply_updates_only_changes_provided_keys(sessionmaker_factory):
    """제공되지 않은 키는 보존되고 화이트리스트 밖 키는 무시된다 (Req 2.1)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        ws = repo.create(seed, name="보존이름", trash_retention_days=30)
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        ws = repo.get_by_id(session, ws_id)
        # is_shareable 만 전환. name·retention 은 보존. 화이트리스트 밖 키는 무시.
        repo.apply_updates(session, ws, {"is_shareable": True, "id": 12345})
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Workspace, ws_id)
        assert reloaded.id == ws_id, "화이트리스트 밖 키(id)는 무시되어야 한다"
        assert reloaded.is_shareable is True
        assert reloaded.name == "보존이름", "제공되지 않은 name 은 보존되어야 한다"
        assert reloaded.trash_retention_days == 30, "제공되지 않은 retention 은 보존되어야 한다"
    finally:
        verify.close()


# --- delete --------------------------------------------------------------


def test_delete_physically_removes_row(sessionmaker_factory):
    """delete 는 워크스페이스 행을 물리적으로 제거한다 (INV-4 비대상, Req 2.5)."""
    seed = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        ws = repo.create(seed, name="to-delete", trash_retention_days=30)
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = WorkspaceRepository()
        ws = repo.get_by_id(session, ws_id)
        repo.delete(session, ws)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Workspace, ws_id)
        assert reloaded is None, "삭제 후 워크스페이스 행이 물리적으로 제거되어야 한다"
    finally:
        verify.close()
