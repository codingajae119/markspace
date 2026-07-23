"""아카이브 스윕 스케줄러 어댑터·엔트리포인트 테스트 (Task 3.2 / Req 4.1, 5.1, 7.6).

design.md §Components and Interfaces #ArchivalScheduler(Feature/Runtime) 계약을 검증한다:
- `attachment_sweep_interval_seconds > 0` 이면 `start(app)` 이 인프로세스
  `BackgroundScheduler` 를 기동하고 interval job 을 등록한다.
- `<= 0` 이면 스케줄러를 기동하지 않는다(외부 cron 사용 신호). `stop()` 은 아무것도
  기동되지 않았을 때 안전한 no-op 이다. 중복 start 는 두 번째 스케줄러를 기동하지 않는다.
- 설정 접근은 단일 Settings 경유(`get_settings`, Req 7.6).
- 엔트리포인트 `run_archival_sweep()` 은 자기 세션(SessionLocal)을 열어 현재 시각(utcnow)
  기준 스윕을 1회 수행하고 commit 한 뒤 처리 건수를 반환한다(Req 4.1·5.1).

게이팅 테스트는 배선(기동/미기동)만 검증하며 실제 스윕 실행을 유발하지 않는다: interval 을
크게 두고 `stop()` 을 즉시 호출해 BackgroundScheduler 스레드가 새지 않도록 한다.
엔트리포인트 테스트는 test_archival.py 의 확립된 테스트 DB + tmp 저장소 패턴을 재사용한다.
"""

import os
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.attachment.scheduler as scheduler_mod
import app.attachment.storage as storage_mod
import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.attachment.scheduler import start, stop
from app.common.db import Base
from app.models import Attachment, Document, User, Workspace

TEST_DB_NAME = "markspace_test"


# ======================================================================
# 스케줄러 시작/종료 게이팅 (Req 4.1·7.6) — trash/scheduler 테스트 미러
# ======================================================================


def _settings_with(interval):
    """`attachment_sweep_interval_seconds` 만 갖는 settings 대역(단일 Settings 경유)."""
    return types.SimpleNamespace(attachment_sweep_interval_seconds=interval)


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
# run_archival_sweep 엔트리포인트 (Req 4.1·5.1) — trash run_sweep 테스트 미러
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


def _make_workspace(session, *, name="ws"):
    """Workspace 행을 삽입하고 flush 한다(attachment/document FK 충족용)."""
    ws = Workspace(
        name=name,
        is_shareable=False,
        trash_retention_days=30,
        created_at=datetime.utcnow(),
    )
    session.add(ws)
    session.flush()
    return ws


def _make_document(session, *, workspace_id, created_by, status="active"):
    """Document 행을 직접 삽입하고 flush 한다(스코프 시드용)."""
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


def _make_attachment(session, *, workspace_id, document_id, file_path):
    """미보관 image Attachment 행을 직접 삽입하고 flush 한다(8.6 스코프 시드용)."""
    att = Attachment(
        workspace_id=workspace_id,
        document_id=document_id,
        file_path=file_path,
        original_name="orig.png",
        kind="image",
        is_archived=False,
        created_at=datetime(2026, 7, 17, 9, 0, 0),
    )
    session.add(att)
    session.flush()
    return att


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


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """저장/보관 루트를 tmp_path 하위로 격리한 settings 대역을 storage 모듈에 주입한다.

    AttachmentStorage 는 `app.attachment.storage.get_settings` 로 저장/보관 루트를 해석하므로,
    그 모듈의 get_settings 를 tmp 루트를 가리키는 namespace 로 대체해 실제 config.yml 루트에
    의존하지 않고 보관 이동을 관찰한다.
    """
    storage_root = tmp_path / "storage"
    archive_root = tmp_path / "archive"
    settings = types.SimpleNamespace(
        file_storage_root=str(storage_root),
        attachment_archive_root=str(archive_root),
    )
    monkeypatch.setattr(storage_mod, "get_settings", lambda: settings)
    return storage_root, archive_root


def _save_file(storage_root: Path, file_path: str, data: bytes) -> Path:
    """저장 루트 하위의 상대 경로에 실제 파일을 기록하고 그 절대 경로를 반환한다(시드용)."""
    dest = storage_root / file_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def test_run_archival_sweep_entrypoint_archives_with_own_session(
    sessionmaker_factory, roots, monkeypatch
):
    """`run_archival_sweep()` 엔트리포인트는 자기 세션(SessionLocal)을 열어 현재 시각(utcnow)
    기준 스윕을 1회 수행하고 commit 한 뒤 처리 건수를 반환한다(design.md §ArchivalScheduler,
    Req 4.1·5.1). 테스트·수동/외부 cron 실행 경로를 검증한다.

    run_archival_sweep 은 모듈 레벨 `app.common.db.SessionLocal` 로 자기 세션을 여므로,
    테스트 DB 로 향하도록 그 세션 팩토리를 테스트 세션 팩토리로 재바인딩한다(격리 전제).
    deleted 문서의 미보관 첨부(8.6 스코프)를 실제 파일과 함께 시드해 엔트리포인트가 실제
    스윕을 자기 세션으로 수행함을 관찰한다.
    """
    import app.common.db as db_module

    storage_root, archive_root = roots
    data = b"\x89PNG\r\n\x1a\n-entrypoint-archive"

    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        deleted_doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        rel_path = f"{ws.id}/{uuid4().hex}.png"
        att = _make_attachment(
            seed,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            file_path=rel_path,
        )
        seed.commit()
        att_id = att.id
        ws_id = ws.id
    finally:
        seed.close()

    # 실제 저장 파일을 저장 루트에 기록(이동 관찰용).
    storage_file = _save_file(storage_root, rel_path, data)
    assert storage_file.is_file()

    from app.attachment.archival import run_archival_sweep

    # run_archival_sweep 이 자기 세션을 여는 모듈 레벨 팩토리를 테스트 DB 로 재바인딩한다.
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker_factory)

    archived = run_archival_sweep()

    assert archived >= 1, "deleted 문서 첨부가 있으면 엔트리포인트는 처리 건수(>=1)를 반환한다"

    # 새 세션 재조회로 영속화(commit)를 확인(캐시 아님).
    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is True, (
            "엔트리포인트의 자기 세션 스윕으로 첨부가 보관(is_archived=true)되어야 한다"
        )
        assert row.file_path == f"{ws_id}/{Path(rel_path).name}"
    finally:
        verify.close()

    # 파일은 물리 삭제 없이 보관 위치로 이동됨(INV-4).
    archived_file = archive_root / f"{ws_id}/{Path(rel_path).name}"
    assert archived_file.is_file(), "보관 파일은 물리적으로 존재해야 한다(INV-4)"
    assert archived_file.read_bytes() == data
    assert not storage_file.exists(), "저장 위치의 파일은 보관 위치로 이동되어야 한다"
