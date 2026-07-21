"""create_app 조립 지점에 auth 라우터가 결선되었는지 검증 (Req 5.1, 5.3).

s01 ``create_app()`` 의 feature 라우터 조립 지점에 s02 auth 라우터가
``include_router`` 로 추가되어, 4개 auth 엔드포인트가 애플리케이션 라우트
테이블(OpenAPI paths)에 노출되는지 확인한다. 이 FastAPI 버전에서
``app.routes`` 래핑이 다르므로 안정적인 introspection 표면인
``app.openapi()["paths"]`` 를 사용한다. 라우트 테이블만 검사하므로 DB 는
필요하지 않다(get_db 를 타는 요청을 보내지 않는다).
"""

from app.main import create_app


from tests.support import logical_openapi_paths


def test_auth_routes_registered_at_assembly_point() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    for path in ("/auth/login", "/auth/logout", "/auth/me", "/auth/password"):
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"


def test_health_route_still_present() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    assert "/health" in paths
