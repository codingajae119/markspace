"""TrashService.list_trash 통합 테스트 (Task 2.1 / Req 1.1~1.6).

design.md §Components and Interfaces #TrashService(Feature/Service)와 §System Flows
"휴지통 목록 조회(행 29)" 계약을 실제 DB·실제 s07 엔진으로 검증한다:
- 엔진 `identify_bundles` 결과를 표시 스키마(`TrashBundleRead`)로 투영한다(무엇이
  묶음인지 재판정하지 않음, Req 1.2).
- 각 묶음의 `expires_at = trashed_at + workspace.trash_retention_days`(Req 1.4).
- 여러 시점에 삭제된 묶음이 별개로 열거되고(Req 1.1), trashed 묶음만 포함하며
  이미 deleted(완전삭제)된 묶음은 노출하지 않는다(Req 1.5).
- 목록은 s01 `Page` 규약을 따른다(Req 6.2). 본인 삭제분 외 전체 노출(Req 1.6,
  권한은 라우터 게이트).

격리: tests/trash/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`markspace_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를
비운 뒤 그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고
엔진을 dispose 한 뒤 환경변수·캐시를 원복한다. 공유 테스트 DB 충돌을 피하려 이름/제목에
uuid4 접미사를 쓴다. `trashed_at` 은 DATETIME(0) 반올림을 피하려 초 단위(마이크로초 0)
고정값으로 핀 고정한다.
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
from app.common.errors import DomainError
from app.document.engine import DocumentStateEngine
from app.document.repository import DocumentRepository
from app.models import Document, User, Workspace
from app.schemas.base import Page
from app.trash.repository import TrashRepository
from app.trash.schemas import TrashBundleRead
from app.trash.service import TrashService

TEST_DB_NAME = "markspace_test"


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

    엔진 `trash_document` 는 `utcnow()` 로 공통 trashed_at 을 부여하므로 만료 예정 시각을
    결정적으로 검증하려면 그 값을 고정값으로 덮어쓴다. 묶음은 동일 trashed_at 연결로
    재구성되므로 구성원 전체에 같은 값을 부여해 묶음 경계를 유지한다. DATETIME(0) 반올림을
    피하려 마이크로초 0 값을 쓴다. (테스트 시드 조작이며 서비스는 trashed_at 을 쓰지 않는다.)
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


def _service() -> TrashService:
    """실제 s07 엔진(+DocumentRepository)과 TrashRepository 로 서비스를 조립한다."""
    engine = DocumentStateEngine(DocumentRepository())
    return TrashService(engine=engine, repository=TrashRepository())


# --- list_trash: 다중 묶음 열거 + 만료 예정 산정 --------------------------


def test_list_trash_enumerates_bundles_with_independent_expiry(
    sessionmaker_factory,
):
    """서로 다른 시점에 삭제된 묶음이 별개로 열거되고 각자의 만료 예정을 갖는다
    (Req 1.1·1.2·1.3·1.4·1.5, `Page` 규약 Req 6.2).

    묶음 A(루트+자식, 2 구성원)와 묶음 B(단일 루트)를 실제 엔진 `trash_document` 로
    만들고 각자 다른 trashed_at 으로 핀 고정한다. `list_trash` 는 두 묶음을 각각 한 번씩
    투영하고 `expires_at == trashed_at + 30일` 을 묶음별 독립 산정해야 한다.
    """
    retention = 30
    t_a = datetime(2026, 6, 1, 9, 0, 0)  # 묶음 A 삭제 시점(초 단위 고정)
    t_b = datetime(2026, 6, 15, 9, 0, 0)  # 묶음 B 삭제 시점(A 와 상이)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws-{uuid4().hex}", trash_retention_days=retention
        )
        root_a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"A-{uuid4().hex}",
        )
        child_a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root_a.id,
            title=f"A1-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        root_b = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"B-{uuid4().hex}", sort_order=Decimal("3000"),
        )
        seed.commit()

        bundle_a = engine.trash_document(seed, root_a)
        _pin_trashed_at(seed, bundle_a.members, t_a)
        bundle_b = engine.trash_document(seed, root_b)
        _pin_trashed_at(seed, bundle_b.members, t_b)

        ws_id = ws.id
        root_a_id, child_a_id, root_b_id = root_a.id, child_a.id, root_b.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        page = _service().list_trash(session, ws_id, limit=50, offset=0)
    finally:
        session.close()

    assert isinstance(page, Page)
    assert page.total == 2, "trashed 묶음 2개가 전체 개수로 집계되어야 한다"
    assert len(page.items) == 2
    assert all(isinstance(i, TrashBundleRead) for i in page.items)

    by_root = {i.root_document_id: i for i in page.items}
    assert set(by_root) == {root_a_id, root_b_id}, "묶음이 각각 한 번씩만 열거되어야 한다"

    a = by_root[root_a_id]
    assert a.bundle_id == root_a_id  # bundle_id == root_document_id
    assert a.trashed_at == t_a
    assert a.expires_at == t_a + timedelta(days=retention), "Req 1.4 만료 예정 산정"
    assert a.member_count == 2
    assert {m.id for m in a.members} == {root_a_id, child_a_id}

    b = by_root[root_b_id]
    assert b.trashed_at == t_b
    assert b.expires_at == t_b + timedelta(days=retention)
    assert b.member_count == 1

    assert a.trashed_at != b.trashed_at, "다른 시점 삭제 묶음은 별개 trashed_at 로 열거"
    assert a.expires_at != b.expires_at, "묶음별 만료 예정이 독립적으로 산정됨"


def test_list_trash_expiry_uses_workspace_retention_days(sessionmaker_factory):
    """만료 예정 시각은 그 워크스페이스의 trash_retention_days 를 더한 값이다(Req 1.4).

    보관일 7일 워크스페이스의 묶음은 `expires_at == trashed_at + 7일` 이어야 한다.
    """
    retention = 7
    t = datetime(2026, 6, 20, 12, 0, 0)

    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(
            seed, name=f"ws7-{uuid4().hex}", trash_retention_days=retention
        )
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"R-{uuid4().hex}",
        )
        seed.commit()
        bundle = engine.trash_document(seed, root)
        _pin_trashed_at(seed, bundle.members, t)
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        page = _service().list_trash(session, ws_id, limit=50, offset=0)
    finally:
        session.close()

    assert page.total == 1
    assert page.items[0].expires_at == t + timedelta(days=retention)


def test_list_trash_excludes_deleted_bundles(sessionmaker_factory):
    """휴지통 목록은 trashed 묶음만 포함하고 완전삭제(deleted)된 묶음은 노출하지 않는다
    (Req 1.5). 두 묶음 중 하나를 엔진 `purge_bundle` 로 deleted 전환하면 목록에서 사라진다.
    """
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        keep_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"keep-{uuid4().hex}",
        )
        purge_root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"purge-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()

        engine.trash_document(seed, keep_root)
        engine.trash_document(seed, purge_root)
        # 한 묶음을 즉시 완전삭제(deleted 종착 전이) → 목록에서 제외되어야 한다.
        engine.purge_bundle(seed, purge_root.id)

        ws_id = ws.id
        keep_id, purge_id = keep_root.id, purge_root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        page = _service().list_trash(session, ws_id, limit=50, offset=0)
    finally:
        session.close()

    root_ids = {i.root_document_id for i in page.items}
    assert keep_id in root_ids, "trashed 묶음은 목록에 남아야 한다"
    assert purge_id not in root_ids, "deleted(완전삭제) 묶음은 노출되지 않아야 한다(Req 1.5)"
    assert page.total == 1, "trashed 묶음만 집계되어야 한다"


def test_list_trash_paginates_over_full_total(sessionmaker_factory):
    """목록은 limit/offset 으로 슬라이스하되 total 은 전체 묶음 수를 유지한다(`Page` 규약).

    3개의 독립 묶음을 만들고 limit=2 로 페이지네이션하면 첫 페이지 2건·둘째 페이지 1건이며
    두 페이지 모두 total==3 이다. 페이지 간 루트 집합은 서로 겹치지 않고 합집합이 전체다.
    """
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        roots = []
        for i in range(3):
            root = _make_document(
                seed, workspace_id=ws.id, created_by=user.id,
                title=f"R{i}-{uuid4().hex}", sort_order=Decimal(1000 * (i + 1)),
            )
            roots.append(root)
        seed.commit()
        for root in roots:
            engine.trash_document(seed, root)
        ws_id = ws.id
        all_root_ids = {r.id for r in roots}
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        svc = _service()
        page1 = svc.list_trash(session, ws_id, limit=2, offset=0)
        page2 = svc.list_trash(session, ws_id, limit=2, offset=2)
    finally:
        session.close()

    assert page1.total == 3 and page2.total == 3, "total 은 슬라이스와 무관한 전체 수"
    assert len(page1.items) == 2
    assert len(page2.items) == 1
    seen = {i.root_document_id for i in page1.items} | {
        i.root_document_id for i in page2.items
    }
    assert seen == all_root_ids, "페이지들의 합집합이 전체 묶음이어야 한다"


def test_list_trash_empty_when_no_trashed(sessionmaker_factory):
    """trashed 묶음이 없으면 빈 `Page`(items=[], total=0)를 반환한다(Req 1.1·6.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        # active 문서만 존재 → 휴지통은 비어 있어야 한다.
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"active-{uuid4().hex}",
        )
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        page = _service().list_trash(session, ws_id, limit=50, offset=0)
    finally:
        session.close()

    assert isinstance(page, Page)
    assert page.items == []
    assert page.total == 0


# --- 순수 투영 단위 테스트(스텁 엔진) ------------------------------------


class _StubBundle:
    """s07 `Bundle` 대역 — 투영에 필요한 최소 속성만 제공한다."""

    def __init__(self, root_document_id, trashed_at, members):
        self.root_document_id = root_document_id
        self.trashed_at = trashed_at
        self.members = members


class _StubMember:
    def __init__(self, id, parent_id, title, workspace_id):
        self.id = id
        self.parent_id = parent_id
        self.title = title
        self.workspace_id = workspace_id


class _StubEngine:
    """`identify_bundles` 만 대역하는 엔진 스텁(순수 투영·만료 산정 검증용)."""

    def __init__(self, bundles):
        self._bundles = bundles

    def identify_bundles(self, db, workspace_id):
        return list(self._bundles)


class _StubRepo:
    """`get_retention_days` 만 대역하는 리포지토리 스텁."""

    def __init__(self, retention_days):
        self._retention = retention_days

    def get_retention_days(self, db, workspace_id):
        return self._retention


def test_list_trash_projection_pure_unit():
    """엔진/리포지토리 스텁으로 투영·만료 산정·`Page` 구성만 순수 검증한다(Req 1.3·1.4).

    실 DB 없이도 `list_trash` 가 `identify_bundles` 결과를 `TrashBundleRead` 로 투영하고
    `expires_at = trashed_at + retention_days` 를 산정함을 확인한다.
    """
    t = datetime(2026, 1, 10, 8, 0, 0)
    root = _StubMember(id=11, parent_id=None, title="루트", workspace_id=7)
    child = _StubMember(id=12, parent_id=11, title="자식", workspace_id=7)
    bundle = _StubBundle(root_document_id=11, trashed_at=t, members=[root, child])

    svc = TrashService(engine=_StubEngine([bundle]), repository=_StubRepo(30))
    page = svc.list_trash(db=None, workspace_id=7, limit=10, offset=0)

    assert isinstance(page, Page)
    assert page.total == 1
    item = page.items[0]
    assert isinstance(item, TrashBundleRead)
    assert item.bundle_id == 11
    assert item.root_document_id == 11
    assert item.root_title == "루트"
    assert item.workspace_id == 7
    assert item.trashed_at == t
    assert item.expires_at == t + timedelta(days=30)
    assert item.member_count == 2
    assert {m.id for m in item.members} == {11, 12}


# --- restore: 묶음 복구 위임(엔진 restore_bundle) -------------------------


def test_restore_returns_bundle_to_active_and_leaves_trash(sessionmaker_factory):
    """복구는 엔진 복구 primitive 를 묶음 루트에 호출해 묶음 전체를 active 로 되돌린다
    (Req 2.1·2.2). 복구 후 구성원은 status=active·trashed_at=NULL 이고 그 루트는
    더 이상 `identify_bundles` 에 열거되지 않는다(휴지통에서 사라짐).

    복구 위치·순서·자동 재중첩 규칙은 엔진이 결정하므로(Req 2.2) 여기서는 위임 결과
    (전체 active 화·휴지통 이탈)만 관찰한다.
    """
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"R-{uuid4().hex}",
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title=f"C-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()
        engine.trash_document(seed, root)
        ws_id, root_id, child_id = ws.id, root.id, child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        result = _service().restore(session, root_id)
        session.commit()
    finally:
        session.close()

    assert result is None, "restore 는 None 을 반환해야 한다(라우터가 204 매핑)"

    verify = sessionmaker_factory()
    try:
        members = (
            verify.query(Document)
            .filter(Document.id.in_([root_id, child_id]))
            .all()
        )
        assert {m.status for m in members} == {"active"}, "구성원 전체 active 복구"
        assert all(m.trashed_at is None for m in members), "trashed_at NULL 복구"

        engine2 = DocumentStateEngine(DocumentRepository())
        bundle_roots = {
            b.root_document_id for b in engine2.identify_bundles(verify, ws_id)
        }
        assert root_id not in bundle_roots, "복구된 묶음은 휴지통에서 사라져야 한다"
    finally:
        verify.close()


def test_restore_only_affects_requested_bundle(sessionmaker_factory):
    """한 묶음의 복구가 다른 독립 묶음을 함께 되살리지 않는다(Req 2.4).

    두 독립 묶음 A·B 를 만들고 A 만 복구한다. B 는 여전히 trashed 로 남고 그 trashed_at
    도 변하지 않아야 한다.
    """
    t_b = datetime(2026, 5, 2, 10, 0, 0)
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        root_a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"A-{uuid4().hex}",
        )
        root_b = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"B-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()
        engine.trash_document(seed, root_a)
        bundle_b = engine.trash_document(seed, root_b)
        _pin_trashed_at(seed, bundle_b.members, t_b)
        ws_id, root_a_id, root_b_id = ws.id, root_a.id, root_b.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        _service().restore(session, root_a_id)
        session.commit()
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        b = verify.query(Document).filter(Document.id == root_b_id).one()
        assert b.status == "trashed", "복구되지 않은 독립 묶음 B 는 여전히 trashed"
        assert b.trashed_at == t_b, "B 의 trashed_at 은 변하지 않아야 한다"

        a = verify.query(Document).filter(Document.id == root_a_id).one()
        assert a.status == "active", "요청된 묶음 A 만 복구되어야 한다"
    finally:
        verify.close()


def test_restore_invalid_root_propagates_404(sessionmaker_factory):
    """유효하지 않은 묶음 루트 복구는 엔진의 404 DomainError 를 전파한다(Req 2.3).

    (a) 존재하지 않는 id, (b) 존재하지만 묶음 루트가 아닌 구성원(자식) id — 둘 다
    엔진 `get_bundle` 이 404 를 던지고 서비스는 이를 삼키지 않고 전파해야 한다.
    """
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"R-{uuid4().hex}",
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title=f"C-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()
        engine.trash_document(seed, root)
        child_id = child.id
    finally:
        seed.close()

    svc = _service()

    session = sessionmaker_factory()
    try:
        with pytest.raises(DomainError) as exc_missing:
            svc.restore(session, 99_999_999)
        assert exc_missing.value.http_status == 404
    finally:
        session.close()

    session2 = sessionmaker_factory()
    try:
        with pytest.raises(DomainError) as exc_nonroot:
            svc.restore(session2, child_id)
        assert exc_nonroot.value.http_status == 404, "비루트 구성원→404"
    finally:
        session2.close()


# --- purge: 묶음 완전삭제 위임(엔진 purge_bundle) -------------------------


def test_purge_transitions_bundle_to_deleted_terminal(sessionmaker_factory):
    """완전삭제는 엔진 완전삭제 primitive 를 묶음 루트에 호출해 묶음 전체를 즉시
    deleted(종착)로 전환한다(Req 3.1·3.3). 완전삭제 후 구성원은 status=deleted 이고
    그 루트는 `identify_bundles`(trashed 만 열거)에서 사라진다.
    """
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"R-{uuid4().hex}",
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title=f"C-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()
        engine.trash_document(seed, root)
        ws_id, root_id, child_id = ws.id, root.id, child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        result = _service().purge(session, root_id)
        session.commit()
    finally:
        session.close()

    assert result is None, "purge 는 None 을 반환해야 한다(라우터가 204 매핑)"

    verify = sessionmaker_factory()
    try:
        members = (
            verify.query(Document)
            .filter(Document.id.in_([root_id, child_id]))
            .all()
        )
        assert {m.status for m in members} == {"deleted"}, "구성원 전체 deleted 종착"

        engine2 = DocumentStateEngine(DocumentRepository())
        bundle_roots = {
            b.root_document_id for b in engine2.identify_bundles(verify, ws_id)
        }
        assert root_id not in bundle_roots, "완전삭제된 묶음은 목록에서 사라져야 한다"
    finally:
        verify.close()


def test_purge_only_affects_requested_bundle(sessionmaker_factory):
    """완전삭제는 요청된 묶음에만 적용되고 다른 독립 묶음의 상태·타이머에 영향이 없다
    (Req 3.2). 두 묶음 중 하나만 purge 하면 나머지는 여전히 trashed·동일 trashed_at 이다.
    """
    t_b = datetime(2026, 5, 3, 11, 0, 0)
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        root_a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"A-{uuid4().hex}",
        )
        root_b = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"B-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()
        engine.trash_document(seed, root_a)
        bundle_b = engine.trash_document(seed, root_b)
        _pin_trashed_at(seed, bundle_b.members, t_b)
        root_a_id, root_b_id = root_a.id, root_b.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        _service().purge(session, root_a_id)
        session.commit()
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        b = verify.query(Document).filter(Document.id == root_b_id).one()
        assert b.status == "trashed", "완전삭제되지 않은 독립 묶음 B 는 여전히 trashed"
        assert b.trashed_at == t_b, "B 의 trashed_at(타이머 기준)은 불변이어야 한다"

        a = verify.query(Document).filter(Document.id == root_a_id).one()
        assert a.status == "deleted", "요청된 묶음 A 만 완전삭제되어야 한다"
    finally:
        verify.close()


def test_purge_invalid_root_propagates_404(sessionmaker_factory):
    """유효하지 않은 묶음 루트 완전삭제는 엔진의 404 DomainError 를 전파한다(Req 3.5).

    존재하지 않는 id 와 비루트 구성원(자식) id 모두 404 로 거부되어야 한다.
    """
    engine = DocumentStateEngine(DocumentRepository())
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(seed, name=f"ws-{uuid4().hex}")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            title=f"R-{uuid4().hex}",
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title=f"C-{uuid4().hex}", sort_order=Decimal("2000"),
        )
        seed.commit()
        engine.trash_document(seed, root)
        child_id = child.id
    finally:
        seed.close()

    svc = _service()

    session = sessionmaker_factory()
    try:
        with pytest.raises(DomainError) as exc_missing:
            svc.purge(session, 99_999_999)
        assert exc_missing.value.http_status == 404
    finally:
        session.close()

    session2 = sessionmaker_factory()
    try:
        with pytest.raises(DomainError) as exc_nonroot:
            svc.purge(session2, child_id)
        assert exc_nonroot.value.http_status == 404, "비루트 구성원→404"
    finally:
        session2.close()
