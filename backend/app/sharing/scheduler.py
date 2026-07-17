"""무효화 스윕 스케줄러 어댑터 — `ShareInvalidationScheduler`
(design.md §Components and Interfaces #ShareInvalidationScheduler, Feature/Runtime).

스윕 로직(`ShareInvalidationSweep`)·엔트리포인트(`run_invalidation_sweep`)와 분리된 인프로세스
스케줄링 어댑터다. `s01` `create_app()` lifespan 이 호출하는 `start(app)`/`stop()` 훅을
제공한다. `Settings.share_invalidation_sweep_interval_seconds` 가 `> 0` 이면 APScheduler
`BackgroundScheduler` 를 기동해 그 주기로 `run_invalidation_sweep` 를 등록하고, `<= 0` 이면
스케줄러를 기동하지 않는다(인프로세스 배치 비활성 = 외부 cron 사용 신호, Req 5.1·7.6).

경계(design.md §ShareInvalidationScheduler): 스케줄 실행·스케줄러 수명만 소유한다. 무효화 판정·
retire 는 서비스가, 세션 수명은 `run_invalidation_sweep` 엔트리포인트가 소유한다. 설정 접근은
`s01` 단일 Settings(`get_settings`) 경유이며 모듈별 설정 파일을 신설하지 않는다(Req 7.6).
APScheduler 는 `s10`/`s12` 가 이미 도입한 의존성을 재사용한다(신규 추가 없음). lifespan 배선은
별도 task 소관이며 이 모듈은 `app/main.py` 를 import 하지 않는다.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from app.config import get_settings
from app.sharing.invalidation import run_invalidation_sweep

__all__ = ["start", "stop"]

logger = logging.getLogger(__name__)

_JOB_ID = "share-invalidation-sweep"

# 기동된 스케줄러 인스턴스를 담는 모듈 레벨 홀더. stop() 이 shutdown 하고, 중복 start 를
# 가드하는 단일 지점이다(None = 미기동).
_scheduler: BackgroundScheduler | None = None


def start(app: FastAPI) -> None:
    """`s01` lifespan startup 훅. interval > 0 이면 주기 무효화 스윕 스케줄러를 기동한다.

    `Settings.share_invalidation_sweep_interval_seconds` 를 단일 Settings(`get_settings`)로
    읽어 `> 0` 이면 `BackgroundScheduler` 에 그 주기로 `run_invalidation_sweep` interval job 을
    등록·기동하고, `<= 0` 이면 인프로세스 스케줄러를 기동하지 않는다(외부 cron 신호). 이미
    기동된 스케줄러가 있으면(중복 start) 새로 기동하지 않고 기존 것을 유지한다.
    """
    global _scheduler
    if _scheduler is not None:
        logger.info("무효화 스윕 스케줄러가 이미 기동되어 있어 중복 기동을 건너뛴다")
        return

    interval = get_settings().share_invalidation_sweep_interval_seconds
    if interval <= 0:
        logger.info(
            "무효화 스윕 인프로세스 스케줄러 비활성(interval=%s <= 0, 외부 cron 신호)",
            interval,
        )
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_invalidation_sweep, "interval", seconds=interval, id=_JOB_ID
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("무효화 스윕 스케줄러 기동(interval=%s초, job=%s)", interval, _JOB_ID)


def stop() -> None:
    """`s01` lifespan shutdown 훅. 기동된 스케줄러가 있으면 종료한다(없으면 안전 no-op)."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("무효화 스윕 스케줄러 종료")
