"""워크스페이스 단위 권한 resolver 단위 테스트 (Task 3.5 / Req 5.1~5.7, INV-1·2·3).

``WorkspaceRoleResolver`` 의 role 위계 판정과 admin bypass, 그리고 의존성
팩토리 ``require_ws_role`` / admin 게이트 ``require_admin`` 의 동작을 FastAPI DI 를
거치지 않고 평범한 함수/메서드 호출로 직접 검증한다(design.md §Common/Permissions
#PermissionResolver, System Flows "세션 인증 판정", Invariants INV-1·2·3).

격리: ``test_auth.py`` 와 동일하게 전용 테스트 DB(``markspace_test``)를 대상으로
``DB_NAME`` 을 바꾸고 ``get_settings`` 캐시를 비운 뒤 그 시점 URL 로 새 엔진을 만든다.
종료 시 테이블을 모두 제거하고 환경변수·캐시를 원복한다(캐시·DB 누수 방지).
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.auth import AuthContext
from app.common.db import Base
from app.common.errors import DomainError, ErrorCode
from app.common.permissions import (
    Role,
    WorkspaceRoleResolver,
    require_admin,
    require_ws_role,
)
from app.models import User, Workspace, WorkspaceMember

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


@pytest.fixture
def test_session():
    """테스트 DB 에 전체 스키마를 생성하고 세션을 제공한 뒤 정리한다."""
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    _drop_everything(engine)  # 시작 전 빈 상태 보증(격리 전제).
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionFactory()

    try:
        yield session
    finally:
        session.close()
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


def _make_user(session, *, is_admin=False):
    """테스트 세션에 User 를 한 명 삽입하고 flush 하여 id 를 확정한다."""
    suffix = f"{is_admin}-{datetime.utcnow().timestamp()}"
    user = User(
        login_id=f"user-{suffix}",
        password_hash="x",
        name="테스트 사용자",
        is_admin=is_admin,
        is_active=True,
        is_deleted=False,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def _make_workspace(session):
    """테스트 세션에 Workspace 를 하나 삽입하고 flush 하여 id 를 확정한다."""
    ws = Workspace(
        name="테스트 워크스페이스",
        is_shareable=False,
        trash_retention_days=30,
        created_at=datetime.utcnow(),
    )
    session.add(ws)
    session.flush()
    return ws


def _add_member(session, *, workspace_id, user_id, role):
    """(workspace, user) 에 role 을 부여하는 WorkspaceMember 를 삽입한다."""
    member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
    session.add(member)
    session.flush()
    return member


def _ctx(user, *, is_admin=None):
    return AuthContext(
        user_id=user.id,
        is_admin=user.is_admin if is_admin is None else is_admin,
    )


# --- resolve() -------------------------------------------------------------


def test_resolve_returns_role_for_member(test_session):
    """멤버는 부여된 role 로 매핑된다 (Req 5.2, 1.1)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    _add_member(test_session, workspace_id=ws.id, user_id=user.id, role="member")

    role = WorkspaceRoleResolver().resolve(test_session, _ctx(user), ws.id)

    assert role is Role.MEMBER


def test_resolve_returns_role_for_owner(test_session):
    """owner 멤버는 OWNER 로 매핑된다 (Req 5.2, 1.1)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    _add_member(test_session, workspace_id=ws.id, user_id=user.id, role="owner")

    role = WorkspaceRoleResolver().resolve(test_session, _ctx(user), ws.id)

    assert role is Role.OWNER


def test_resolve_returns_none_for_non_member(test_session):
    """멤버가 아니면 None (Req 5.3)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)

    role = WorkspaceRoleResolver().resolve(test_session, _ctx(user), ws.id)

    assert role is None


# --- Role 2단계 위계·심볼 (Req 1.1, 1.2) -----------------------------------


def test_role_is_two_tier_owner_over_member():
    """Role 은 owner/member 2값이며 owner > member 위계이다 (Req 1.1, 1.2)."""
    assert Role.OWNER > Role.MEMBER
    assert int(Role.MEMBER) == 1
    assert int(Role.OWNER) == 2
    assert {r.name for r in Role} == {"MEMBER", "OWNER"}


def test_role_has_no_editor_or_viewer_symbols():
    """삭제된 EDITOR/VIEWER 심볼은 존재하지 않는다 (하위 호환 alias 없음, Req 1.1)."""
    assert not hasattr(Role, "EDITOR")
    assert not hasattr(Role, "VIEWER")


def test_role_map_holds_only_two_values():
    """_ROLE_MAP 은 owner/member 두 문자열만 번역하고 legacy 값은 매핑에서 제외된다 (Req 1.1)."""
    from app.common.permissions import _ROLE_MAP

    assert _ROLE_MAP == {"owner": Role.OWNER, "member": Role.MEMBER}
    assert _ROLE_MAP.get("editor") is None
    assert _ROLE_MAP.get("viewer") is None


# --- has_at_least() 위계 (Req 1.2, 5.2, INV-2, INV-3) ----------------------


def test_member_meets_member_but_not_owner(test_session):
    """member 는 MEMBER 요구를 만족하고 OWNER 는 만족하지 못한다 (Req 1.2·5.2 위계)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    _add_member(test_session, workspace_id=ws.id, user_id=user.id, role="member")
    resolver = WorkspaceRoleResolver()
    ctx = _ctx(user)

    assert resolver.has_at_least(test_session, ctx, ws.id, Role.MEMBER) is True
    assert resolver.has_at_least(test_session, ctx, ws.id, Role.OWNER) is False


def test_owner_meets_all_levels(test_session):
    """owner 는 member 의 모든 권한을 포함한다 (Req 1.2·5.6 위계)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    _add_member(test_session, workspace_id=ws.id, user_id=user.id, role="owner")
    resolver = WorkspaceRoleResolver()
    ctx = _ctx(user)

    assert resolver.has_at_least(test_session, ctx, ws.id, Role.OWNER) is True
    assert resolver.has_at_least(test_session, ctx, ws.id, Role.MEMBER) is True


def test_non_member_denied_for_any_role(test_session):
    """멤버가 아니면 어떤 최소 role 도 만족하지 못한다 (Req 5.3)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    resolver = WorkspaceRoleResolver()
    ctx = _ctx(user)

    assert resolver.has_at_least(test_session, ctx, ws.id, Role.MEMBER) is False
    assert resolver.has_at_least(test_session, ctx, ws.id, Role.OWNER) is False


def test_admin_bypasses_membership(test_session):
    """admin 은 멤버가 아니어도 최상위 role 을 통과한다 (Req 5.5, INV-3)."""
    ws = _make_workspace(test_session)
    admin = _make_user(test_session, is_admin=True)
    resolver = WorkspaceRoleResolver()
    ctx = _ctx(admin)

    assert resolver.has_at_least(test_session, ctx, ws.id, Role.OWNER) is True


# --- require_ws_role() 의존성 팩토리 --------------------------------------


def test_require_ws_role_passes_for_sufficient_role(test_session):
    """member 요구를 만족하는 멤버는 ctx 를 그대로 돌려받는다 (Req 5.7, 4.1)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    _add_member(test_session, workspace_id=ws.id, user_id=user.id, role="member")
    dep = require_ws_role(Role.MEMBER)
    ctx = _ctx(user)

    result = dep(workspace_id=ws.id, ctx=ctx, db=test_session)

    assert result is ctx


def test_require_ws_role_denies_member_for_owner_action_with_403(test_session):
    """member 가 owner 요구 관리 작업을 요청하면 403 FORBIDDEN (Req 5.4, INV-2)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    _add_member(test_session, workspace_id=ws.id, user_id=user.id, role="member")
    dep = require_ws_role(Role.OWNER)
    ctx = _ctx(user)

    with pytest.raises(DomainError) as exc:
        dep(workspace_id=ws.id, ctx=ctx, db=test_session)

    assert exc.value.code == ErrorCode.FORBIDDEN
    assert exc.value.http_status == 403


def test_require_ws_role_denies_non_member_with_403(test_session):
    """멤버가 아니면 403 FORBIDDEN (Req 5.3, 4.6)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    dep = require_ws_role(Role.MEMBER)
    ctx = _ctx(user)

    with pytest.raises(DomainError) as exc:
        dep(workspace_id=ws.id, ctx=ctx, db=test_session)

    assert exc.value.code == ErrorCode.FORBIDDEN
    assert exc.value.http_status == 403


def test_require_ws_role_admin_bypasses(test_session):
    """admin 은 멤버가 아니어도 통과하며 ctx 를 돌려받는다 (Req 5.5, INV-3)."""
    ws = _make_workspace(test_session)
    admin = _make_user(test_session, is_admin=True)
    dep = require_ws_role(Role.OWNER)
    ctx = _ctx(admin)

    result = dep(workspace_id=ws.id, ctx=ctx, db=test_session)

    assert result is ctx


# --- require_admin() 게이트 (권한 단일화, INV-3) --------------------------


def test_require_admin_passes_for_admin(test_session):
    """admin ctx 는 그대로 통과한다."""
    admin = _make_user(test_session, is_admin=True)
    ctx = _ctx(admin)

    assert require_admin(ctx=ctx) is ctx


def test_require_admin_denies_non_admin_with_403():
    """비-admin ctx 는 403 FORBIDDEN 으로 거부된다."""
    ctx = AuthContext(user_id=1, is_admin=False)

    with pytest.raises(DomainError) as exc:
        require_admin(ctx=ctx)

    assert exc.value.code == ErrorCode.FORBIDDEN
    assert exc.value.http_status == 403
