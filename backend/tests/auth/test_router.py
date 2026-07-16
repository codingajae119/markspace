"""AuthRouter 결선 단위 테스트 (Task 3.1 / Req 1.2, 2.2, 2.3, 3.2, 3.3, 4.6, 5.2).

design.md §auth/API #AuthRouter API Contract 표와 System Flows(미인증 보호 접근)를 검증한다.
DB 없이 라우터 결선만 확인한다: `get_auth_service` 를 가짜 서비스로 override 하여
엔드포인트·경로·메서드·인증 강제·상태코드·응답 스키마를 단위 검증한다.

핵심 불변식:
- 4개 엔드포인트가 정확한 경로/메서드로 등록된다(POST /auth/login, POST /auth/logout,
  GET /auth/me, POST /auth/password).
- /auth/login 만 공개(인증 의존성 없음). 나머지는 세션 없으면 401 unauthenticated.
- login/me → 200 AuthUserRead JSON. logout/password → 204 no body.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.auth.router import get_auth_service
from app.auth.router import router as auth_router
from app.auth.schemas import AuthUserRead
from app.common.auth import AuthContext
from app.common.db import get_db
from app.common.errors import register_error_handlers

_READ = AuthUserRead(
    id=42,
    login_id="alice",
    name="Alice",
    email="alice@example.com",
    is_admin=False,
)


class _FakeService:
    """AuthService 인터페이스를 흉내내는 최소 가짜(스텁)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def authenticate(self, login_id, password, session) -> AuthUserRead:
        self.calls.append(("authenticate", login_id, password))
        session["user_id"] = _READ.id
        return _READ

    def logout(self, session) -> None:
        self.calls.append(("logout",))
        session.clear()

    def get_me(self, ctx: AuthContext) -> AuthUserRead:
        self.calls.append(("get_me", ctx.user_id))
        return _READ

    def change_password(self, ctx, current_password, new_password) -> None:
        self.calls.append(("change_password", ctx.user_id, current_password, new_password))


def _build_app(*, service: _FakeService | None = None) -> tuple[FastAPI, _FakeService]:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(auth_router)

    fake = service or _FakeService()
    app.dependency_overrides[get_auth_service] = lambda: fake
    # get_current_user 가 실 DB에 접근하지 않도록 get_db 를 무해한 스텁으로 교체.
    # (세션 쿠키가 없으면 get_current_user 는 db 접근 전에 401 을 낸다.)
    app.dependency_overrides[get_db] = lambda: iter([None])
    return app, fake


def _authed_client(app: FastAPI) -> TestClient:
    """세션 쿠키를 심어 get_current_user 를 통과시키려면 실 DB 가 필요하므로,
    보호 엔드포인트 테스트는 get_current_user 자체를 override 하여 인증을 통과시킨다."""
    from app.common.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=42, is_admin=False
    )
    return TestClient(app)


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_four_routes_registered():
    app, _ = _build_app()
    paths = app.openapi()["paths"]
    auth_ops = {
        (path, method.upper())
        for path, methods in paths.items()
        if path.startswith("/auth")
        for method in methods
    }
    assert auth_ops == {
        ("/auth/login", "POST"),
        ("/auth/logout", "POST"),
        ("/auth/me", "GET"),
        ("/auth/password", "POST"),
    }


# --- 공개 로그인 ---------------------------------------------------------------


def test_login_public_returns_200_auth_user_read():
    app, fake = _build_app()
    client = TestClient(app)

    resp = client.post("/auth/login", json={"login_id": "alice", "password": "pw"})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "id": 42,
        "login_id": "alice",
        "name": "Alice",
        "email": "alice@example.com",
        "is_admin": False,
    }
    assert "password_hash" not in body
    assert fake.calls[0] == ("authenticate", "alice", "pw")


def test_login_requires_no_auth_dependency():
    # 세션 쿠키 없이도 200 이어야 한다(공개).
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.post("/auth/login", json={"login_id": "alice", "password": "pw"})
    assert resp.status_code == 200


def test_login_missing_field_returns_422():
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.post("/auth/login", json={"login_id": "alice"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


# --- 보호 엔드포인트: 미인증 401 -------------------------------------------------


@pytest.mark.parametrize(
    "method,path,json_body",
    [
        ("post", "/auth/logout", None),
        ("get", "/auth/me", None),
        ("post", "/auth/password", {"current_password": "x", "new_password": "yyyyyyyy"}),
    ],
)
def test_protected_endpoints_unauthenticated_return_401(method, path, json_body):
    app, _ = _build_app()
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 보호 엔드포인트: 인증 통과 시 계약 -------------------------------------------


def test_me_returns_200_auth_user_read():
    app, fake = _build_app()
    client = _authed_client(app)

    resp = client.get("/auth/me")

    assert resp.status_code == 200
    assert resp.json()["login_id"] == "alice"
    assert fake.calls[-1] == ("get_me", 42)


def test_logout_returns_204_no_body():
    app, fake = _build_app()
    client = _authed_client(app)

    resp = client.post("/auth/logout")

    assert resp.status_code == 204
    assert resp.content == b""
    assert fake.calls[-1] == ("logout",)


def test_change_password_returns_204_no_body():
    app, fake = _build_app()
    client = _authed_client(app)

    resp = client.post(
        "/auth/password",
        json={"current_password": "old", "new_password": "newpassword"},
    )

    assert resp.status_code == 204
    assert resp.content == b""
    assert fake.calls[-1] == ("change_password", 42, "old", "newpassword")


def test_change_password_short_new_password_returns_422():
    app, _ = _build_app()
    client = _authed_client(app)

    resp = client.post(
        "/auth/password",
        json={"current_password": "old", "new_password": "short"},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"
