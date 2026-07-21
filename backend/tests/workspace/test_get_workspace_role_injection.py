"""WS 상세 role 주입 + 읽기 전역 개방 테스트 (Task 3.4 / Req 3.5, 3.7, 3.8, 7.2).

design.md §Components → `WorkspaceService.get_workspace`(Service Interface·Responsibilities)
및 §Decision D3, §Modified Files 를 검증한다. 두 계층을 다룬다:

- 서비스 계층: `get_workspace(db, workspace_id, ctx)` 가 호출자 관점 role 을 주입한다 —
  owner/member 는 자신의 role, 비멤버(admin 포함)는 None(admin 미상승, INV-3). 비멤버도
  이름·설정(is_shareable·보관일)을 그대로 받는다(R3.5·R3.8). 부재 WS 는 404.
- 라우터 계층: `GET /workspaces/{id}` 게이트가 `require_ws_role(MEMBER)` → `get_current_user`
  (활성 사용자 전용)로 교체되어, 비멤버 활성 사용자가 403 없이 200 을 받고 `ctx` 가 서비스로
  전달된다(R3.7·R7.2).

세션(`db`)은 메서드별 인자로 전달받는 계약이므로 가짜 repo 는 각 메서드의 첫 인자로 `db` 를 받는다.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers
from app.models import Workspace
from app.workspace.router import get_workspace_service
from app.workspace.router import router as workspace_router
from app.workspace.schemas import MemberRole, WorkspaceRead
from app.workspace.service import WorkspaceService


def _make_ws(
    *,
    ws_id: int = 1,
    name: str = "WS",
    is_shareable: bool = False,
    trash_retention_days: int = 30,
) -> Workspace:
    return Workspace(
        id=ws_id,
        name=name,
        is_shareable=is_shareable,
        trash_retention_days=trash_retention_days,
        created_at=datetime(2026, 1, 1),
        updated_at=None,
    )


NON_MEMBER_CTX = AuthContext(user_id=42, is_admin=False)
ADMIN_NON_MEMBER_CTX = AuthContext(user_id=7, is_admin=True)
OWNER_CTX = AuthContext(user_id=10, is_admin=False)
MEMBER_CTX = AuthContext(user_id=11, is_admin=False)


class _FakeWorkspaceRepo:
    def __init__(self, *, by_id: Workspace | None = None) -> None:
        self._by_id = by_id
        self.get_by_id_calls: list[int] = []

    def get_by_id(self, db, workspace_id: int) -> Workspace | None:
        self.get_by_id_calls.append(workspace_id)
        return self._by_id


class _FakeMembershipRepo:
    """`get_role(db, workspace_id, user_id) -> str | None` 만 흉내내는 최소 가짜.

    (workspace_id, user_id) → role 문자열 매핑을 보유하며 미등록은 None 을 반환한다.
    """

    def __init__(self, roles: dict[tuple[int, int], str] | None = None) -> None:
        self._roles = roles or {}
        self.get_role_calls: list[tuple[int, int]] = []

    def get_role(self, db, workspace_id: int, user_id: int) -> str | None:
        self.get_role_calls.append((workspace_id, user_id))
        return self._roles.get((workspace_id, user_id))


# --- 서비스 계층: role 주입 -------------------------------------------------------


def test_get_workspace_non_member_returns_fields_and_role_none():
    """비멤버 활성 사용자: 이름·설정을 받고 role 은 None(R3.5·R3.8)."""
    ws = _make_ws(ws_id=8, name="Found", is_shareable=True, trash_retention_days=15)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    member_repo = _FakeMembershipRepo()  # 비멤버: get_role → None
    service = WorkspaceService(ws_repo, member_repo)

    result = service.get_workspace(None, 8, NON_MEMBER_CTX)

    assert isinstance(result, WorkspaceRead)
    assert result.id == 8
    assert result.name == "Found"
    assert result.is_shareable is True
    assert result.trash_retention_days == 15
    assert result.role is None
    # 호출자 관점 role 을 실제 user_id 로 조회했다.
    assert member_repo.get_role_calls == [(8, NON_MEMBER_CTX.user_id)]


def test_get_workspace_owner_caller_role_owner():
    ws = _make_ws(ws_id=8)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    member_repo = _FakeMembershipRepo({(8, OWNER_CTX.user_id): "owner"})
    service = WorkspaceService(ws_repo, member_repo)

    result = service.get_workspace(None, 8, OWNER_CTX)

    assert result.role == MemberRole.OWNER


def test_get_workspace_member_caller_role_member():
    ws = _make_ws(ws_id=8)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    member_repo = _FakeMembershipRepo({(8, MEMBER_CTX.user_id): "member"})
    service = WorkspaceService(ws_repo, member_repo)

    result = service.get_workspace(None, 8, MEMBER_CTX)

    assert result.role == MemberRole.MEMBER


def test_get_workspace_admin_non_member_role_none_no_elevation():
    """admin 이어도 비멤버면 role 은 None — 상승 없음(INV-3)."""
    ws = _make_ws(ws_id=8)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    member_repo = _FakeMembershipRepo()  # admin 은 이 WS 멤버가 아님
    service = WorkspaceService(ws_repo, member_repo)

    result = service.get_workspace(None, 8, ADMIN_NON_MEMBER_CTX)

    assert result.role is None
    assert member_repo.get_role_calls == [(8, ADMIN_NON_MEMBER_CTX.user_id)]


def test_get_workspace_missing_raises_404():
    ws_repo = _FakeWorkspaceRepo(by_id=None)
    member_repo = _FakeMembershipRepo()
    service = WorkspaceService(ws_repo, member_repo)

    with pytest.raises(DomainError) as ei:
        service.get_workspace(None, 999, NON_MEMBER_CTX)

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert ws_repo.get_by_id_calls == [999]


# --- 라우터 계층: 활성 사용자 게이트(비멤버 200) ---------------------------------


_NOW = datetime(2026, 1, 1, 0, 0, 0)
_WS_READ_NON_MEMBER = WorkspaceRead(
    id=42,
    name="팀 워크스페이스",
    is_shareable=True,
    trash_retention_days=20,
    created_at=_NOW,
    updated_at=None,
    role=None,
)


class _FakeWorkspaceService:
    """`get_workspace(db, workspace_id, ctx)` 새 시그니처를 흉내내는 스텁."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_workspace(self, db, workspace_id, ctx) -> WorkspaceRead:
        self.calls.append(("get_workspace", workspace_id, ctx.user_id, ctx.is_admin))
        return _WS_READ_NON_MEMBER


def _build_app() -> tuple[FastAPI, _FakeWorkspaceService]:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(workspace_router)

    ws_fake = _FakeWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: ws_fake
    app.dependency_overrides[get_db] = lambda: iter([None])
    return app, ws_fake


def test_get_workspace_route_non_member_active_user_returns_200():
    """비멤버 활성 사용자가 상세를 200 으로 받고(게이트 = 활성 사용자), role 은 null.

    role 게이트가 없으므로 db(멤버 role) 를 참조하지 않고도 통과한다. ctx 가 서비스로
    전달되는지도 함께 검증한다(R3.7·R7.2).
    """
    app, ws_fake = _build_app()
    app.dependency_overrides[get_current_user] = lambda: NON_MEMBER_CTX
    client = TestClient(app)

    resp = client.get("/workspaces/42")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == 42
    assert body["name"] == "팀 워크스페이스"
    assert body["is_shareable"] is True
    assert body["trash_retention_days"] == 20
    assert body["role"] is None
    # 라우터가 ctx 를 서비스로 전달했다.
    assert ws_fake.calls[-1] == (
        "get_workspace",
        42,
        NON_MEMBER_CTX.user_id,
        False,
    )


def test_get_workspace_route_unauthenticated_401():
    """미인증은 여전히 401 — 개방은 활성 사용자에 한정(R7.3)."""
    app, _ = _build_app()
    client = TestClient(app)

    resp = client.get("/workspaces/42")

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
