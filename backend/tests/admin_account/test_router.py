"""AdminUserRouter 결선 단위 테스트 (Task 3.1 / Req 1.1, 1.2, 1.3, 2.2, 3.1, 4.1, 5.1, 6.1, 7.1, 8.2).

design.md §Components and Interfaces #AdminUserRouter API Contract 표와 §System Flows(게이트 판정)를
검증한다. DB 없이 라우터 결선만 확인한다: `get_admin_account_service` 를 가짜 서비스로 override 하여
엔드포인트·경로·메서드·admin 게이트·상태코드·응답 스키마를 단위 검증한다.

핵심 불변식:
- 4개 엔드포인트가 정확한 경로/메서드로 등록된다(POST /admin/users, GET /admin/users,
  PATCH /admin/users/{user_id}, POST /admin/users/{user_id}/password).
- 전 라우트가 s01 require_admin 게이트를 부착한다: admin→성공, 비-admin→403, 미인증→401.
- 성공 계약: POST 201 UserRead, GET 200 Page[UserRead], PATCH 200 UserRead, password POST 204 no body.
- 스키마 검증 실패(필수 누락)→422 s01 ErrorResponse(code "validation_error").
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.admin_account.router import get_admin_account_service
from app.admin_account.router import router as admin_router
from app.admin_account.schemas import UserRead
from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.schemas.base import Page

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_READ = UserRead(
    id=7,
    login_id="bob",
    name="Bob",
    email="bob@example.com",
    is_admin=False,
    is_active=True,
    is_deleted=False,
    created_at=_NOW,
    updated_at=None,
)
_PAGE = Page[UserRead](items=[_READ], total=1)


class _FakeService:
    """AdminAccountService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s03 계약). 호출을 기록하고 canned 응답을 반환한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_user(self, db, payload) -> UserRead:
        self.calls.append(("create_user", payload.login_id))
        return _READ

    def list_users(self, db, limit, offset) -> Page[UserRead]:
        self.calls.append(("list_users", limit, offset))
        return _PAGE

    def update_user(self, db, user_id, changes) -> UserRead:
        self.calls.append(("update_user", user_id))
        return _READ

    def reset_password(self, db, user_id, req) -> None:
        self.calls.append(("reset_password", user_id, req.new_password))


def _build_app(*, service: _FakeService | None = None) -> tuple[FastAPI, _FakeService]:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(admin_router)

    fake = service or _FakeService()
    app.dependency_overrides[get_admin_account_service] = lambda: fake
    # require_admin→get_current_user 가 실 DB 에 접근하지 않도록 get_db 를 무해한 스텁으로 교체.
    # (세션 쿠키가 없으면 get_current_user 는 db 접근 전에 401 을 낸다.)
    app.dependency_overrides[get_db] = lambda: iter([None])
    return app, fake


def _as_admin(app: FastAPI, *, is_admin: bool = True) -> TestClient:
    """get_current_user 를 override 하여 실 DB·세션 없이 인증 컨텍스트를 주입한다.

    require_admin 은 get_current_user 결과의 is_admin 만 검사하므로 admin/비-admin 경로를
    결정적으로 재현한다(test_router.py 의 _authed_client 와 동일 결선 override)."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=1, is_admin=is_admin
    )
    return TestClient(app)


# 각 라우트를 admin 인증으로 호출하는 파라미터 세트(미인증 401 검증에 재사용).
_ROUTES = [
    ("post", "/admin/users", {"login_id": "bob", "password": "pw", "name": "Bob"}),
    ("get", "/admin/users", None),
    ("patch", "/admin/users/7", {"is_active": False}),
    ("post", "/admin/users/7/password", {"new_password": "newsecret"}),
]


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_four_routes_registered():
    app, _ = _build_app()
    paths = app.openapi()["paths"]
    admin_ops = {
        (path, method.upper())
        for path, methods in paths.items()
        if path.startswith("/admin")
        for method in methods
    }
    assert admin_ops == {
        ("/admin/users", "POST"),
        ("/admin/users", "GET"),
        ("/admin/users/{user_id}", "PATCH"),
        ("/admin/users/{user_id}/password", "POST"),
    }


# --- 성공 계약(admin 인증) -------------------------------------------------------


def test_create_user_returns_201_user_read():
    app, fake = _build_app()
    client = _as_admin(app)

    resp = client.post(
        "/admin/users",
        json={"login_id": "bob", "password": "pw", "name": "Bob"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["login_id"] == "bob"
    assert body["is_admin"] is False
    assert "password_hash" not in body
    assert fake.calls[-1] == ("create_user", "bob")


def test_list_users_returns_200_page_user_read_default_pagination():
    app, fake = _build_app()
    client = _as_admin(app)

    resp = client.get("/admin/users")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["login_id"] == "bob"
    # 기본 페이지네이션(limit=50, offset=0)이 서비스에 전달됨.
    assert fake.calls[-1] == ("list_users", 50, 0)


def test_list_users_forwards_query_params():
    app, fake = _build_app()
    client = _as_admin(app)

    resp = client.get("/admin/users", params={"limit": 10, "offset": 20})

    assert resp.status_code == 200
    assert fake.calls[-1] == ("list_users", 10, 20)


def test_update_user_returns_200_user_read():
    app, fake = _build_app()
    client = _as_admin(app)

    resp = client.patch("/admin/users/7", json={"is_active": False})

    assert resp.status_code == 200
    assert resp.json()["id"] == 7
    assert fake.calls[-1] == ("update_user", 7)


def test_reset_password_returns_204_no_body():
    app, fake = _build_app()
    client = _as_admin(app)

    resp = client.post("/admin/users/7/password", json={"new_password": "newsecret"})

    assert resp.status_code == 204
    assert resp.content == b""
    assert fake.calls[-1] == ("reset_password", 7, "newsecret")


# --- admin 게이트: 인증된 비-admin → 403 forbidden -------------------------------


@pytest.mark.parametrize("method,path,json_body", _ROUTES)
def test_non_admin_forbidden_403(method, path, json_body):
    app, _ = _build_app()
    client = _as_admin(app, is_admin=False)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


# --- admin 게이트: 미인증(세션 없음) → 401 unauthenticated -----------------------


@pytest.mark.parametrize("method,path,json_body", _ROUTES)
def test_unauthenticated_401(method, path, json_body):
    # get_current_user 를 override 하지 않는다: 세션 쿠키 없이 요청하면 require_admin 이
    # 의존하는 s01 get_current_user 가 db 접근 전에 401 을 낸다.
    app, _ = _build_app()
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 스키마 검증 실패 → 422 -----------------------------------------------------


def test_create_user_missing_required_field_returns_422():
    app, _ = _build_app()
    client = _as_admin(app)

    # name 누락(필수).
    resp = client.post("/admin/users", json={"login_id": "bob", "password": "pw"})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_reset_password_missing_field_returns_422():
    app, _ = _build_app()
    client = _as_admin(app)

    resp = client.post("/admin/users/7/password", json={})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"
