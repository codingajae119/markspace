"""create_app 조립 지점에 워크스페이스·admin 소유권 라우터가 결선되었는지 검증 (Req 6.4·6.5).

s01 ``create_app()`` 의 feature 라우터 조립 지점에 s05 워크스페이스 라우터
(`workspace.router`)와 admin 소유권 라우터(`workspace.admin_router`)가
``include_router`` 로 추가되어, 8개 워크스페이스·멤버십 엔드포인트와 1개 admin
소유권 엔드포인트가 애플리케이션 라우트 테이블(OpenAPI paths)에 노출되는지
확인한다. 안정적인 introspection 표면인 ``app.openapi()["paths"]`` 를 사용하며,
라우트 테이블·메서드만 검사하므로 DB 는 필요하지 않다(get_db 를 타는 요청을
보내지 않는다).
"""

from app.main import create_app


from tests.support import logical_openapi_paths


def test_workspace_routes_registered_at_assembly_point() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    expected = {
        "/workspaces": {"post", "get"},
        "/workspaces/{id}": {"get", "patch", "delete"},
        "/workspaces/{id}/members": {"post"},
        "/workspaces/{id}/members/{uid}": {"patch", "delete"},
    }
    for path, methods in expected.items():
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"
        for method in methods:
            assert method in paths[path], f"{method.upper()} {path} 가 노출되지 않음"


def test_admin_owner_route_registered_at_assembly_point() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    assert "/admin/workspaces/{id}/owner" in paths, "admin 소유권 경로가 OpenAPI paths 에 없음"
    assert "post" in paths["/admin/workspaces/{id}/owner"], "POST /admin/workspaces/{id}/owner 가 노출되지 않음"


def test_prior_spec_routes_still_present() -> None:
    """s02 auth·s03 admin_account·s01 health 경로가 조립에서 회귀 없이 유지되는지 확인."""
    app = create_app()
    paths = logical_openapi_paths(app)
    for path in ("/auth/login", "/auth/logout", "/auth/me", "/auth/password"):
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"
    for path in ("/admin/users", "/admin/users/{user_id}", "/admin/users/{user_id}/password"):
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"
    assert "/health" in paths, "/health 가 OpenAPI paths 에 없음"
