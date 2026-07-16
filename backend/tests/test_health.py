"""health 라우터 DB 연결 점검 테스트 (Requirement 8.2, 8.3).

`GET /health`가 애플리케이션 가용 상태(`status:"ok"`)와 경량 ``SELECT 1``
기반의 DB 연결 여부(`db:"ok"|"down"`)를 반영하는지 관찰 가능한 동작으로
검증한다. down 경로는 `app.dependency_overrides[get_db]`로 `.execute()`가
예외를 던지는 세션을 주입해 결정적으로 재현한다(실제 MySQL을 멈추지 않는다).
"""

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.common.db import get_db
from app.main import create_app


class _BrokenSession:
    """`.execute()`가 항상 실패하는 세션 스텁(DB 중단 상황 모사)."""

    def execute(self, *args: object, **kwargs: object) -> object:
        raise OperationalError("SELECT 1", {}, Exception("db down"))


def test_health_ok_when_db_reachable() -> None:
    """8.2, 8.3: DB 도달 가능 시 200 `{status:"ok", db:"ok"}`."""
    client = TestClient(create_app())

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_health_reports_db_down_without_raising() -> None:
    """8.3: DB 점검 실패 시에도 200을 유지하고 `db:"down"`을 반영한다."""
    app = create_app()

    def _broken_db() -> object:
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_db
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "down"}
