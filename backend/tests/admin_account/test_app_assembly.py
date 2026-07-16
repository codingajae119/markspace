"""create_app 조립 지점에 admin_account 라우터가 결선되었는지 검증 (Req 8.5).

s01 ``create_app()`` 의 feature 라우터 조립 지점에 s03 admin_account 라우터가
``include_router`` 로 추가되어, 4개 계정관리 엔드포인트가 애플리케이션 라우트
테이블(OpenAPI paths)에 노출되는지 확인한다. 안정적인 introspection 표면인
``app.openapi()["paths"]`` 를 사용하며, 라우트 테이블·메서드만 검사하므로 DB 는
필요하지 않다(get_db 를 타는 요청을 보내지 않는다).
"""

from app.main import create_app


def test_admin_account_routes_registered_at_assembly_point() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    expected = {
        "/admin/users": {"post", "get"},
        "/admin/users/{user_id}": {"patch"},
        "/admin/users/{user_id}/password": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"
        for method in methods:
            assert method in paths[path], f"{method.upper()} {path} 가 노출되지 않음"


def test_auth_routes_still_present() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    for path in ("/auth/login", "/auth/logout", "/auth/me", "/auth/password"):
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"


def test_health_route_still_present() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/health" in paths
