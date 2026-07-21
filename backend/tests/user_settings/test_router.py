"""user_settings 라우터 결선 단위 테스트 (DB 불필요).

`get_user_settings_service` 를 가짜 서비스로 override 하여 경로·메서드·인증 강제·
상태코드·응답 스키마를 단위 검증한다.

핵심 불변식:
- 정확히 2개 엔드포인트(GET /me/settings, PATCH /me/settings)가 등록된다.
- 둘 다 세션 없으면 401 unauthenticated(공개 아님).
- 인증 통과 시 200 + UserSettingsRead JSON({"autosave_enabled": ...})만 노출.
"""

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.user_settings.router import get_user_settings_service
from app.user_settings.router import router as user_settings_router
from app.user_settings.schemas import UserSettingsRead, UserSettingsUpdate


class _FakeService:
    """UserSettingsService 인터페이스를 흉내내는 최소 가짜."""

    def __init__(self, value: bool = False, ws: int | None = None) -> None:
        self.value = value
        self.ws = ws
        self.calls: list[tuple] = []

    def get(self, ctx: AuthContext) -> UserSettingsRead:
        self.calls.append(("get", ctx.user_id))
        return UserSettingsRead(
            autosave_enabled=self.value, last_selected_workspace_id=self.ws
        )

    def update(self, ctx: AuthContext, payload: UserSettingsUpdate) -> UserSettingsRead:
        self.calls.append(
            (
                "update",
                ctx.user_id,
                payload.autosave_enabled,
                payload.last_selected_workspace_id,
            )
        )
        if payload.autosave_enabled is not None:
            self.value = payload.autosave_enabled
        if payload.last_selected_workspace_id is not None:
            self.ws = payload.last_selected_workspace_id
        return UserSettingsRead(
            autosave_enabled=self.value, last_selected_workspace_id=self.ws
        )


def _build_app(*, service: _FakeService | None = None) -> tuple[FastAPI, _FakeService]:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(user_settings_router)

    fake = service or _FakeService()
    app.dependency_overrides[get_user_settings_service] = lambda: fake
    # 세션 쿠키가 없으면 get_current_user 는 db 접근 전에 401 을 낸다.
    app.dependency_overrides[get_db] = lambda: iter([None])
    return app, fake


def _authed_client(app: FastAPI, *, user_id: int = 42) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=user_id, is_admin=False
    )
    return TestClient(app)


# --- 등록/경로 ------------------------------------------------------------------


def test_exactly_two_routes_registered():
    app, _ = _build_app()
    paths = app.openapi()["paths"]
    ops = {
        (path, method.upper())
        for path, methods in paths.items()
        if path.startswith("/me/settings")
        for method in methods
    }
    assert ops == {("/me/settings", "GET"), ("/me/settings", "PATCH")}


# --- 미인증 401 -----------------------------------------------------------------


def test_get_unauthenticated_returns_401():
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.get("/me/settings")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_patch_unauthenticated_returns_401():
    app, _ = _build_app()
    client = TestClient(app)
    resp = client.patch("/me/settings", json={"autosave_enabled": True})
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 인증 통과 계약 -------------------------------------------------------------


def test_get_returns_200_settings_read():
    app, fake = _build_app(service=_FakeService(value=True))
    client = _authed_client(app)

    resp = client.get("/me/settings")

    assert resp.status_code == 200
    assert resp.json() == {"autosave_enabled": True, "last_selected_workspace_id": None}
    assert fake.calls[-1] == ("get", 42)


def test_patch_updates_and_returns_200_settings_read():
    app, fake = _build_app(service=_FakeService(value=False))
    client = _authed_client(app)

    resp = client.patch("/me/settings", json={"autosave_enabled": True})

    assert resp.status_code == 200
    assert resp.json() == {"autosave_enabled": True, "last_selected_workspace_id": None}
    assert fake.calls[-1] == ("update", 42, True, None)


def test_patch_updates_last_selected_workspace():
    app, fake = _build_app(service=_FakeService(value=True))
    client = _authed_client(app)

    resp = client.patch("/me/settings", json={"last_selected_workspace_id": 7})

    assert resp.status_code == 200
    # autosave 는 그대로(True), 워크스페이스만 7 로 갱신되어 응답된다.
    assert resp.json() == {"autosave_enabled": True, "last_selected_workspace_id": 7}
    assert fake.calls[-1] == ("update", 42, None, 7)


def test_patch_empty_body_is_valid_partial_update():
    app, fake = _build_app(service=_FakeService(value=True))
    client = _authed_client(app)

    resp = client.patch("/me/settings", json={})

    assert resp.status_code == 200
    # 빈 PATCH 는 유효하며 현재 값을 반환한다(None → 변경 없음).
    assert resp.json() == {"autosave_enabled": True, "last_selected_workspace_id": None}
    assert fake.calls[-1] == ("update", 42, None, None)


def test_patch_wrong_type_returns_422():
    app, _ = _build_app()
    client = _authed_client(app)

    resp = client.patch("/me/settings", json={"autosave_enabled": "not-a-bool"})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"
