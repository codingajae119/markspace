"""DocumentStateEngine 불변식 property·edge-case 테스트 (Task 5.2).

엔진 primitive 를 **라우터 밖에서 직접 호출**하는 재사용 경계로 검증한다(s10/s14 소비
계약, Req 9.1·9.2). design.md §Testing Strategy §Property / Edge-case Tests(비흡수·독립
타이머 기준·복구 위치 결정성·이동 사이클 부재)와 §Invariants(INV-5·10·11·12) 를 대상으로
한다. 다섯 절(clause)을 담는다:

  1. 비흡수 property(INV-10·11) — 임의 트리에서 자식·부모를 임의 순서로 삭제해도 서로 다른
     시점 묶음이 병합되지 않고 각 묶음이 독립 루트로 식별된다(itertools.permutations 로
     삭제 순서를 결정적 열거; 3노드→6순서로 DB 부하를 제한).
  2. 독립 타이머 기준 property(INV-12) — 각 묶음의 보관 기준 시각이 자기 trashed_at 이며
     다른 묶음의 삭제·복구가 그 기준값을 바꾸지 않는다.
  3. 복구 위치 결정성(Req 7.1~7.5) — 부모 상태 조합(active/trashed/deleted/부재)에 대해
     복구 목적지가 6.5 규칙과 일치하고 자동 재중첩이 없다.
  4. 완전삭제 원자성·종착·물리삭제 없음(Req 8.1·8.3·8.4).
  5. 이동 사이클 부재 property(INV-5) — move 는 SERVICE 소유이므로 DocumentService.
     move_document 로 자기/후손 이동이 409 로 거부되고, 유효 이동 후 계층에 사이클이 없다.

harness 는 tests/document/test_engine.py 의 확립된 패턴(테스트 DB 마이그레이션 fixture·
시드 헬퍼·T1/T2 타임스탬프)을 복제한다(모듈 자기완결성 유지, test_engine.py 미수정).
DB 기반(느림)이다. `_ensure_after` 로 실 trash_document 호출 간 trashed_at 의 엄격 단조성을
보장해 타임스탬프 충돌로 인한 허위 병합/플래키를 방지한다.
"""

import itertools
import os
import time
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.common.errors import DomainError, ErrorCode
from app.document.engine import Bundle, DocumentStateEngine
from app.document.renderer import MarkdownRenderer
from app.document.repository import DocumentRepository
from app.document.schemas import DocumentMoveRequest
from app.document.service import DocumentService
from app.models import Document, User, Workspace

TEST_DB_NAME = "notion_lite_test"

# 서로 다른 삭제 시점(명시 시드용). 서로 다른 시점 묶음이 병합되지 않음을 검증한다.
T1 = datetime(2026, 7, 16, 10, 0, 0)
T2 = datetime(2026, 7, 16, 11, 0, 0)


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
    """테스트 DB 에 User 를 삽입하고 flush 하여 id 를 확정한다(created_by FK 충족용)."""
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
    """Workspace 행을 삽입하고 flush 한다(document.workspace_id FK 충족용)."""
    ws = Workspace(
        name=name,
        is_shareable=False,
        trash_retention_days=30,
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
    trashed_at=None,
):
    """Document 행을 직접 삽입하고 flush 한다(트리·상태 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        trashed_at=trashed_at,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


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


def _engine():
    return DocumentStateEngine(DocumentRepository())


def _service():
    return DocumentService(DocumentRepository(), MarkdownRenderer())


def _ensure_after(ts: datetime) -> None:
    """utcnow() 가 ts 를 초과할 때까지 짧게 대기한다(가능한 한 삭제 시각을 벌린다).

    trash_document 는 내부에서 datetime.utcnow() 로 trashed_at 을 찍는다. 다음 삭제 전에
    시계가 ts 를 지나도록 대기해 연속 삭제의 시각을 벌린다.

    주의: document.trashed_at 은 s01 스키마상 MySQL DATETIME(소수 자리 0 = **초 단위**)
    이므로, 같은 초 안에서 발생한 서로 다른 삭제는 저장 시 동일 trashed_at 으로 절삭될 수
    있다(→ 같은 초·부모자식 연결이면 같은 묶음으로 식별). 따라서 이 대기는 **초 경계를
    보장하지 않으며** 아래 property 단언은 그 절삭에 무관하게 성립하는 불변식(분할·단일
    trashed_at·INV-11)만 검사한다. 확정적 개수/독립성이 필요한 단언은 실 삭제 대신
    명시 서로 다른 trashed_at 을 시드해 검증한다.
    """
    while datetime.utcnow() <= ts:
        time.sleep(0.001)


# =====================================================================
# Clause 1 — 비흡수 property (INV-10·11): 임의 삭제 순서에서 묶음 불병합
# =====================================================================


def _seed_tree(seed, user, ws):
    """트리 R→A→B, R→C 를 active 로 시드하고 id 매핑을 반환한다(비흡수 열거용)."""
    r = _make_document(
        seed, workspace_id=ws.id, created_by=user.id, title="R",
        sort_order=Decimal("100"),
    )
    a = _make_document(
        seed, workspace_id=ws.id, created_by=user.id, parent_id=r.id, title="A",
        sort_order=Decimal("100"),
    )
    b = _make_document(
        seed, workspace_id=ws.id, created_by=user.id, parent_id=a.id, title="B",
        sort_order=Decimal("100"),
    )
    c = _make_document(
        seed, workspace_id=ws.id, created_by=user.id, parent_id=r.id, title="C",
        sort_order=Decimal("200"),
    )
    return {"R": r.id, "A": a.id, "B": b.id, "C": c.id}


def test_non_absorption_property_over_deletion_orders(sessionmaker_factory):
    """임의 삭제 순서에서도 서로 다른 시점 묶음이 병합되지 않고 독립 루트로 식별된다
    (비흡수, INV-10·11). itertools.permutations 로 (A,B,C) 삭제 순서 6가지를 결정적 열거하고
    각 순서마다 R 을 마지막에 삭제한다(3노드→6순서로 DB 부하 제한). 각 순서마다 전용
    workspace 를 써서 단일 테스트 DB 안에서 격리한다.

    순서에 따라 삭제 시점 캐스케이드 결과(묶음 개수)는 달라지지만, 아래 **불변식**은 모든
    순서에서 성립해야 한다:
      (P1) 분할: 묶음 구성원의 합집합 = 전체 trashed 문서, 구성원 서로소(중복 흡수 없음).
      (P2) 단일 trashed_at: 각 묶음의 모든 구성원이 루트와 동일 trashed_at(교차시점 병합 없음).
      (P3) INV-11/비흡수: 묶음 루트의 부모가 trashed 이면 부모는 **다른** 묶음이고
           root.trashed_at ≤ parent.trashed_at(자식이 먼저 진입).
    """
    node_names = ["A", "B", "C"]
    # 3노드 순열 = 6가지(문서화된 상한; 침묵 절삭 아님). R 은 항상 마지막에 삭제.
    orders = list(itertools.permutations(node_names))
    assert len(orders) == 6

    for perm_index, perm in enumerate(orders):
        delete_sequence = list(perm) + ["R"]

        seed = sessionmaker_factory()
        try:
            user = _make_user(seed, login_id=f"nonabsorb-{perm_index}")
            ws = _make_workspace(seed, name=f"ws-nonabsorb-{perm_index}")
            ids = _seed_tree(seed, user, ws)
            seed.commit()
            ws_id = ws.id
        finally:
            seed.close()

        # 지정 순서로 삭제. 캐스케이드로 이미 trashed 된 노드는 건너뛴다(비active→409).
        op = sessionmaker_factory()
        try:
            engine = _engine()
            repo = DocumentRepository()
            last_ts = datetime(1970, 1, 1)
            for name in delete_sequence:
                doc = repo.get(op, ids[name])
                if doc.status != "active":
                    continue  # 앞선 삭제 캐스케이드에 이미 포착됨(임의 순서 모델)
                _ensure_after(last_ts)  # 각 독립 삭제가 서로 다른 trashed_at 을 갖도록
                bundle = engine.trash_document(op, doc)
                last_ts = bundle.trashed_at
        finally:
            op.close()

        # fresh 세션에서 커밋된 상태를 읽어 불변식을 검증한다.
        verify = sessionmaker_factory()
        try:
            engine = _engine()
            repo = DocumentRepository()
            all_trashed = repo.list_trashed_by_workspace(verify, ws_id)
            trashed_ids = {d.id for d in all_trashed}
            assert trashed_ids == set(ids.values()), (
                f"{perm}: 전 노드가 결국 trashed 여야 한다"
            )

            bundles = engine.identify_bundles(verify, ws_id)
            by_id = {d.id: d for d in all_trashed}

            # (P1) 분할: 구성원 합집합=전체, 서로소.
            member_ids: list[int] = []
            for b in bundles:
                member_ids.extend(d.id for d in b.members)
            assert len(member_ids) == len(set(member_ids)), (
                f"{perm}: 어떤 문서도 둘 이상 묶음에 흡수되지 않아야 한다(서로소)"
            )
            assert set(member_ids) == trashed_ids, (
                f"{perm}: 묶음들은 trashed 집합을 정확히 분할해야 한다"
            )

            # (P2) 단일 trashed_at: 각 묶음의 모든 구성원이 루트와 동일 시점.
            for b in bundles:
                assert all(m.trashed_at == b.trashed_at for m in b.members), (
                    f"{perm}: 서로 다른 시점이 한 묶음으로 병합되면 안 된다"
                )

            # (P3) INV-11/비흡수: 루트의 부모가 trashed 면 다른 묶음이고 child≤parent.
            for b in bundles:
                root = by_id[b.root_document_id]
                if root.parent_id is None:
                    continue
                parent = by_id.get(root.parent_id)
                if parent is None or parent.status != "trashed":
                    continue
                # 루트로 식별됐는데 부모가 trashed 라면 부모는 반드시 다른 시점(=다른 묶음).
                assert parent.trashed_at != root.trashed_at, (
                    f"{perm}: 먼저 삭제된 자식이 부모 묶음에 흡수되면 안 된다"
                )
                assert root.trashed_at <= parent.trashed_at, (
                    f"{perm}: INV-11 child.trashed_at ≤ parent.trashed_at 위반"
                )
        finally:
            verify.close()


def test_non_absorption_identify_distinct_events_stay_separate(sessionmaker_factory):
    """서로 다른 시점(명시 4개 trashed_at)에 개별 삭제된 부모자식 트리의 각 노드는
    identify_bundles/get_bundle 에서 4개 독립 싱글턴 묶음으로 식별되고 서로 흡수되지 않는다
    (비흡수 식별 primitive, Req 6.1·6.4·6.5). 실 삭제(초 단위 절삭) 대신 명시 서로 다른
    trashed_at 을 시드해 확정적으로 검증한다."""
    # 트리 R→A→B, R→C 를 서로 다른 4개 시점에 개별 삭제된 상태로 시드(각자 독립 묶음).
    ta = datetime(2026, 7, 16, 9, 0, 0)  # A
    tb = datetime(2026, 7, 16, 10, 0, 0)  # B
    tc = datetime(2026, 7, 16, 11, 0, 0)  # C
    tr = datetime(2026, 7, 16, 12, 0, 0)  # R
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="nonabsorb-explicit")
        ws = _make_workspace(seed, name="ws-nonabsorb-explicit")
        r = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="R",
            status="trashed", trashed_at=tr, sort_order=Decimal("100"),
        )
        a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=r.id, title="A",
            status="trashed", trashed_at=ta, sort_order=Decimal("100"),
        )
        b = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=a.id, title="B",
            status="trashed", trashed_at=tb, sort_order=Decimal("100"),
        )
        c = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=r.id, title="C",
            status="trashed", trashed_at=tc, sort_order=Decimal("200"),
        )
        seed.commit()
        ws_id = ws.id
        ids = {"R": r.id, "A": a.id, "B": b.id, "C": c.id}
    finally:
        seed.close()

    verify = sessionmaker_factory()
    try:
        engine = _engine()
        bundles = engine.identify_bundles(verify, ws_id)
        roots = {b.root_document_id for b in bundles}
        # 각 노드가 서로 다른 시점에 개별 삭제됐으므로 4개 독립 싱글턴 묶음이어야 한다.
        assert roots == set(ids.values()), "서로 다른 시점 4노드는 4개 독립 묶음이어야 한다"
        assert all(len(bd.members) == 1 for bd in bundles), "어느 묶음도 타 노드를 흡수 안 함"
        # B(자식)는 A(부모)·R(조부) 묶음 어디에도 흡수되지 않는다.
        for bd in bundles:
            if bd.root_document_id != ids["B"]:
                assert ids["B"] not in {m.id for m in bd.members}
        # get_bundle 로도 각 노드가 자기 단독 묶음 루트로 확정된다.
        for node_id in ids.values():
            assert {m.id for m in engine.get_bundle(verify, node_id).members} == {
                node_id
            }
    finally:
        verify.close()


# =====================================================================
# Clause 2 — 독립 타이머 기준 property (INV-12): 기준값 불변
# =====================================================================


def test_independent_retention_basis_purge_does_not_alter_other(sessionmaker_factory):
    """각 묶음의 보관 기준 시각은 자기 trashed_at 이며, 다른 묶음의 **완전삭제**가 그
    기준값을 바이트 단위로 바꾸지 않는다(INV-12 기준값 불변, Req 6.4·8.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="basis-purge")
        ws = _make_workspace(seed, name="ws-basis-purge")
        # 독립 묶음 b1(T1), b2(T2, 자식 포함).
        b1 = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="b1",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        b2 = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="b2",
            status="trashed", trashed_at=T2, sort_order=Decimal("200"),
        )
        b2_child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=b2.id,
            title="b2-child", status="trashed", trashed_at=T2,
            sort_order=Decimal("100"),
        )
        seed.commit()
        b1_id, b2_id, b2_child_id = b1.id, b2.id, b2_child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        # b1 완전삭제 전 b2 기준값 스냅샷.
        before = engine.get_bundle(session, b2_id).trashed_at
        engine.purge_bundle(session, b1_id)
        after = engine.get_bundle(session, b2_id).trashed_at
        assert before == T2 and after == T2, (
            "다른 묶음 완전삭제가 b2 의 보관 기준(trashed_at)을 바꾸면 안 된다"
        )
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        assert repo.get(verify, b1_id).status == "deleted"
        b2 = repo.get(verify, b2_id)
        b2c = repo.get(verify, b2_child_id)
        assert b2.status == "trashed" and b2.trashed_at == T2, "b2 기준값 불변"
        assert b2c.status == "trashed" and b2c.trashed_at == T2
    finally:
        verify.close()


def test_independent_retention_basis_restore_does_not_alter_other(sessionmaker_factory):
    """다른 묶음의 **복구**도 잔존 묶음의 trashed_at 기준값을 바꾸지 않는다(INV-12)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="basis-restore")
        ws = _make_workspace(seed, name="ws-basis-restore")
        b1 = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="b1",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        b2 = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="b2",
            status="trashed", trashed_at=T2, sort_order=Decimal("200"),
        )
        seed.commit()
        b1_id, b2_id = b1.id, b2.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        engine.restore_bundle(session, b1_id)  # b1 복구
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        assert repo.get(verify, b1_id).status == "active"
        b2 = repo.get(verify, b2_id)
        assert b2.status == "trashed" and b2.trashed_at == T2, (
            "다른 묶음 복구가 b2 의 보관 기준을 바꾸면 안 된다(INV-12)"
        )
    finally:
        verify.close()


# =====================================================================
# Clause 3 — 복구 위치 결정성 (Req 7.1~7.5)
# =====================================================================


@pytest.mark.parametrize(
    "parent_state",
    ["active", "trashed", "deleted", "absent"],
)
def test_restore_destination_determined_by_parent_state(
    sessionmaker_factory, parent_state
):
    """부모 상태 조합에 대해 복구 목적지가 6.5 규칙과 일치한다(Req 7.1·7.2·7.4).

    - active 부모 → 부모 밑 복귀(parent_id 유지) + 원위치 sort_order 복원(비충돌).
    - trashed/deleted/부재 부모 → root 복귀(parent_id=NULL) + root 맨 뒤 배치.
    """
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id=f"restore-dest-{parent_state}")
        ws = _make_workspace(seed, name=f"ws-restore-dest-{parent_state}")

        parent_id = None
        if parent_state != "absent":
            status = "active" if parent_state == "active" else parent_state
            trashed_at = T2 if parent_state == "trashed" else None
            parent = _make_document(
                seed, workspace_id=ws.id, created_by=user.id, title="parent",
                status=status, trashed_at=trashed_at, sort_order=Decimal("100"),
            )
            parent_id = parent.id

        # root 레벨 생존 active 형제(맨 뒤 append 위치를 결정적으로 만든다): sort_order=1000.
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root-sib",
            status="active", sort_order=Decimal("1000"),
        )
        # 복구 대상 묶음 루트: 원래 sort_order=500 보존한 채 trashed(T1).
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent_id,
            title="root", status="trashed", trashed_at=T1, sort_order=Decimal("500"),
        )
        seed.commit()
        root_id = root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        engine.restore_bundle(session, root_id)
        restored = DocumentRepository().get(session, root_id)
        assert restored.status == "active" and restored.trashed_at is None

        if parent_state == "active":
            assert restored.parent_id == parent_id, (
                "부모 active → 부모 참조 유지(7.1)"
            )
            assert restored.sort_order == Decimal("500"), (
                "비충돌이면 원래 sort_order 원위치 복원(7.3)"
            )
        else:
            assert restored.parent_id is None, (
                f"부모 {parent_state} → root 복귀·parent_id=NULL(7.2)"
            )
            # root 레벨 생존 형제(1000) 맨 뒤 = 1000 + step(1000) = 2000, 원래 500 아님.
            assert restored.sort_order == Decimal("2000"), (
                "root 복귀는 맨 뒤 배치이고 원래 sort_order 복원 아님(7.4)"
            )
    finally:
        session.close()


def test_restore_no_auto_renest_child_stays_at_root(sessionmaker_factory):
    """자식을 root 로 복구한 뒤 그 부모를 복구해도 자식을 부모 밑으로 자동 재중첩하지
    않는다(Req 7.5)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="renest")
        ws = _make_workspace(seed, name="ws-renest")
        # 부모 P(T1)·자식 C(T2)는 별개 시점 삭제 → 별개 묶음.
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="child", status="trashed", trashed_at=T2, sort_order=Decimal("200"),
        )
        seed.commit()
        parent_id, child_id = parent.id, child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        # 자식 먼저 복구 → 부모가 trashed 이므로 root 로 복귀(parent_id=NULL).
        engine.restore_bundle(session, child_id)
        assert DocumentRepository().get(session, child_id).parent_id is None
        # 이제 부모 복구 → 자식은 이미 active(root)이며 자동 재중첩되지 않아야 한다.
        engine.restore_bundle(session, parent_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        child = DocumentRepository().get(verify, child_id)
        assert child.parent_id is None and child.status == "active", (
            "부모 복구가 이전에 root 로 복구된 자식을 재중첩하면 안 된다(7.5)"
        )
    finally:
        verify.close()


# =====================================================================
# Clause 4 — 완전삭제 원자성·종착·물리삭제 없음 (Req 8.1·8.3·8.4)
# =====================================================================


def test_purge_is_atomic_terminal_and_non_physical(sessionmaker_factory):
    """완전삭제는 묶음 전체를 즉시 deleted 로 전환(원자적, 8.1)하고, deleted 는 종착이라
    재삭제·복구·묶음조회가 거부되며(8.3), 레코드는 물리 삭제되지 않는다(8.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="purge-inv")
        ws = _make_workspace(seed, name="ws-purge-inv")
        # 다구성원 묶음(동일 trashed_at=T1): root → a → b.
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="a", status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        b = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=a.id,
            title="b", status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        seed.commit()
        root_id, a_id, b_id = root.id, a.id, b.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        repo = DocumentRepository()
        bundle = engine.purge_bundle(session, root_id)

        # 원자성: 구성원 전체가 한 번에 deleted, trashed_at 보존.
        assert isinstance(bundle, Bundle)
        assert {d.id for d in bundle.members} == {root_id, a_id, b_id}
        assert all(d.status == "deleted" for d in bundle.members), "원자 전환(8.1)"
        assert all(d.trashed_at == T1 for d in bundle.members), "trashed_at 보존"

        purged = repo.get(session, root_id)
        # 종착: 재삭제 불가(409).
        with pytest.raises(DomainError) as exc:
            engine.trash_document(session, purged)
        assert exc.value.http_status == 409 and exc.value.code == ErrorCode.CONFLICT
        # 종착: 복구·묶음조회 불가(더는 trashed 아님 → 404, 복구 경로 없음).
        with pytest.raises(DomainError) as exc:
            engine.restore_bundle(session, root_id)
        assert exc.value.http_status == 404
        with pytest.raises(DomainError) as exc:
            engine.get_bundle(session, root_id)
        assert exc.value.http_status == 404
    finally:
        session.close()

    # 물리삭제 없음: fresh 세션에서 레코드가 status=deleted 로 보존되어야 한다(INV-4·8.4).
    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        for doc_id in (root_id, a_id, b_id):
            persisted = repo.get(verify, doc_id)
            assert persisted is not None, "레코드가 물리 삭제되면 안 된다(INV-4·8.4)"
            assert persisted.status == "deleted"
            assert persisted.trashed_at == T1
    finally:
        verify.close()


# =====================================================================
# Clause 5 — 이동 사이클 부재 property (INV-5), DocumentService.move_document
# =====================================================================


def _has_cycle(repo, session, start_id) -> bool:
    """start_id 에서 parent 체인을 되짚어 사이클(자기 재방문)이 있는지 판정한다."""
    seen: set[int] = set()
    node = repo.get(session, start_id)
    while node is not None:
        if node.id in seen:
            return True
        seen.add(node.id)
        if node.parent_id is None:
            return False
        node = repo.get(session, node.parent_id)
    return False


def test_move_rejects_self_and_descendant_no_cycle_created(sessionmaker_factory):
    """이동 사이클 부재(INV-5): 체인 root→child→grandchild 에서 자기/후손 밑 이동은 모두
    409 로 거부되고, 유효 이동 후에도 계층 그래프에 사이클이 없다(Req 4.2·4.7)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="move-cycle")
        ws = _make_workspace(seed, name="ws-move-cycle")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="active", sort_order=Decimal("100"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child", status="active", sort_order=Decimal("100"),
        )
        grandchild = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=child.id,
            title="grandchild", status="active", sort_order=Decimal("100"),
        )
        seed.commit()
        root_id, child_id, gc_id = root.id, child.id, grandchild.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        service = _service()
        repo = DocumentRepository()

        # 자기 자신 밑 이동 거부(409).
        with pytest.raises(DomainError) as exc:
            service.move_document(
                session, root_id, DocumentMoveRequest(new_parent_id=root_id)
            )
        assert exc.value.http_status == 409

        # 직계 후손(child) 밑으로 root 이동 거부(409).
        with pytest.raises(DomainError) as exc:
            service.move_document(
                session, root_id, DocumentMoveRequest(new_parent_id=child_id)
            )
        assert exc.value.http_status == 409

        # 더 깊은 후손(grandchild) 밑으로 root 이동 거부(409).
        with pytest.raises(DomainError) as exc:
            service.move_document(
                session, root_id, DocumentMoveRequest(new_parent_id=gc_id)
            )
        assert exc.value.http_status == 409

        # 거부된 이동은 계층을 바꾸지 않았다 — 사이클 없음.
        for node_id in (root_id, child_id, gc_id):
            assert not _has_cycle(repo, session, node_id), "거부 후 사이클 없어야 함"

        # 유효 이동: grandchild 를 root 레벨(new_parent_id=None)로 승격 → 사이클 없음.
        service.move_document(
            session, gc_id, DocumentMoveRequest(new_parent_id=None)
        )
        moved = repo.get(session, gc_id)
        assert moved.parent_id is None
        for node_id in (root_id, child_id, gc_id):
            assert not _has_cycle(repo, session, node_id), "유효 이동 후에도 사이클 없음(INV-5)"
    finally:
        session.close()
