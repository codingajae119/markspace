"""MembershipRepository 통합 테스트 (Task 2.2 / Req 3.1, 3.2, 3.6, 3.8, 4.2, 4.7, 5.2, 5.3).

design.md §Components and Interfaces #MembershipRepository 계약을 검증한다:
- `add` 는 (workspace, user, role) 멤버 행을 생성하고 fresh 세션 재조회로 영속화를 증명한다.
- 중복 (workspace_id, user_id) 삽입은 s01 UNIQUE 제약(uq_workspace_member_ws_user) 위반으로
  IntegrityError 를 발생시킨다(리포지토리는 삼키지 않는다; 서비스가 409 로 변환).
- `get`/`get_role` 은 멤버 행/role 문자열을 반환하고 비멤버는 None 을 반환한다.
- `set_role` 은 role 을 갱신한다(fresh 세션 증명).
- `remove` 는 멤버 행을 물리 제거한다(INV-4 비대상).
- `remove_all_for_workspace` 는 해당 워크스페이스의 모든 멤버 행을 제거한다.
- `user_exists` 는 존재 사용자(is_deleted 포함)는 True, 미존재 id 는 False 를 반환한다.

격리: tests/workspace/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한
뒤 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.models import User, Workspace, WorkspaceMember
from app.workspace.repository import MembershipRepository

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


def _make_user(session, *, login_id, is_deleted=False):
    """테스트 DB 에 User 를 삽입하고 flush 하여 id 를 확정한다(멤버십 FK 충족용)."""
    user = User(
        login_id=login_id,
        password_hash="hash-initial",
        name="테스트 사용자",
        email=None,
        is_admin=False,
        is_active=True,
        is_deleted=is_deleted,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def _make_workspace(session, *, name="ws"):
    """테스트 DB 에 Workspace 를 삽입하고 flush 하여 id 를 확정한다(멤버십 FK 충족용)."""
    workspace = Workspace(
        name=name,
        is_shareable=False,
        trash_retention_days=30,
        created_at=datetime.utcnow(),
    )
    session.add(workspace)
    session.flush()
    return workspace


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


# --- add / get / get_role ------------------------------------------------


def test_add_creates_member_and_persists(sessionmaker_factory):
    """add 는 멤버 행을 생성하고 fresh 세션 재조회로 영속화를 증명한다 (Req 3.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="member")
        ws = _make_workspace(seed, name="ws-add")
        seed.commit()
        ws_id, user_id = ws.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        member = repo.add(session, workspace_id=ws_id, user_id=user_id, role="owner")
        assert member.id is not None
        assert member.workspace_id == ws_id
        assert member.user_id == user_id
        assert member.role == "owner"
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        found = repo.get(verify, ws_id, user_id)
        assert found is not None, "생성된 멤버 행이 영속되어야 한다"
        assert found.role == "owner"
        assert repo.get_role(verify, ws_id, user_id) == "owner"
    finally:
        verify.close()


def test_get_and_get_role_return_none_for_non_member(sessionmaker_factory):
    """get/get_role 은 비멤버(workspace, user)에 대해 None 을 반환한다 (Req 4.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="stranger")
        ws = _make_workspace(seed, name="ws-empty")
        seed.commit()
        ws_id, user_id = ws.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        assert repo.get(session, ws_id, user_id) is None
        assert repo.get_role(session, ws_id, user_id) is None
    finally:
        session.close()


def test_get_role_returns_registered_role_string(sessionmaker_factory):
    """get_role 은 등록된 role 문자열(원시값)을 반환한다 (Req 4.2, resolver 데이터 소스)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="editor-user")
        ws = _make_workspace(seed, name="ws-role")
        seed.commit()
        ws_id, user_id = ws.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        repo.add(session, workspace_id=ws_id, user_id=user_id, role="editor")
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        role = repo.get_role(verify, ws_id, user_id)
        assert role == "editor"
        assert isinstance(role, str), "get_role 은 원시 문자열을 반환해야 한다"
    finally:
        verify.close()


# --- uniqueness ----------------------------------------------------------


def test_duplicate_member_insert_raises_integrity_error(sessionmaker_factory):
    """중복 (workspace_id, user_id) 삽입은 UNIQUE 제약 위반으로 IntegrityError 를 낸다 (Req 3.8)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="dup")
        ws = _make_workspace(seed, name="ws-dup")
        seed.commit()
        ws_id, user_id = ws.id, user.id
    finally:
        seed.close()

    first = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        repo.add(first, workspace_id=ws_id, user_id=user_id, role="owner")
    finally:
        first.close()

    # 실패한 삽입은 세션을 오염시키므로 fresh 세션에서 중복을 시도한다.
    dup = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        with pytest.raises(IntegrityError):
            repo.add(dup, workspace_id=ws_id, user_id=user_id, role="viewer")
    finally:
        dup.close()


# --- set_role ------------------------------------------------------------


def test_set_role_updates_role(sessionmaker_factory):
    """set_role 은 멤버 role 을 갱신하고 fresh 세션 재조회로 증명한다 (Req 5.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="promote")
        ws = _make_workspace(seed, name="ws-set")
        seed.commit()
        ws_id, user_id = ws.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        member = repo.add(session, workspace_id=ws_id, user_id=user_id, role="viewer")
        updated = repo.set_role(session, member, "owner")
        assert updated.role == "owner"
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        assert repo.get_role(verify, ws_id, user_id) == "owner"
    finally:
        verify.close()


# --- remove --------------------------------------------------------------


def test_remove_physically_removes_member(sessionmaker_factory):
    """remove 는 멤버 행을 물리적으로 제거한다 (INV-4 비대상, Req 5.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="leaver")
        ws = _make_workspace(seed, name="ws-remove")
        seed.commit()
        ws_id, user_id = ws.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        member = repo.add(session, workspace_id=ws_id, user_id=user_id, role="editor")
        repo.remove(session, member)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        assert repo.get(verify, ws_id, user_id) is None, "삭제 후 멤버 행이 물리 제거되어야 한다"
    finally:
        verify.close()


# --- remove_all_for_workspace --------------------------------------------


def test_remove_all_for_workspace_removes_all_members(sessionmaker_factory):
    """remove_all_for_workspace 는 해당 워크스페이스의 모든 멤버 행을 제거한다 (Req 3.6)."""
    seed = sessionmaker_factory()
    try:
        ws = _make_workspace(seed, name="ws-bulk")
        other_ws = _make_workspace(seed, name="ws-other")
        u1 = _make_user(seed, login_id="bulk-1")
        u2 = _make_user(seed, login_id="bulk-2")
        u3 = _make_user(seed, login_id="bulk-3")
        seed.commit()
        ws_id, other_ws_id = ws.id, other_ws.id
        u1_id, u2_id, u3_id = u1.id, u2.id, u3.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        repo.add(session, workspace_id=ws_id, user_id=u1_id, role="owner")
        repo.add(session, workspace_id=ws_id, user_id=u2_id, role="editor")
        # 다른 워크스페이스의 멤버는 보존되어야 한다.
        repo.add(session, workspace_id=other_ws_id, user_id=u3_id, role="owner")
        repo.remove_all_for_workspace(session, ws_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        assert repo.get(verify, ws_id, u1_id) is None
        assert repo.get(verify, ws_id, u2_id) is None
        assert (
            repo.get(verify, other_ws_id, u3_id) is not None
        ), "다른 워크스페이스의 멤버는 보존되어야 한다"
    finally:
        verify.close()


# --- user_exists ---------------------------------------------------------


def test_user_exists_true_for_existing_user(sessionmaker_factory):
    """user_exists 는 존재하는 사용자에 대해 True 를 반환한다 (Req 3.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="exists")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        assert repo.user_exists(session, user_id) is True
    finally:
        session.close()


def test_user_exists_true_for_deleted_user(sessionmaker_factory):
    """user_exists 는 is_deleted=True 사용자도 존재로 간주해 True 를 반환한다 (Req 3.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="soft-deleted", is_deleted=True)
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        assert (
            repo.user_exists(session, user_id) is True
        ), "is_deleted 사용자도 존재로 간주되어야 한다"
    finally:
        session.close()


def test_user_exists_false_for_nonexistent_user(sessionmaker_factory):
    """user_exists 는 존재하지 않는 id 에 대해 False 를 반환한다 (Req 3.2)."""
    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        assert repo.user_exists(session, 999999) is False
    finally:
        session.close()


# --- list_assignable_users (anti-join 배정 가능 조회, Req 1.1, 1.5) -------


def _make_assignable_user(
    session,
    *,
    login_id,
    name="배정 대상",
    email=None,
    is_admin=False,
    is_active=True,
    is_deleted=False,
):
    """상태 플래그를 세밀히 지정해 User 를 삽입·flush 한다(배정 가능 필터 검증용)."""
    user = User(
        login_id=login_id,
        password_hash="hash-initial",
        name=name,
        email=email,
        is_admin=is_admin,
        is_active=is_active,
        is_deleted=is_deleted,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def test_list_assignable_users_filters_and_returns_only_assignable(
    sessionmaker_factory,
):
    """list_assignable_users 는 admin·비활성·삭제·기존멤버를 제외하고 배정 가능만 반환한다 (Req 1.1).

    admin·inactive·deleted·이 워크스페이스의 기존 멤버는 각각 제외되고, 평범한 배정 가능
    사용자만 items 로 반환되며 total 이 그 수와 일치한다.
    """
    seed = sessionmaker_factory()
    try:
        ws = _make_workspace(seed, name="ws-assignable")
        assignable = _make_assignable_user(seed, login_id="plain", name="배정가능")
        admin = _make_assignable_user(seed, login_id="an-admin", is_admin=True)
        inactive = _make_assignable_user(
            seed, login_id="inactive", is_active=False
        )
        deleted = _make_assignable_user(seed, login_id="deleted", is_deleted=True)
        member = _make_assignable_user(seed, login_id="already-member")
        seed.flush()
        seed.add(
            WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="editor")
        )
        seed.commit()
        ws_id = ws.id
        assignable_id = assignable.id
        excluded_ids = {admin.id, inactive.id, deleted.id, member.id}
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        items, total = repo.list_assignable_users(
            session, ws_id, limit=50, offset=0
        )
        returned_ids = {u.id for u in items}
        assert assignable_id in returned_ids, "평범한 배정 가능 사용자는 반환되어야 한다"
        assert returned_ids.isdisjoint(
            excluded_ids
        ), "admin·비활성·삭제·기존멤버는 제외되어야 한다"
        assert returned_ids == {assignable_id}
        assert total == 1, "total 은 필터된 배정 가능 수와 일치해야 한다"
    finally:
        session.close()


def test_list_assignable_users_includes_member_of_other_workspace(
    sessionmaker_factory,
):
    """다른 워크스페이스의 멤버는 여전히 배정 가능으로 반환된다 (Req 1.1, 상관 NOT EXISTS 정확성).

    상관 조건이 (workspace_id AND user_id) 로 좁혀지지 않으면 임의 워크스페이스의 멤버가
    잘못 제외되는 고전적 anti-join 버그를 잡는다.
    """
    seed = sessionmaker_factory()
    try:
        target_ws = _make_workspace(seed, name="ws-target")
        other_ws = _make_workspace(seed, name="ws-other")
        user = _make_assignable_user(seed, login_id="member-elsewhere")
        seed.flush()
        # user 는 other_ws 의 멤버지만 target_ws 에는 아니다 → target 기준 배정 가능.
        seed.add(
            WorkspaceMember(
                workspace_id=other_ws.id, user_id=user.id, role="owner"
            )
        )
        seed.commit()
        target_id, user_id = target_ws.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        items, total = repo.list_assignable_users(
            session, target_id, limit=50, offset=0
        )
        returned_ids = {u.id for u in items}
        assert user_id in returned_ids, (
            "다른 워크스페이스의 멤버는 대상 워크스페이스 기준 배정 가능이어야 한다"
        )
        assert total == 1
    finally:
        session.close()


def test_list_assignable_users_total_is_filtered_count_not_page_size(
    sessionmaker_factory,
):
    """total 은 페이지 크기가 아니라 전체 배정 가능 수와 일치한다 (Req 1.5, 무필터 count 금지).

    limit 보다 많은 배정 가능 사용자를 시드하고, total 은 전체 배정 가능 수인 반면
    len(items) 는 limit 인지 확인한다.
    """
    seed = sessionmaker_factory()
    try:
        ws = _make_workspace(seed, name="ws-paged")
        for i in range(5):
            _make_assignable_user(seed, login_id=f"assignable-{i}")
        # 필터로 제외되어 total 을 부풀리면 안 되는 노이즈 계정.
        _make_assignable_user(seed, login_id="noise-admin", is_admin=True)
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        items, total = repo.list_assignable_users(
            session, ws_id, limit=2, offset=0
        )
        assert total == 5, "total 은 페이지 크기가 아닌 전체 배정 가능 수(5)여야 한다"
        assert len(items) == 2, "items 는 limit 만큼만 반환해야 한다"
    finally:
        session.close()


def test_list_assignable_users_orders_ascending_by_id(sessionmaker_factory):
    """items 는 user.id 오름차순의 결정적 순서로 반환된다 (Req 1.5)."""
    seed = sessionmaker_factory()
    try:
        ws = _make_workspace(seed, name="ws-order")
        for i in range(4):
            _make_assignable_user(seed, login_id=f"ordered-{i}")
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = MembershipRepository()
        items, _ = repo.list_assignable_users(session, ws_id, limit=50, offset=0)
        returned_ids = [u.id for u in items]
        assert returned_ids == sorted(returned_ids), "items 는 user.id 오름차순이어야 한다"
        assert len(returned_ids) == 4
    finally:
        session.close()
