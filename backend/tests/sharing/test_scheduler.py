"""무효화 스윕 스케줄러 어댑터·엔트리포인트 테스트 (Task 3.2 / Req 5.1, 7.6).

design.md §Components and Interfaces #ShareInvalidationScheduler(Feature/Runtime) 계약을 검증한다:
- `share_invalidation_sweep_interval_seconds > 0` 이면 `start(app)` 이 인프로세스
  `BackgroundScheduler` 를 기동하고 interval job 을 등록한다.
- `<= 0` 이면 스케줄러를 기동하지 않는다(외부 cron 사용 신호). `stop()` 은 아무것도
  기동되지 않았을 때 안전한 no-op 이다. 중복 start 는 두 번째 스케줄러를 기동하지 않는다.
- 설정 접근은 단일 Settings 경유(`get_settings`, Req 7.6).
- 엔트리포인트 `run_invalidation_sweep()` 은 자기 세션(SessionLocal)을 열어 무효화 스윕을
  1회 수행하고 commit 한 뒤 retire 건수를 반환한다(Req 5.1).

게이팅 테스트는 배선(기동/미기동)만 검증하며 실제 스윕 실행을 유발하지 않는다: interval 을
크게 두고 `stop()` 을 즉시 호출해 BackgroundScheduler 스레드가 새지 않도록 한다.
엔트리포인트 테스트는 test_invalidation.py 의 확립된 테스트 DB 패턴을 재사용한다.
"""

import os
import types
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
import app.sharing.scheduler as scheduler_mod
from app.common.db import Base
from app.models import Document, ShareLink, User, Workspace
from app.sharing.scheduler import start, stop

TEST_DB_NAME = "notion_lite_test"


# ======================================================================
# 스케줄러 시작/종료 게이팅 (Req 5.1·7.6) — attachment/scheduler 테스트 미러
# ======================================================================


def _settings_with(interval):
    """`share_invalidation_sweep_interval_seconds` 만 갖는 settings 대역(단일 Settings 경유)."""
    return types.SimpleNamespace(share_invalidation_sweep_interval_seconds=interval)


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
    """interval > 0 이면 스케줄러가 기동되고 스윕 interval job 이 등록된다(Req 5.1)."""
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
    """interval <= 0(=0) 이면 스케줄러를 기동하지 않는다(외부 cron 신호, Req 7.6)."""
    monkeypatch.setattr(
        scheduler_mod, "get_settings", lambda: _settings_with(0)
    )

    start(app_stub)

    assert scheduler_mod._scheduler is None, "interval=0 이면 스케줄러가 기동되면 안 된다"


def test_start_disabled_when_interval_negative(app_stub, monkeypatch):
    """음수 interval 도 비활성 계약을 따른다(<=0, Req 7.6)."""
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


# ======================================================================
# run_invalidation_sweep 엔트리포인트 (Req 5.1) — test_invalidation 미러
# ======================================================================


def _drop_everything(engine) -> None:
    """대상 DB 의 모든 테이블을 FK 무시하고 제거해 빈 상태로 만든다(견고한 teardown)."""
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        names = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ]
        for name in names:
            conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def _make_user(session, *, login_id):
    """테스트 DB 에 User 를 삽입하고 flush 하여 id 를 확정한다(FK 충족용)."""
    user = User(
        login_id=login_id,
        password_hash="hash-initial",
        name="테스트 사용자",
        email=None,
        is_admin=False,
        is_active=True,
        is_deleted=False,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def _make_workspace(session, *, name="ws", is_shareable=True):
    """Workspace 행을 삽입하고 flush 한다(게이트 관측 스코프 시드용, 기본 게이트 on)."""
    ws = Workspace(
        name=name,
        is_shareable=is_shareable,
        trash_retention_days=30,
        created_at=datetime.utcnow(),
    )
    session.add(ws)
    session.flush()
    return ws


def _make_document(session, *, workspace_id, created_by, status="active"):
    """Document 행을 직접 삽입하고 flush 한다(링크·스코프 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=None,
        title="문서",
        status=status,
        sort_order=Decimal("1000"),
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


def _make_share_link(session, *, document_id, token=None, is_enabled=True):
    """ShareLink 행을 직접 삽입하고 flush 한다(스코프 시드용)."""
    link = ShareLink(
        document_id=document_id,
        token=token or uuid4().hex,
        is_enabled=is_enabled,
        created_at=datetime(2026, 7, 17, 9, 0, 0),
    )
    session.add(link)
    session.flush()
    return link


@pytest.fixture
def sessionmaker_factory():
    """테스트 DB 를 마이그레이션하고 세션 팩토리를 제공한다(격리·원복 보증)."""
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    TestSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    _drop_everything(engine)  # 시작 전 빈 상태 보증(격리 전제).
    Base.metadata.create_all(engine)  # 마이그레이션된 DB 계약을 물리적으로 생성.

    try:
        yield TestSessionLocal
    finally:
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


def test_run_invalidation_sweep_entrypoint_retires_with_own_session(
    sessionmaker_factory, monkeypatch
):
    """`run_invalidation_sweep()` 엔트리포인트는 자기 세션(SessionLocal)을 열어 무효화 스윕을
    1회 수행하고 commit 한 뒤 retire 건수를 반환한다(design.md §ShareInvalidationScheduler,
    Req 5.1). 테스트·수동/외부 cron 실행 경로를 검증한다.

    run_invalidation_sweep 은 모듈 레벨 `app.common.db.SessionLocal` 로 자기 세션을 여므로,
    테스트 DB 로 향하도록 그 세션 팩토리를 테스트 세션 팩토리로 재바인딩한다(격리 전제).
    trashed 문서에 걸린 활성 링크(무효화 스코프)를 시드해 엔트리포인트가 실제 스윕을 자기
    세션으로 수행함을 관찰한다.
    """
    import app.common.db as db_module

    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}", is_shareable=True)
        trashed_doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, status="trashed"
        )
        link = _make_share_link(
            seed, document_id=trashed_doc.id, token=f"t-{uuid4().hex}"
        )
        seed.commit()
        link_id = link.id
        old_token = link.token
    finally:
        seed.close()

    from app.sharing.invalidation import run_invalidation_sweep

    # run_invalidation_sweep 이 자기 세션을 여는 모듈 레벨 팩토리를 테스트 DB 로 재바인딩한다.
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker_factory)

    retired = run_invalidation_sweep()

    assert isinstance(retired, int), "엔트리포인트는 retire 건수(int)를 반환한다"
    assert retired >= 1, "무효 활성 링크가 있으면 엔트리포인트는 retire 건수(>=1)를 반환한다"

    # 새 세션 재조회로 영속화(commit)를 확인(캐시 아님).
    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row is not None, "retire 는 물리 삭제하지 않는다(행 유지, INV-4)"
        assert row.is_enabled is False, (
            "엔트리포인트의 자기 세션 스윕으로 링크가 retire(비활성)되어야 한다"
        )
        assert row.token != old_token, (
            "retire 는 토큰을 교체해 이전 토큰을 영구 무효화한다(INV-8)"
        )
    finally:
        verify.close()
