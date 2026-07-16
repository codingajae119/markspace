"""애플리케이션 부트스트랩 조립 지점 테스트 (Requirement 8.1, 8.4, 8.5, 8.6).

`create_app()`이 Settings 로드·SessionMiddleware 등록·공통 에러 핸들러 등록·
health 라우터 조립·feature 라우터 조립 지점을 올바르게 구성하는지 관찰 가능한
동작으로 검증한다. 조립 지점은 원래 s01에서 비어 있었으나 s02(task 3.2)가 auth
라우터를 등록했으므로, 현재 불변식은 "구현된 spec(health + auth)만 등록되고
미구현 spec은 부재"다. 실제 DB 연결 점검(8.3)은 task 4.2의 범위이므로 여기서는
health 라우터가 조립되어 200을 반환하는지만 확인한다.
"""

from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.main import create_app

# 아직 구현되지 않은 하위 spec의 feature 엔드포인트 경로(조립 지점 미등록 검증용).
# s02가 auth 라우터를 등록했으므로 /auth/* 는 제외한다(s02 task 3.2).
_UNIMPLEMENTED_FEATURE_PATHS = (
    "/workspaces",
    "/documents",
    "/trash",
    "/attachments",
    "/share",
)

# s02(task 3.2)가 조립 지점에 등록한 인증 엔드포인트.
_AUTH_PATHS = (
    "/auth/login",
    "/auth/logout",
    "/auth/me",
    "/auth/password",
)


def test_create_app_loads_settings_title() -> None:
    """8.1: create_app()이 Settings를 로드해 app.title을 설정한다."""
    app = create_app()
    assert app.title == get_settings().app_name


def test_session_middleware_registered() -> None:
    """8.6: 모든 요청이 세션 미들웨어를 거치도록 SessionMiddleware가 등록된다."""
    app = create_app()
    assert any(mw.cls is SessionMiddleware for mw in app.user_middleware)


def test_unhandled_exception_becomes_common_error_response() -> None:
    """8.5: 미처리 예외가 내부 세부정보 노출 없이 500 공통 ErrorResponse로 변환된다."""
    app = create_app()

    def _boom() -> None:
        raise RuntimeError("secret internal detail")

    app.add_api_route("/_boom", _boom, methods=["GET"])

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/_boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "internal"
    # 내부 세부정보(예외 문자열)가 응답 본문에 새어나오지 않는다.
    assert "secret internal detail" not in resp.text


def test_health_router_included() -> None:
    """8.1: health 라우터가 조립 지점에 포함되어 GET /health가 200을 반환한다."""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_feature_router_assembly_point_hosts_only_implemented_specs() -> None:
    """8.4: feature 라우터 조립 지점에는 구현된 spec만 등록된다.

    원래 8.4는 s01이 조립 지점을 비워 둔다(health만 등록)는 것을 검증했으나,
    s02(task 3.2)가 조립 지점에 auth 라우터를 등록하면서 불변식이 갱신되었다:
    구현된 spec(health + auth)만 등록되고, 아직 구현되지 않은 하위 spec
    (workspaces/documents/trash/attachments/share)의 경로는 여전히 부재한다.

    OpenAPI 스키마의 paths는 실제로 조립되어 계약으로 노출된 엔드포인트
    집합이므로, 이를 기준으로 등록 여부를 검증한다.
    """
    app = create_app()
    paths = set(app.openapi()["paths"].keys())

    # health(s01) 및 auth(s02 task 3.2)는 조립되어 노출된다.
    assert "/health" in paths
    for auth_path in _AUTH_PATHS:
        assert auth_path in paths
    # 아직 구현되지 않은 하위 spec의 엔드포인트는 등록되지 않는다.
    for feature_path in _UNIMPLEMENTED_FEATURE_PATHS:
        assert feature_path not in paths
