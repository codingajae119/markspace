"""RetentionSweepService 통합 테스트 (Task 2.3 / Req 4.1~4.7, 6.1).

design.md §Components and Interfaces #RetentionSweepService(Feature/Service)와
§System Flows "보관 만료 자동 영구삭제 스윕(6.8, INV-12)" 계약을 실제 DB·실제 s07
엔진으로 검증한다:
- 주입된 `now` 에 대해 `trashed_at + retention_days <= now` 묶음만 엔진 `purge_bundle`
  로 deleted 전환하고, 아직 보관 기간이 남은 묶음은 그대로 둔다(Req 4.1·4.4).
- 각 묶음 만료는 그 묶음의 `trashed_at` 기준 독립 산정이며, 서로 다른 trashed_at 을
  가진 자식/부모 묶음은 각자 만료된다 — 한 묶음 만료가 다른 묶음 기준을 바꾸지 않는다
  (Req 4.2·4.5, INV-12).
- 워크스페이스별 `trash_retention_days` 로 만료를 판정한다(교차 워크스페이스, Req 4.1).
- 이미 deleted/복구된 묶음은 오류 없이 건너뛰고, 반복 실행은 중복 전이·오류를 일으키지
  않는다(멱등, Req 4.6·4.7).
- 반환값은 실제 완전삭제된 묶음 수다.

격리: tests/trash/test_service.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME` 을
전용 테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운
뒤 그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을
dispose 한 뒤 환경변수·캐시를 원복한다. 공유 테스트 DB 충돌을 피하려 이름/제목에 uuid4
접미사를 쓴다. `trashed_at` 은 DATETIME(0) 반올림을 피하려 초 단위(마이크로초 0) 고정값
으로 핀 고정한다(테스트 시드 조작이며 서비스는 trashed_at 을 쓰지 않는다).
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.document.engine import DocumentStateEngine
from app.document.repository import DocumentRepository
from app.models import Document, User, Workspace
from app.trash.repository import TrashRepository
from app.trash.retention import RetentionSweepService

TEST_DB_NAME = "notion_lite_test"


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


def _make_workspace(session, *, name="ws", trash_retention_days=30):
    """Workspace 행을 삽입하고 flush 한다(retention 조회·document FK 충족용)."""
    ws = Workspace(
        name=name,
        is_shareable=False,
        trash_retention_days=trash_retention_days,
        created_at=datetime.utcnow(),
    )
    session.add(ws)
    session.flush()
    return ws


def _make_document(
    session,
    *,
    workspace_id,
    created_by,
    parent_id=None,
    title="문서",
    status="active",
    sort_order=Decimal("1000"),
):
    """active Document 행을 삽입하고 flush 한다(엔진 삭제 대상 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        trashed_at=None,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


def _pin_trashed_at(session, members, ts):
    """묶음 구성원 전체의 `trashed_at` 을 결정적 초단위 값으로 핀 고정한다.

    엔진 `trash_document` 는 `utcnow()` 로 공통 trashed_at 을 부여하므로 만료 경계를
    결정적으로 검증하려면 그 값을 고정값으로 덮어쓴다. 묶음은 동일 trashed_at 연결로
    재구성되므로 구성원 전체에 같은 값을 부여해 묶음 경계를 유지한다. DATETIME(0)
    반올림을 피하려 마이크로초 0 값을 쓴다. (테스트 시드 조작이며 스윕 서비스는
    trashed_at 을 쓰지 않는다.)
    """
    for m in members:
        m.trashed_at = ts
    session.commit()


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


def _sweep() -> RetentionSweepService:
    """실제 s07 엔진(+DocumentRepository)과 TrashRepository 로 스윕 서비스를 조립한다."""
    engine = DocumentStateEngine(DocumentRepository())
    return RetentionSweepService(engine=engine, repository=TrashRepository())


def _status_of(session_factory, doc_id):
    """새 세션으로 문서 상태를 읽어 반환한다(전이 결과의 신선한 관찰)."""
    verify = session_factory()
    try:
        return verify.query(Document).filter(Document.id == doc_id).one().status
    finally:
        verify.close()


# --- 만료 경계: 만료 묶음만 전환, 미만료 유지 -----------------------------


def test_sweep_purges_expired_and_keeps_unexpired(sessionmaker_factory):
    """`trashed_at + retention_days <= now` 묶음만 deleted 로 전환하고 미만료는 유지한다
    (Req 4.1·4.4). 경계(정확히 now 시점)는 `<=` 라 만료로 취급한다.

    retention=30 인 한 워크스페이스에 세 묶음을 만든다:
    - expired: trashed_at = now - 40일 → 만료 → 완전삭제
    - boundary: trashed_at = now - 30일(정확히 경계) → `<= now` 라 만료 → 완전삭제
    - fresh: trashed_at = now - 10일 → 미만료 → 유지
    반환값은 실제 완전삭제된 묶음 수(2)여야 한다.
    """
    retention = 30
    now = datetime(2026, 7, 17, 0, 0, 0)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=retention
        )
        expired_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"exp-{uuid4().hex}", sort_order=Decimal("1000"),
        )
        boundary_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"bnd-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        fresh_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"fresh-{uuid4().hex}", sort_order=Decimal("3000"),
        )
        seed.commit()

        b_exp = engine.trash_document(seed, expired_root)
        _pin_trashed_at(seed, b_exp.members, now - timedelta(days=40))
        b_bnd = engine.trash_document(seed, boundary_root)
        _pin_trashed_at(seed, b_bnd.members, now - timedelta(days=retention))
        b_fresh = engine.trash_document(seed, fresh_root)
        _pin_trashed_at(seed, b_fresh.members, now - timedelta(days=10))

        expired_id, boundary_id, fresh_id = (
            expired_root.id, boundary_root.id, fresh_root.id
        )
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        purged = _sweep().sweep_expired_bundles(session, now)
    finally:
        session.close()

    assert purged == 2, "만료·경계 묶음 2개만 완전삭제되어야 한다(반환값 정합)"
    assert _status_of(sessionmaker_factory, expired_id) == "deleted"
    assert _status_of(sessionmaker_factory, boundary_id) == "deleted", (
        "정확히 경계(now)인 묶음은 `<=` 로 만료 처리되어야 한다"
    )
    assert _status_of(sessionmaker_factory, fresh_id) == "trashed", (
        "보관 기간이 남은 묶음은 유지되어야 한다"
    )


# --- 묶음별 독립 타이머(자식/부모 서로 다른 trashed_at) ------------------


def test_sweep_independent_per_bundle_timer(sessionmaker_factory):
    """서로 다른 trashed_at 을 가진 자식/부모 묶음이 각자의 만료 시점에 독립 전환된다
    (Req 4.2·4.5, INV-12). 한 묶음의 만료가 다른 묶음 기준을 끌고 가지 않는다.

    자식을 먼저 삭제해 자식 단독 묶음(오래됨, 만료)을 만들고, 이후 부모를 삭제해 부모
    단독 묶음(최근, 미만료)을 만든다(비흡수). 스윕은 만료된 자식 묶음만 완전삭제하고
    미만료 부모 묶음은 trashed 로 유지해야 한다.
    """
    retention = 30
    now = datetime(2026, 7, 17, 0, 0, 0)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=retention
        )
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"P-{uuid4().hex}", sort_order=Decimal("1000"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title=f"C-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()

        # 자식 단독 삭제(오래된 만료 묶음).
        b_child = engine.trash_document(seed, child)
        _pin_trashed_at(seed, b_child.members, now - timedelta(days=40))
        # 부모 삭제(최근·미만료). 이미 trashed 된 자식은 흡수되지 않는다(비흡수).
        b_parent = engine.trash_document(seed, parent)
        _pin_trashed_at(seed, b_parent.members, now - timedelta(days=5))

        parent_id, child_id = parent.id, child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        purged = _sweep().sweep_expired_bundles(session, now)
    finally:
        session.close()

    assert purged == 1, "만료된 자식 묶음 1개만 완전삭제되어야 한다"
    assert _status_of(sessionmaker_factory, child_id) == "deleted", (
        "오래된 자식 묶음은 자기 trashed_at 기준으로 만료되어야 한다"
    )
    assert _status_of(sessionmaker_factory, parent_id) == "trashed", (
        "미만료 부모 묶음은 자식 만료에 끌려가지 않고 유지되어야 한다(INV-12)"
    )


# --- 교차 워크스페이스: 각 WS 의 retention 으로 독립 판정 -----------------


def test_sweep_judges_each_workspace_by_its_retention(sessionmaker_factory):
    """각 워크스페이스의 trash_retention_days 로 만료를 독립 판정한다(Req 4.1).

    WS-A retention=7 · 묶음 trashed_at = now-10일 → 만료 → 완전삭제.
    WS-B retention=30 · 묶음 trashed_at = now-10일 → 미만료 → 유지.
    동일한 삭제 경과(10일)라도 워크스페이스별 보관일에 따라 결과가 갈린다.
    """
    now = datetime(2026, 7, 17, 0, 0, 0)
    ts = now - timedelta(days=10)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws_a = _make_workspace(
            seed, name=f"wsA-{uuid4().hex}", trash_retention_days=7
        )
        ws_b = _make_workspace(
            seed, name=f"wsB-{uuid4().hex}", trash_retention_days=30
        )
        root_a = _make_document(
            seed, workspace_id=ws_a.id, created_by=user.id,
            title=f"A-{uuid4().hex}",
        )
        root_b = _make_document(
            seed, workspace_id=ws_b.id, created_by=user.id,
            title=f"B-{uuid4().hex}",
        )
        seed.commit()

        b_a = engine.trash_document(seed, root_a)
        _pin_trashed_at(seed, b_a.members, ts)
        b_b = engine.trash_document(seed, root_b)
        _pin_trashed_at(seed, b_b.members, ts)

        root_a_id, root_b_id = root_a.id, root_b.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        purged = _sweep().sweep_expired_bundles(session, now)
    finally:
        session.close()

    assert purged == 1, "보관일이 짧은 WS-A 묶음만 완전삭제되어야 한다"
    assert _status_of(sessionmaker_factory, root_a_id) == "deleted", (
        "retention=7 인 WS-A 의 10일 경과 묶음은 만료되어야 한다"
    )
    assert _status_of(sessionmaker_factory, root_b_id) == "trashed", (
        "retention=30 인 WS-B 의 10일 경과 묶음은 유지되어야 한다"
    )


# --- 멱등: 반복 실행이 중복 전이·오류를 일으키지 않음 ---------------------


def test_sweep_is_idempotent_on_repeat(sessionmaker_factory):
    """같은 now 로 반복 실행해도 만료 묶음은 한 번만 전환되고 재실행은 no-op 이다
    (Req 4.6·4.7). 두 번째 실행은 오류 없이 0 을 반환하고 상태를 재전이하지 않는다.
    """
    retention = 30
    now = datetime(2026, 7, 17, 0, 0, 0)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=retention
        )
        expired_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"exp-{uuid4().hex}", sort_order=Decimal("1000"),
        )
        fresh_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"fresh-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()

        b_exp = engine.trash_document(seed, expired_root)
        _pin_trashed_at(seed, b_exp.members, now - timedelta(days=40))
        b_fresh = engine.trash_document(seed, fresh_root)
        _pin_trashed_at(seed, b_fresh.members, now - timedelta(days=1))

        expired_id, fresh_id = expired_root.id, fresh_root.id
    finally:
        seed.close()

    svc = _sweep()

    first = sessionmaker_factory()
    try:
        purged_1 = svc.sweep_expired_bundles(first, now)
    finally:
        first.close()

    second = sessionmaker_factory()
    try:
        purged_2 = svc.sweep_expired_bundles(second, now)
    finally:
        second.close()

    assert purged_1 == 1, "첫 실행은 만료 묶음 1개를 완전삭제한다"
    assert purged_2 == 0, "두 번째 실행은 재전이 없이 no-op(0) 이어야 한다"
    assert _status_of(sessionmaker_factory, expired_id) == "deleted", (
        "만료 묶음은 deleted 종착으로 유지(중복 전이 없음)"
    )
    assert _status_of(sessionmaker_factory, fresh_id) == "trashed", (
        "미만료 묶음은 반복 실행에도 유지되어야 한다"
    )


def test_sweep_skips_already_deleted_bundle_without_error(sessionmaker_factory):
    """이미 완전삭제(deleted)된 묶음은 오류 없이 건너뛴다(Req 4.6).

    만료 대상 묶음을 스윕 전에 엔진 `purge_bundle` 로 미리 deleted 로 만들면, 그 묶음은
    `identify_bundles`(trashed 만 열거)에 없으므로 스윕은 오류 없이 0 을 반환한다.
    """
    retention = 30
    now = datetime(2026, 7, 17, 0, 0, 0)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=retention
        )
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"R-{uuid4().hex}",
        )
        seed.commit()

        b = engine.trash_document(seed, root)
        _pin_trashed_at(seed, b.members, now - timedelta(days=40))
        # 스윕 전에 미리 완전삭제(경쟁적 선처리 상황 모사).
        engine.purge_bundle(seed, root.id)
        root_id = root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        purged = _sweep().sweep_expired_bundles(session, now)
    finally:
        session.close()

    assert purged == 0, "이미 deleted 인 묶음은 열거되지 않아 스윕이 건너뛴다"
    assert _status_of(sessionmaker_factory, root_id) == "deleted", (
        "선처리된 묶음 상태는 스윕에 영향받지 않고 그대로 유지"
    )


def test_sweep_empty_scope_returns_zero(sessionmaker_factory):
    """trashed 문서가 없으면 스윕 스코프가 비어 0 을 반환한다(Req 4.3·4.4)."""
    now = datetime(2026, 7, 17, 0, 0, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"active-{uuid4().hex}",
        )
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        purged = _sweep().sweep_expired_bundles(session, now)
    finally:
        session.close()

    assert purged == 0, "trashed 묶음이 없으면 스윕은 no-op(0) 이다"


# --- 예외 격리: 한 묶음 실패가 전체 스윕을 중단시키지 않음 ----------------


def test_sweep_isolates_per_bundle_exception(sessionmaker_factory, caplog):
    """한 묶음의 purge 예외가 격리되어 나머지 만료 묶음은 계속 처리된다(Req 4.6·4.7).

    엔진을 감싸 첫 만료 묶음의 `purge_bundle` 에서만 예외를 던지게 하면, 스윕은 그 실패를
    로그로 남기고 계속 진행해 나머지 만료 묶음을 완전삭제해야 한다. 실패한 묶음은 그대로
    trashed 로 남는다.
    """
    import logging

    retention = 30
    now = datetime(2026, 7, 17, 0, 0, 0)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=retention
        )
        boom_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"boom-{uuid4().hex}", sort_order=Decimal("1000"),
        )
        ok_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"ok-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()

        b_boom = engine.trash_document(seed, boom_root)
        _pin_trashed_at(seed, b_boom.members, now - timedelta(days=40))
        b_ok = engine.trash_document(seed, ok_root)
        _pin_trashed_at(seed, b_ok.members, now - timedelta(days=40))

        boom_id, ok_id = boom_root.id, ok_root.id
    finally:
        seed.close()

    real_engine = DocumentStateEngine(DocumentRepository())

    class _FlakyEngine:
        """첫 대상 묶음 purge 만 실패시키는 엔진 래퍼(예외 격리 검증용)."""

        def identify_bundles(self, db, workspace_id):
            return real_engine.identify_bundles(db, workspace_id)

        def purge_bundle(self, db, root_document_id):
            if root_document_id == boom_id:
                raise RuntimeError("simulated purge failure")
            return real_engine.purge_bundle(db, root_document_id)

    svc = RetentionSweepService(engine=_FlakyEngine(), repository=TrashRepository())

    # 앞선 스위트(L1/L3 하네스)가 alembic env.py 의 fileConfig(기본
    # disable_existing_loggers=True)를 태우면 import 시점에 만들어진
    # `app.trash.retention` 로거가 disabled 되어 caplog 이 레코드를 잡지 못한다(순서
    # 의존 플레이크). 캡처 직전에 해당 로거를 명시적으로 재활성화하고 at_level 을 그
    # 로거로 스코프해 실행 순서와 무관하게 결정적으로 관측한다.
    retention_logger = logging.getLogger("app.trash.retention")
    retention_logger.disabled = False
    retention_logger.propagate = True

    session = sessionmaker_factory()
    try:
        with caplog.at_level(logging.ERROR, logger="app.trash.retention"):
            purged = svc.sweep_expired_bundles(session, now)
    finally:
        session.close()

    assert purged == 1, "실패 묶음을 건너뛰고 나머지 만료 묶음은 완전삭제되어야 한다"
    assert _status_of(sessionmaker_factory, ok_id) == "deleted", (
        "정상 묶음은 다른 묶음 실패와 무관하게 처리되어야 한다"
    )
    assert _status_of(sessionmaker_factory, boom_id) == "trashed", (
        "purge 가 실패한 묶음은 전이되지 않고 trashed 로 남는다"
    )
    assert caplog.records, "격리된 예외는 조용히 삼키지 않고 로그로 남겨야 한다"


# --- run_sweep 엔트리포인트: 자기 세션으로 스윕 1회 수행(Task 3.2 / Req 4.1) ---


def test_run_sweep_entrypoint_purges_expired_with_own_session(
    sessionmaker_factory, monkeypatch
):
    """`run_sweep()` 엔트리포인트는 자기 세션(SessionLocal)을 열어 현재 시각(utcnow)
    기준 스윕을 1회 수행하고 처리한 묶음 수를 반환한다(design.md §RetentionScheduler,
    Req 4.1). 테스트·수동/외부 cron 실행 경로를 검증한다.

    run_sweep 은 모듈 레벨 `app.common.db.SessionLocal` 로 자기 세션을 여므로, 테스트
    DB 로 향하도록 그 세션 팩토리를 테스트 세션 팩토리로 재바인딩한다(격리 전제). now 를
    주입받지 않고 내부에서 utcnow 를 산정하므로, 만료 묶음은 `retention_days + 1일` 이전,
    미만료 묶음은 최근으로 trashed_at 을 핀 고정해 결정적으로 검증한다.
    """
    import app.common.db as db_module

    retention = 30
    # run_sweep 은 실제 utcnow 를 쓰므로 그 시점 기준으로 trashed_at 을 고정한다.
    real_now = datetime.utcnow().replace(microsecond=0)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=retention
        )
        expired_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"exp-{uuid4().hex}", sort_order=Decimal("1000"),
        )
        fresh_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"fresh-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()

        b_exp = engine.trash_document(seed, expired_root)
        _pin_trashed_at(
            seed, b_exp.members, real_now - timedelta(days=retention + 1)
        )
        b_fresh = engine.trash_document(seed, fresh_root)
        _pin_trashed_at(seed, b_fresh.members, real_now - timedelta(days=1))

        expired_id, fresh_id = expired_root.id, fresh_root.id
    finally:
        seed.close()

    from app.trash.retention import run_sweep

    # run_sweep 이 자기 세션을 여는 모듈 레벨 팩토리를 테스트 DB 로 재바인딩한다.
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker_factory)

    purged = run_sweep()

    assert purged >= 1, "만료 묶음이 있으면 run_sweep 은 처리 묶음 수(>=1)를 반환한다"
    assert _status_of(sessionmaker_factory, expired_id) == "deleted", (
        "만료 묶음은 run_sweep 의 자기 세션 스윕으로 deleted 전환되어야 한다"
    )
    assert _status_of(sessionmaker_factory, fresh_id) == "trashed", (
        "미만료 묶음은 run_sweep 에 영향받지 않고 trashed 로 유지되어야 한다"
    )
