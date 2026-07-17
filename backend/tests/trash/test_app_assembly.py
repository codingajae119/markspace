"""create_app 조립 지점에 휴지통 라우터·lifespan 스케줄러가 결선되었는지 검증 (Req 6.5, 6.6).

s01 ``create_app()`` 의 feature 라우터 조립 지점에 s10 trash 라우터가 ``include_router``
로 추가되어, 3개 휴지통 엔드포인트(카탈로그 행 29~31)가 애플리케이션 라우트
테이블(OpenAPI paths)에 노출되는지 확인한다(6.5). 또한 앱 lifespan startup/shutdown
훅에 보관 스윕 스케줄러 ``start(app)``/``stop()`` 이 연결되었는지 ASGI lifespan 을
구동해 확인한다. 안정적인 introspection 표면인 ``app.openapi()["paths"]`` 를 사용하며
(FastAPI 는 include_router 를 lazy 로 보관해 ``app.routes`` 순회로는 하위 경로가 드러나지
않는다), 라우트 테이블·메서드만 검사하므로 DB 는 필요하지 않다(get_db 를 타는 요청을
보내지 않는다). 스케줄러 start/stop 은 monkeypatch 로 기록만 하여 실제
BackgroundScheduler 스레드가 뜨지 않게 한다(결정성).
"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_trash_routes_registered_at_assembly_point() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    expected = {
        "/workspaces/{id}/trash": {"get"},
        "/trash/{bundleId}/restore": {"post"},
        "/trash/{bundleId}": {"delete"},
    }
    for path, methods in expected.items():
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음"
        for method in methods:
            assert method in paths[path], f"{method.upper()} {path} 가 노출되지 않음"


def test_earlier_spec_routes_still_present() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    # 조립 seam 회귀 가드: s09 잠금·s07 문서·s01 health 라우트가 여전히 노출되어야 한다.
    assert "/documents/{id}/lock" in paths, "s09 /documents/{id}/lock 가 사라짐"
    assert (
        "/workspaces/{workspace_id}/documents" in paths
    ), "s07 /workspaces/{workspace_id}/documents 가 사라짐"
    assert "/health" in paths, "s01 /health 가 사라짐"


def test_lifespan_starts_and_stops_scheduler(monkeypatch) -> None:
    # main 이 참조하는 스케줄러 모듈의 start/stop 을 기록용으로 대체(실제 스레드 억제).
    from app.trash import scheduler as trash_scheduler

    calls: list[str] = []

    def _fake_start(app) -> None:  # noqa: ANN001
        calls.append("start")

    def _fake_stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(trash_scheduler, "start", _fake_start)
    monkeypatch.setattr(trash_scheduler, "stop", _fake_stop)

    app = create_app()
    # with TestClient(...) 는 ASGI lifespan 을 진입/종료시켜 startup/shutdown 훅을 구동한다.
    with TestClient(app):
        assert calls == ["start"], "lifespan startup 에서 scheduler.start 가 호출되지 않음"
    assert calls == ["start", "stop"], "lifespan shutdown 에서 scheduler.stop 이 호출되지 않음"
