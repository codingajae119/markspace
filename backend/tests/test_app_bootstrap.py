"""애플리케이션 부트스트랩 조립 지점 테스트 (Requirement 8.1, 8.4, 8.5, 8.6).

`create_app()`이 Settings 로드·SessionMiddleware 등록·공통 에러 핸들러 등록·
health 라우터 조립·비어 있는 feature 라우터 조립 지점을 올바르게 구성하는지
관찰 가능한 동작으로 검증한다. 실제 DB 연결 점검(8.3)은 task 4.2의 범위이므로
여기서는 health 라우터가 조립되어 200을 반환하는지만 확인한다.
"""

from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.main import create_app

# s01이 등록하지 않아야 하는 feature 엔드포인트 경로(빈 조립 지점 검증용).
_FEATURE_PATHS = (
    "/auth/login",
    "/auth/logout",
    "/workspaces",
    "/documents",
    "/trash",
    "/attachments",
    "/share",
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


def test_feature_router_assembly_point_is_empty() -> None:
    """8.4: feature 라우터 조립 지점은 초기 비어 있다(health만 등록).

    OpenAPI 스키마의 paths는 실제로 조립되어 계약으로 노출된 엔드포인트
    집합이므로, 이를 기준으로 health만 등록되고 feature 경로는 없음을 검증한다.
    """
    app = create_app()
    paths = set(app.openapi()["paths"].keys())

    assert "/health" in paths
    # s01은 어떤 feature 엔드포인트도 등록하지 않는다(동작은 하위 spec 소유).
    assert paths == {"/health"}
    for feature_path in _FEATURE_PATHS:
        assert feature_path not in paths
