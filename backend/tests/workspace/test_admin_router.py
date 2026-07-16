"""AdminOwnerRouter 결선 단위 테스트 (Task 3.2 / Req 5.1, 5.4, 6.2, 6.4).

design.md §Feature/API #AdminOwnerRouter API Contract 표와 §System Flows(admin 게이트 판정)를
검증한다. DB 없이 라우터 결선만 확인한다: `get_membership_service` 를 가짜 서비스로 override 하여
엔드포인트·경로·메서드·admin 게이트·상태코드·응답 스키마를 단위 검증한다.

핵심 불변식:
- 1개 엔드포인트가 정확한 경로/메서드로 등록된다(POST /admin/workspaces/{id}/owner).
- s01 공통 require_admin 게이트를 소비한다: admin→성공, 비-admin→403, 미인증→401.
- 성공 계약: admin 세션→소유권 변경 위임 후 200 + WorkspaceRead, 서비스에 (id, new_owner_user_id) 전달.
- 미존재 워크스페이스/사용자→404 s01 ErrorResponse(code "not_found").
- 스키마 검증 실패(new_owner_user_id 누락)→422 s01 ErrorResponse(code "validation_error").
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers
from app.workspace.admin_router import get_membership_service
from app.workspace.admin_router import router as admin_router
from app.workspace.schemas import WorkspaceRead

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_READ = WorkspaceRead(
    id=42,
    name="Team",
    is_shareable=False,
    trash_retention_days=30,
    created_at=_NOW,
    updated_at=None,
)


class _FakeService:
    """MembershipService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s05 계약). 호출을 기록하고 canned 응답을 반환한다.
    `raise_error` 가 설정되면 해당 DomainError 를 raise 하여 404 경로를 재현한다.
    """

    def __init__(self, *, raise_error: DomainError | None = None) -> None:
        self.calls: list[tuple] = []
        self._raise_error = raise_error

    def change_owner(self, db, workspace_id, payload) -> WorkspaceRead:
        self.calls.append(("change_owner", workspace_id, payload.new_owner_user_id))
        if self._raise_error is not None:
            raise self._raise_error
        return _READ


def _build_app(
    *, service: _FakeService | None = None
) -> tuple[FastAPI, _FakeService]:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(admin_router)

    fake = service or _FakeService()
    app.dependency_overrides[get_membership_service] = lambda: fake
    # require_admin→get_current_user 가 실 DB 에 접근하지 않도록 get_db 를 무해한 스텁으로 교체.
    # (세션 쿠키가 없으면 get_current_user 는 db 접근 전에 401 을 낸다.)
    app.dependency_overrides[get_db] = lambda: iter([None])
    return app, fake


def _as_admin(app: FastAPI, *, is_admin: bool = True) -> TestClient:
    """get_current_user 를 override 하여 실 DB·세션 없이 인증 컨텍스트를 주입한다.

    require_admin 은 get_current_user 결과의 is_admin 만 검사하므로 admin/비-admin 경로를
    결정적으로 재현한다."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=1, is_admin=is_admin
    )
    return TestClient(app)


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_one_route_registered():
    app, _ = _build_app()
    paths = app.openapi()["paths"]
    admin_ops = {
        (path, method.upper())
        for path, methods in paths.items()
        if path.startswith("/admin")
        for method in methods
    }
    assert admin_ops == {("/admin/workspaces/{id}/owner", "POST")}


# --- 성공 계약(admin 인증) -------------------------------------------------------


def test_change_owner_returns_200_workspace_read():
    app, fake = _build_app()
    client = _as_admin(app)

    resp = client.post("/admin/workspaces/42/owner", json={"new_owner_user_id": 7})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 42
    assert body["name"] == "Team"
    assert body["is_shareable"] is False
    assert body["trash_retention_days"] == 30
    # 서비스에 (workspace_id, new_owner_user_id) 가 전달됨.
    assert fake.calls[-1] == ("change_owner", 42, 7)


# --- admin 게이트: 인증된 비-admin → 403 forbidden -------------------------------


def test_non_admin_forbidden_403():
    app, fake = _build_app()
    client = _as_admin(app, is_admin=False)

    resp = client.post("/admin/workspaces/42/owner", json={"new_owner_user_id": 7})

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
    # 게이트가 막았으므로 서비스는 호출되지 않는다.
    assert fake.calls == []


# --- admin 게이트: 미인증(세션 없음) → 401 unauthenticated -----------------------


def test_unauthenticated_401():
    # get_current_user 를 override 하지 않는다: 세션 쿠키 없이 요청하면 require_admin 이
    # 의존하는 s01 get_current_user 가 db 접근 전에 401 을 낸다.
    app, _ = _build_app()
    client = TestClient(app)

    resp = client.post("/admin/workspaces/42/owner", json={"new_owner_user_id": 7})

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 미존재 워크스페이스/사용자 → 404 -------------------------------------------


def test_missing_workspace_or_user_returns_404():
    fake = _FakeService(
        raise_error=DomainError(
            code=ErrorCode.NOT_FOUND,
            message="Workspace not found",
            http_status=404,
        )
    )
    app, fake = _build_app(service=fake)
    client = _as_admin(app)

    resp = client.post("/admin/workspaces/999/owner", json={"new_owner_user_id": 7})

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    # 서비스가 판정하도록 위임됨을 확인.
    assert fake.calls[-1] == ("change_owner", 999, 7)


# --- 스키마 검증 실패 → 422 -----------------------------------------------------


def test_missing_new_owner_user_id_returns_422():
    app, fake = _build_app()
    client = _as_admin(app)

    resp = client.post("/admin/workspaces/42/owner", json={})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"
    # pydantic 이 위임 전에 거부하므로 서비스는 호출되지 않는다.
    assert fake.calls == []
