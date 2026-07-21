"""create_app 조립 지점에 lock_version 라우터가 결선되었는지 검증 (Req 7.6).

s01 ``create_app()`` 의 feature 라우터 조립 지점에 s09 lock_version 라우터가
``include_router`` 로 추가되어, 5개 잠금·버전 엔드포인트(카탈로그 행 24~28)가
애플리케이션 라우트 테이블(OpenAPI paths)에 노출되는지 확인한다. 안정적인
introspection 표면인 ``app.openapi()["paths"]`` 를 사용하며(FastAPI ≥0.139 는
include_router 를 lazy ``_IncludedRouter`` 로 보관해 ``app.routes`` 순회로는
하위 경로가 드러나지 않는다), 라우트 테이블·메서드만 검사하므로 DB 는
필요하지 않다(get_db 를 타는 요청을 보내지 않는다).
"""

from app.main import create_app


from tests.support import logical_openapi_paths


def test_lock_version_routes_registered_at_assembly_point() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    expected = {
        "/documents/{id}/lock": {"post"},
        "/documents/{id}/save": {"post"},
        "/documents/{id}/cancel": {"post"},
        "/documents/{id}/force-unlock": {"post"},
        "/documents/{id}/versions": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"
        for method in methods:
            assert method in paths[path], f"{method.upper()} {path} 가 노출되지 않음"


def test_document_routes_still_present() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    # s07 문서 라우터가 여전히 조립되어 있어야 한다(기존 include 순서 보존).
    assert "/documents/{id}/move" in paths, "s07 /documents/{id}/move 가 사라짐"


def test_health_route_still_present() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    assert "/health" in paths
