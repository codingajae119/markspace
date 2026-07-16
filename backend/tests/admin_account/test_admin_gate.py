"""s01 require_admin 게이트 소비 증명 테스트 (Task 1.2 / Req 1.1, 1.2, 1.3, 1.4).

s03 는 admin 게이트를 **재정의하지 않는다**. `app.common.permissions.require_admin`
(s01 소유·유일 정의)을 import 하여 라우트에 `Depends(require_admin)` 로 부착만 한다.
이 테스트는 그 소비가 실제로 동작함을 증명한다: `Depends(require_admin)` 을 부착한
throwaway 라우트를 마운트하고 세 가지 접근 결과를 검증한다.

- admin AuthContext(is_admin=True) → 통과(200).
- 인증된 비-admin(is_admin=False) → 403, s01 ErrorResponse code "forbidden".
- 미인증(세션 없음) → 401, code "unauthenticated"(require_admin 이 의존하는
  s01 get_current_user 가 산출).

게이트 **정의** 자체의 단위 테스트는 s01 소유(tests/test_permissions.py)이며 여기서
중복하지 않는다. 이 파일은 오직 s03 가 게이트를 부착(소비)할 수 있음을 검증한다.
DB 없이 확인하려고 get_current_user/get_db 를 무해한 스텁으로 override 한다
(tests/auth/test_router.py 의 결선 패턴과 동일).
"""

from fastapi import APIRouter, Depends, FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.common.permissions import require_admin

_PROBE_PATH = "/_probe"


def _build_probe_app() -> FastAPI:
    """`Depends(require_admin)` 를 부착한 throwaway 라우트를 마운트한 최소 앱.

    라우트 핸들러는 게이트가 확정한 AuthContext 를 그대로 반환하므로, 게이트가
    통과할 때만 200 과 함께 그 컨텍스트가 노출된다(부착이 안 되어 있으면 게이트가
    없는 셈이 되어 비-admin/미인증 케이스가 실패한다).
    """
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)

    router = APIRouter()

    @router.get(_PROBE_PATH)
    def _probe(ctx: AuthContext = Depends(require_admin)) -> dict:
        return {"user_id": ctx.user_id, "is_admin": ctx.is_admin}

    app.include_router(router)

    # get_current_user 가 실 DB 에 접근하지 않도록 get_db 를 무해한 스텁으로 교체.
    # (세션 쿠키가 없으면 get_current_user 는 db 접근 전에 401 을 낸다.)
    app.dependency_overrides[get_db] = lambda: iter([None])
    return app


def _inject_context(app: FastAPI, ctx: AuthContext) -> None:
    """get_current_user 를 override 하여 실 DB·세션 없이 인증 컨텍스트를 주입한다.

    require_admin 은 get_current_user 결과의 is_admin 만 검사하므로, 이 주입으로
    admin/비-admin 두 경로를 결정적으로 재현한다(test_router.py 의 _authed_client 와
    동일한 결선 override 방식)."""
    app.dependency_overrides[get_current_user] = lambda: ctx


# --- admin → 통과(200) ---------------------------------------------------------


def test_admin_context_passes_gate_returns_200():
    app = _build_probe_app()
    _inject_context(app, AuthContext(user_id=1, is_admin=True))
    client = TestClient(app)

    resp = client.get(_PROBE_PATH)

    assert resp.status_code == 200
    # 게이트가 admin 컨텍스트를 그대로 통과시켜 핸들러에 전달했음을 확인.
    assert resp.json() == {"user_id": 1, "is_admin": True}


# --- 인증된 비-admin → 403 forbidden -------------------------------------------


def test_non_admin_context_is_forbidden_403():
    app = _build_probe_app()
    _inject_context(app, AuthContext(user_id=2, is_admin=False))
    client = TestClient(app)

    resp = client.get(_PROBE_PATH)

    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "forbidden"  # s01 ErrorResponse 계약
    assert "message" in body


# --- 미인증(세션 없음) → 401 unauthenticated -----------------------------------


def test_unauthenticated_request_is_401():
    # get_current_user 를 override 하지 않는다: 세션 쿠키 없이 요청하면
    # require_admin 이 의존하는 s01 get_current_user 가 db 접근 전에 401 을 낸다.
    app = _build_probe_app()
    client = TestClient(app)

    resp = client.get(_PROBE_PATH)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
