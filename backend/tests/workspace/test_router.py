"""WorkspaceRouter 결선 단위 테스트 (Task 3.1 / Req 1.1, 1.3, 1.5, 2.1, 2.5, 2.6,
3.1, 3.4, 3.5, 4.3, 4.4, 4.5, 6.2, 6.3, 6.4).

design.md §Components → WorkspaceRouter API Contract 표와 §System Flows(게이트 판정)를 검증한다.
DB 없이 라우터 결선만 확인한다:
- 결선/스키마/위임: `get_workspace_service`·`get_membership_service` 를 가짜 서비스로 override
  하고 `get_current_user` 를 admin 컨텍스트로 주입해(게이트 bypass, INV-3) 8개 엔드포인트의
  경로·메서드·상태코드·응답 스키마·서비스 위임을 단위 검증한다.
- 실제 게이트 동작(401/403/admin-bypass): `get_current_user` 로 인증 컨텍스트를 주입하고
  `get_db` 를 가짜 세션으로 교체해 `WorkspaceRoleResolver.resolve` 가 참조하는
  `db.query(WorkspaceMember).filter(...).one_or_none()` 이 선택된 role 멤버(또는 None)를
  돌려주게 한다. 그 결과 owner→통과 / viewer·editor·비멤버→403 / admin→bypass / 미인증→401
  을 재현한다.

핵심 불변식:
- 워크스페이스·멤버십 8개 + s23 assignable-users 1개 + s25 멤버 로스터 GET 1개 = 10개 엔드포인트가 등록된다
  (POST/GET /workspaces, GET/PATCH/DELETE /workspaces/{id},
  GET /workspaces/{id}/assignable-users,
  POST /workspaces/{id}/members, PATCH/DELETE /workspaces/{id}/members/{uid}).
- 생성·목록은 인증만(get_current_user), 상세는 require_ws_role(VIEWER), 수정·삭제·멤버 관리는
  require_ws_role(OWNER) 게이트를 부착한다.
- 성공 계약: POST 201, GET 200, PATCH 200, DELETE 204(no body), 멤버 POST 201.
- 스키마 검증 실패(필수 누락)→422 s01 ErrorResponse(code "validation_error").
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.schemas.base import Page
from app.workspace.router import (
    get_membership_service,
    get_workspace_service,
)
from app.workspace.router import router as workspace_router
from app.workspace.schemas import (
    AssignableUserRead,
    MemberRead,
    MemberRosterRead,
    WorkspaceRead,
)

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_WS_READ = WorkspaceRead(
    id=42,
    name="팀 워크스페이스",
    is_shareable=False,
    trash_retention_days=30,
    created_at=_NOW,
    updated_at=None,
)
_WS_PAGE = Page[WorkspaceRead](items=[_WS_READ], total=1)
_MEMBER_READ = MemberRead(id=5, workspace_id=42, user_id=9, role="editor")
_ASSIGNABLE_READ = AssignableUserRead(id=11, name="배정 가능 사용자", email="a@example.com")
_ASSIGNABLE_PAGE = Page[AssignableUserRead](items=[_ASSIGNABLE_READ], total=1)
_ROSTER_READ = MemberRosterRead(user_id=9, name="멤버 사용자", email="m@example.com", role="editor")
_ROSTER_PAGE = Page[MemberRosterRead](items=[_ROSTER_READ], total=1)


class _FakeWorkspaceService:
    """WorkspaceService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s05 계약). 호출을 기록하고 canned 응답을 반환한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_workspace(self, db, ctx, payload) -> WorkspaceRead:
        self.calls.append(("create_workspace", ctx.user_id, payload.name))
        return _WS_READ

    def list_workspaces(self, db, ctx, limit, offset) -> Page[WorkspaceRead]:
        self.calls.append(("list_workspaces", ctx.user_id, limit, offset))
        return _WS_PAGE

    def get_workspace(self, db, workspace_id) -> WorkspaceRead:
        self.calls.append(("get_workspace", workspace_id))
        return _WS_READ

    def update_workspace(self, db, workspace_id, changes) -> WorkspaceRead:
        self.calls.append(("update_workspace", workspace_id))
        return _WS_READ

    def delete_workspace(self, db, workspace_id) -> None:
        self.calls.append(("delete_workspace", workspace_id))


class _FakeMembershipService:
    """MembershipService 인터페이스를 흉내내는 최소 가짜(스텁)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def add_member(self, db, workspace_id, payload) -> MemberRead:
        self.calls.append(("add_member", workspace_id, payload.user_id, payload.role.value))
        return _MEMBER_READ

    def change_role(self, db, workspace_id, user_id, payload) -> MemberRead:
        self.calls.append(("change_role", workspace_id, user_id, payload.role.value))
        return _MEMBER_READ

    def remove_member(self, db, workspace_id, user_id) -> None:
        self.calls.append(("remove_member", workspace_id, user_id))

    def list_assignable_users(self, db, workspace_id, limit, offset) -> Page[AssignableUserRead]:
        self.calls.append(("list_assignable_users", workspace_id, limit, offset))
        return _ASSIGNABLE_PAGE

    def list_members(self, db, workspace_id, limit, offset) -> Page[MemberRosterRead]:
        self.calls.append(("list_members", workspace_id, limit, offset))
        return _ROSTER_PAGE


# --- 가짜 DB 세션: resolver 의 role 조회만 흉내낸다 ---------------------------------


class _FakeMember:
    """WorkspaceRoleResolver 가 읽는 role 속성만 노출하는 멤버 스텁."""

    def __init__(self, role: str) -> None:
        self.role = role


class _FakeQuery:
    def __init__(self, member) -> None:
        self._member = member

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def one_or_none(self):
        return self._member


class _FakeSession:
    """resolver 의 ``db.query(WorkspaceMember).filter(...).one_or_none()`` 만 지원한다."""

    def __init__(self, member=None) -> None:
        self._member = member

    def query(self, model) -> _FakeQuery:
        return _FakeQuery(self._member)


def _build_app() -> tuple[FastAPI, _FakeWorkspaceService, _FakeMembershipService]:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(workspace_router)

    ws_fake = _FakeWorkspaceService()
    member_fake = _FakeMembershipService()
    app.dependency_overrides[get_workspace_service] = lambda: ws_fake
    app.dependency_overrides[get_membership_service] = lambda: member_fake
    # 기본: get_db 는 무해한 스텁(게이트 admin bypass 시 db 는 참조되지 않는다).
    app.dependency_overrides[get_db] = lambda: iter([None])
    return app, ws_fake, member_fake


def _login(app: FastAPI, *, user_id: int = 1, is_admin: bool = False) -> None:
    """get_current_user 를 override 하여 실 DB·세션 없이 인증 컨텍스트를 주입한다."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=user_id, is_admin=is_admin
    )


def _set_db_member(app: FastAPI, *, role: str | None) -> None:
    """get_db 를 override 하여 resolver 가 선택된 role 멤버(또는 None)를 보게 한다.

    get_db 는 generator 의존성이므로 override 도 세션을 yield 하는 generator 함수로 준다
    (그래야 FastAPI 가 yield 된 세션을 주입한다; 단순 iterator 반환은 iterator 자체가 주입됨).
    """
    member = _FakeMember(role) if role is not None else None

    def _fake_db():
        yield _FakeSession(member)

    app.dependency_overrides[get_db] = _fake_db


# 각 라우트를 (method, path, json_body) 로 나열(미인증 401 검증에 재사용).
_ROUTES = [
    ("post", "/workspaces", {"name": "새 워크스페이스"}),
    ("get", "/workspaces", None),
    ("get", "/workspaces/42", None),
    ("patch", "/workspaces/42", {"name": "갱신"}),
    ("delete", "/workspaces/42", None),
    ("post", "/workspaces/42/members", {"user_id": 9, "role": "editor"}),
    ("patch", "/workspaces/42/members/9", {"role": "owner"}),
    ("delete", "/workspaces/42/members/9", None),
]


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_all_routes_registered():
    app, _, _ = _build_app()
    paths = app.openapi()["paths"]
    ops = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
    }
    assert ops == {
        ("/workspaces", "POST"),
        ("/workspaces", "GET"),
        ("/workspaces/{id}", "GET"),
        ("/workspaces/{id}", "PATCH"),
        ("/workspaces/{id}", "DELETE"),
        ("/workspaces/{id}/assignable-users", "GET"),
        ("/workspaces/{id}/members", "GET"),
        ("/workspaces/{id}/members", "POST"),
        ("/workspaces/{id}/members/{uid}", "PATCH"),
        ("/workspaces/{id}/members/{uid}", "DELETE"),
    }


# --- 성공 계약(admin 인증으로 게이트 bypass) -------------------------------------


def test_create_workspace_returns_201_and_delegates():
    app, ws_fake, _ = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/workspaces", json={"name": "새 워크스페이스"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == 42
    assert body["is_shareable"] is False
    assert ws_fake.calls[-1] == ("create_workspace", 7, "새 워크스페이스")


def test_list_workspaces_returns_200_default_pagination():
    app, ws_fake, _ = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 42
    assert ws_fake.calls[-1] == ("list_workspaces", 7, 50, 0)


def test_list_workspaces_forwards_query_params():
    app, ws_fake, _ = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces", params={"limit": 10, "offset": 20})

    assert resp.status_code == 200
    assert ws_fake.calls[-1] == ("list_workspaces", 7, 10, 20)


def test_get_workspace_returns_200_and_delegates():
    app, ws_fake, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/42")

    assert resp.status_code == 200
    assert resp.json()["id"] == 42
    assert ws_fake.calls[-1] == ("get_workspace", 42)


def test_update_workspace_returns_200_and_delegates():
    app, ws_fake, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.patch("/workspaces/42", json={"name": "갱신"})

    assert resp.status_code == 200
    assert resp.json()["id"] == 42
    assert ws_fake.calls[-1] == ("update_workspace", 42)


def test_delete_workspace_returns_204_no_body_and_delegates():
    app, ws_fake, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.delete("/workspaces/42")

    assert resp.status_code == 204
    assert resp.content == b""
    assert ws_fake.calls[-1] == ("delete_workspace", 42)


def test_add_member_returns_201_and_delegates():
    app, _, member_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/workspaces/42/members", json={"user_id": 9, "role": "editor"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == 9
    assert body["role"] == "editor"
    assert member_fake.calls[-1] == ("add_member", 42, 9, "editor")


def test_change_role_returns_200_and_delegates():
    app, _, member_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.patch("/workspaces/42/members/9", json={"role": "owner"})

    assert resp.status_code == 200
    assert resp.json()["id"] == 5
    assert member_fake.calls[-1] == ("change_role", 42, 9, "owner")


def test_remove_member_returns_204_no_body_and_delegates():
    app, _, member_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.delete("/workspaces/42/members/9")

    assert resp.status_code == 204
    assert resp.content == b""
    assert member_fake.calls[-1] == ("remove_member", 42, 9)


# --- 게이트: 상세(VIEWER) --------------------------------------------------------


def test_get_workspace_viewer_passes():
    app, ws_fake, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db_member(app, role="viewer")
    client = TestClient(app)

    resp = client.get("/workspaces/42")

    assert resp.status_code == 200
    assert ws_fake.calls[-1] == ("get_workspace", 42)


def test_get_workspace_non_member_forbidden_403():
    app, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db_member(app, role=None)
    client = TestClient(app)

    resp = client.get("/workspaces/42")

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


# --- 게이트: 수정·삭제·멤버 관리(OWNER) -----------------------------------------


@pytest.mark.parametrize("method,path,json_body", [
    ("patch", "/workspaces/42", {"name": "x"}),
    ("delete", "/workspaces/42", None),
    ("post", "/workspaces/42/members", {"user_id": 9, "role": "editor"}),
    ("patch", "/workspaces/42/members/9", {"role": "owner"}),
    ("delete", "/workspaces/42/members/9", None),
])
def test_owner_route_owner_passes(method, path, json_body):
    app, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db_member(app, role="owner")
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code in (200, 201, 204), resp.text


@pytest.mark.parametrize("method,path,json_body", [
    ("patch", "/workspaces/42", {"name": "x"}),
    ("delete", "/workspaces/42", None),
    ("post", "/workspaces/42/members", {"user_id": 9, "role": "editor"}),
    ("patch", "/workspaces/42/members/9", {"role": "owner"}),
    ("delete", "/workspaces/42/members/9", None),
])
@pytest.mark.parametrize("role", ["viewer", "editor", None])
def test_owner_route_lower_role_or_non_member_forbidden_403(method, path, json_body, role):
    app, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db_member(app, role=role)
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_owner_route_admin_bypasses():
    """admin 은 멤버십·role 무관하게 OWNER 게이트를 통과한다 (INV-3, Req 4.5)."""
    app, ws_fake, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db_member(app, role=None)  # 비멤버여도 admin 은 bypass.
    client = TestClient(app)

    resp = client.delete("/workspaces/42")

    assert resp.status_code == 204
    assert ws_fake.calls[-1] == ("delete_workspace", 42)


# --- 미인증(세션 없음) → 401 ----------------------------------------------------


@pytest.mark.parametrize("method,path,json_body", _ROUTES)
def test_unauthenticated_401(method, path, json_body):
    # get_current_user 를 override 하지 않는다: 세션 쿠키 없이 요청하면 s01
    # get_current_user 가 db 접근 전에 401 을 낸다.
    app, _, _ = _build_app()
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 스키마 검증 실패 → 422 -----------------------------------------------------


def test_create_workspace_missing_name_returns_422():
    app, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/workspaces", json={})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_add_member_missing_role_returns_422():
    app, _, _ = _build_app()
    _login(app, is_admin=True)  # 게이트 통과 후 본문 검증이 422 를 산출.
    client = TestClient(app)

    resp = client.post("/workspaces/42/members", json={"user_id": 9})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


# --- assignable-users(OWNER 게이트, 배정 가능 조회) 결선 -------------------------
# NOTE: 전체 게이팅 매트릭스(editor/viewer/비멤버→403, admin→200, 미인증→401,
# 존재하지 않는 ws→403)와 페이지네이션·빈 봉투 경계는 task 2.2 의 경계다. 여기서는
# 라우트 결선 + owner happy path + Page 봉투 형태만 최소로 검증한다.


def test_list_assignable_users_owner_returns_200_and_delegates():
    app, _, member_fake = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db_member(app, role="owner")
    client = TestClient(app)

    resp = client.get("/workspaces/42/assignable-users?limit=50&offset=0")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 11
    assert body["items"][0]["email"] == "a@example.com"
    assert member_fake.calls[-1] == ("list_assignable_users", 42, 50, 0)


# --- s25 멤버 로스터(OWNER 게이트, GET /workspaces/{id}/members) 결선 -------------
# NOTE: 전체 게이팅 매트릭스(editor/viewer/비멤버·미존재 WS→403, admin→200, 미인증→401,
# anti-enumeration)와 결정적 순서·전체 count 경계는 통합 테스트(task 3.x)의 경계다.
# 여기서는 라우트 결선 + owner happy path + Page[MemberRosterRead] 봉투 + 쿼리 수용/범위
# 위반 422 만 DB 없이 단위 검증한다.


def test_list_members_owner_returns_200_and_delegates():
    app, _, member_fake = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db_member(app, role="owner")
    client = TestClient(app)

    resp = client.get("/workspaces/42/members?limit=50&offset=0")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["user_id"] == 9
    assert body["items"][0]["name"] == "멤버 사용자"
    assert body["items"][0]["email"] == "m@example.com"
    assert body["items"][0]["role"] == "editor"
    assert member_fake.calls[-1] == ("list_members", 42, 50, 0)


def test_list_members_default_pagination():
    app, _, member_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/42/members")

    assert resp.status_code == 200
    assert member_fake.calls[-1] == ("list_members", 42, 50, 0)


def test_list_members_forwards_query_params():
    app, _, member_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/42/members", params={"limit": 10, "offset": 20})

    assert resp.status_code == 200
    assert member_fake.calls[-1] == ("list_members", 42, 10, 20)


@pytest.mark.parametrize("params", [{"limit": 0}, {"offset": -1}])
def test_list_members_query_range_violation_returns_422(params):
    app, _, _ = _build_app()
    _login(app, is_admin=True)  # 게이트 통과 후 쿼리 검증이 422 를 산출.
    client = TestClient(app)

    resp = client.get("/workspaces/42/members", params=params)

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"
