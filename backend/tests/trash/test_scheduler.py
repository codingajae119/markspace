"""보관 스윕 스케줄러 어댑터 시작/종료 게이팅 테스트 (Task 3.2 / Req 4.1, 6.7).

design.md §Components and Interfaces #RetentionScheduler(Feature/Runtime) 계약을
검증한다:
- `trash_sweep_interval_seconds > 0` 이면 `start(app)` 이 인프로세스
  `BackgroundScheduler` 를 기동하고 interval job 을 등록한다.
- `<= 0` 이면 스케줄러를 기동하지 않는다(외부 cron 사용 신호). `stop()` 은 아무것도
  기동되지 않았을 때 안전한 no-op 이다.
- 설정 접근은 단일 Settings 경유(`get_settings`, Req 6.7).

이 테스트는 배선(기동/미기동)만 검증하며 실제 스윕 실행을 유발하지 않는다: interval 을
크게 두고 `stop()` 을 즉시 호출해 BackgroundScheduler 스레드가 새지 않도록 한다.
"""

import types

import pytest
from fastapi import FastAPI

import app.trash.scheduler as scheduler_mod
from app.trash.scheduler import start, stop


def _settings_with(interval):
    """`trash_sweep_interval_seconds` 만 갖는 settings 대역을 만든다(단일 Settings 경유)."""
    return types.SimpleNamespace(trash_sweep_interval_seconds=interval)


@pytest.fixture
def app_stub():
    """lifespan 훅 서명(`start(app)`)을 만족시키는 FastAPI 인스턴스."""
    return FastAPI()


@pytest.fixture(autouse=True)
def _ensure_stopped():
    """어떤 테스트가 스케줄러를 기동해도 종료를 보증해 스레드 누수를 막는다."""
    yield
    stop()


def test_start_boots_scheduler_when_interval_positive(app_stub, monkeypatch):
    """interval > 0 이면 스케줄러가 기동되고 스윕 interval job 이 등록된다(Req 4.1)."""
    monkeypatch.setattr(
        scheduler_mod, "get_settings", lambda: _settings_with(3600)
    )

    start(app_stub)

    assert scheduler_mod._scheduler is not None, "interval>0 이면 스케줄러가 기동되어야 한다"
    assert scheduler_mod._scheduler.running, "기동된 스케줄러는 running 이어야 한다"
    assert (
        scheduler_mod._scheduler.get_job(scheduler_mod._JOB_ID) is not None
    ), "주기 스윕 job 이 등록되어야 한다"

    stop()

    assert scheduler_mod._scheduler is None, "stop() 후 스케줄러 홀더는 비워져야 한다"


def test_start_disabled_when_interval_zero(app_stub, monkeypatch):
    """interval <= 0(=0) 이면 스케줄러를 기동하지 않는다(외부 cron 신호, Req 6.7)."""
    monkeypatch.setattr(
        scheduler_mod, "get_settings", lambda: _settings_with(0)
    )

    start(app_stub)

    assert scheduler_mod._scheduler is None, "interval=0 이면 스케줄러가 기동되면 안 된다"


def test_start_disabled_when_interval_negative(app_stub, monkeypatch):
    """음수 interval 도 비활성 계약을 따른다(<=0, Req 6.7)."""
    monkeypatch.setattr(
        scheduler_mod, "get_settings", lambda: _settings_with(-1)
    )

    start(app_stub)

    assert scheduler_mod._scheduler is None, "interval<0 이면 스케줄러가 기동되면 안 된다"


def test_stop_without_start_is_safe_noop(app_stub, monkeypatch):
    """아무것도 기동되지 않았을 때 stop() 은 안전한 no-op 이다."""
    assert scheduler_mod._scheduler is None

    stop()  # 예외 없이 통과해야 한다

    assert scheduler_mod._scheduler is None


def test_double_start_does_not_boot_second_scheduler(app_stub, monkeypatch):
    """중복 start 는 두 번째 스케줄러를 기동하지 않는다(홀더 가드)."""
    monkeypatch.setattr(
        scheduler_mod, "get_settings", lambda: _settings_with(3600)
    )

    start(app_stub)
    first = scheduler_mod._scheduler
    start(app_stub)

    assert scheduler_mod._scheduler is first, "중복 start 는 기존 스케줄러를 유지해야 한다"

    stop()
