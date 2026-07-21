"""create_app 조립 지점에 공유 라우터·lifespan 무효화 스케줄러가 결선되었는지 검증 (Req 7.4, 7.5).

s01 ``create_app()`` 의 feature 라우터 조립 지점에 s14 sharing 라우터가 ``include_router`` 로
추가되어, 공유 4개 엔드포인트(카탈로그 행 34~37)가 애플리케이션 라우트 테이블(OpenAPI paths)에
노출되는지 확인한다(7.4). 또한 앱 lifespan startup/shutdown 훅에 무효화 스윕 스케줄러
``start(app)``/``stop()`` 이 s10 trash·s12 attachment 스케줄러와 나란히 연결되었는지 ASGI
lifespan 을 구동해 확인한다. 안정적인 introspection 표면인 ``app.openapi()["paths"]`` 를
사용하며(FastAPI 는 include_router 를 lazy 로 보관해 ``app.routes`` 순회로는 하위 경로가
드러나지 않는다), 라우트 테이블·메서드만 검사하므로 DB 는 필요하지 않다. 스케줄러 start/stop 은
monkeypatch 로 기록만 하여 실제 BackgroundScheduler 스레드가 뜨지 않게 한다(결정성·누수 방지).

새 스키마 마이그레이션 부재(7.5)는 versions 디렉터리에 s01 초기 마이그레이션(0001)만 존재하고
sharing 전용 마이그레이션이 추가되지 않았음을 확인한다(강한 검증은 부모의 git 청결성 체크).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


from tests.support import logical_openapi_paths


def test_sharing_routes_registered_at_assembly_point() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    expected = {
        "/documents/{id}/share": {"post", "patch"},
        "/public/{token}": {"get"},
        "/public/{token}/attachments/{aid}": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths, f"{path} 가 OpenAPI paths 에 없음(카탈로그 행 34~37 미노출)"
        for method in methods:
            assert method in paths[path], f"{method.upper()} {path} 가 노출되지 않음"


def test_earlier_spec_routes_still_present() -> None:
    app = create_app()
    paths = logical_openapi_paths(app)
    # 조립 seam 회귀 가드: s12 첨부·s10 휴지통·s01 health 라우트가 여전히 노출되어야 한다.
    assert "/attachments/{id}" in paths, "s12 /attachments/{id} 가 사라짐"
    assert "/workspaces/{id}/trash" in paths, "s10 /workspaces/{id}/trash 가 사라짐"
    assert "/health" in paths, "s01 /health 가 사라짐"


def test_lifespan_starts_and_stops_sharing_scheduler(monkeypatch) -> None:
    # main 이 참조하는 공유 스케줄러 모듈의 start/stop 을 기록용으로 대체(실제 스레드 억제).
    from app.sharing import scheduler as sharing_scheduler

    calls: list[str] = []

    def _fake_start(app) -> None:  # noqa: ANN001
        calls.append("start")

    def _fake_stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(sharing_scheduler, "start", _fake_start)
    monkeypatch.setattr(sharing_scheduler, "stop", _fake_stop)

    app = create_app()
    # with TestClient(...) 는 ASGI lifespan 을 진입/종료시켜 startup/shutdown 훅을 구동한다.
    with TestClient(app):
        assert "start" in calls, "lifespan startup 에서 sharing scheduler.start 가 호출되지 않음"
    assert calls == ["start", "stop"], (
        "lifespan shutdown 에서 sharing scheduler.stop 이 호출되지 않음"
    )


def test_no_new_sharing_migration_added() -> None:
    """Req 7.5: 공유는 s01 초기 마이그레이션 스키마(share_link 포함) 위에서 동작하고 새 마이그레이션을 더하지 않는다.

    versions 디렉터리에 s01 초기 마이그레이션만 존재하고 sharing 전용 마이그레이션 파일이
    추가되지 않았음을 확인한다(강한 검증은 부모의 ``git status --porcelain migrations/`` 청결성).
    """
    versions_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    migration_files = sorted(p.name for p in versions_dir.glob("*.py"))
    # s01 baseline(0001) + additive user_setting(0002·0003) + s26 role 2단계화(0004)만 허용.
    # sharing 전용 마이그레이션은 여전히 없어야 한다.
    assert migration_files == [
        "0001_initial_schema.py",
        "0002_user_setting.py",
        "0003_user_setting_last_selected_workspace.py",
        "0004_open_access_roles.py",
    ], (
        f"sharing 전용 마이그레이션이 추가되면 안 된다(발견: {migration_files})"
    )
