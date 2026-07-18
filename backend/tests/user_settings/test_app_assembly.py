"""create_app 조립 지점에 user_settings 라우터가 결선되었는지 검증.

s01 ``create_app()`` 의 feature 라우터 조립 지점에 user_settings 라우터가
``include_router`` 로 추가되어 `/me/settings` 의 GET·PATCH 가 애플리케이션 라우트
테이블(OpenAPI paths)에 노출되는지 확인한다. 라우트 표만 검사하므로 DB 불필요.
"""

from app.main import create_app


def test_user_settings_routes_registered_at_assembly_point():
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/me/settings" in paths, "/me/settings 가 OpenAPI paths 에 없음"
    assert "get" in paths["/me/settings"], "GET /me/settings 가 노출되지 않음"
    assert "patch" in paths["/me/settings"], "PATCH /me/settings 가 노출되지 않음"


def test_prior_spec_routes_still_present():
    """기존 spec 경로가 조립에서 회귀 없이 유지되는지 확인."""
    app = create_app()
    paths = app.openapi()["paths"]
    for path in ("/auth/login", "/auth/me", "/workspaces", "/health"):
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"
