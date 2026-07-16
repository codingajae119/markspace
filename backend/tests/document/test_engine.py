"""DocumentStateEngine 묶음 식별·열거·active 하위 질의 테스트
(Task 3.1 / Req 6.1, 6.2, 6.3, 6.4, 6.5, 9.1, 9.2, 9.3).

design.md §Components and Interfaces #DocumentStateEngine 의 묶음 계약을 실제 DB 로 검증한다.
이 task 는 삭제/복구/완전삭제(3.2~3.4)를 구현하지 않으며 아래 3개 primitive 만 검증한다:
- `active_descendants` — 특정 문서의 active 하위(root 포함)만 반환(이미 trashed 하위 제외,
  repo.collect_active_descendants 위임, Req 9.3).
- `identify_bundles` — WS 전체 trashed 문서를 묶음(루트+동일 trashed_at 연결 서브트리)으로 분할
  열거. 서로 다른 trashed_at 묶음은 병합되지 않는다(비흡수, Req 6.1·6.4·6.5).
- `get_bundle` — 루트 문서 id 로 묶음 구성원 확정·검증. 미존재·비trashed·비루트 → 404(Req 6.5).

격리: tests/document/test_repository.py 의 확립된 테스트 DB 패턴을 복제한다(실 DB 트리 시드로
repository 질의 의미를 충실히 재현). trashed 문서는 status="trashed"+명시 trashed_at 로 시드한다.
"""

import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.common.errors import DomainError, ErrorCode
from app.document.engine import Bundle, DocumentStateEngine
from app.document.repository import DocumentRepository
from app.models import Document, User, Workspace

TEST_DB_NAME = "notion_lite_test"

# 삭제 시점(공통 trashed_at). 서로 다른 시점이 병합되지 않음을 검증한다.
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


# --- active_descendants --------------------------------------------------


def test_active_descendants_returns_active_subtree_root_included(sessionmaker_factory):
    """active_descendants 는 root 포함 active 하위만 반환하고 이미 trashed 하위는 제외한다
    (repo.collect_active_descendants 위임 검증, Req 9.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="active-desc")
        ws = _make_workspace(seed, name="ws-active")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            sort_order=Decimal("100"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child", status="active", sort_order=Decimal("100"),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child-trashed", status="trashed", sort_order=Decimal("200"),
            trashed_at=T1,
        )
        seed.commit()
        root_id = root.id
        child_id = child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        root = DocumentRepository().get(session, root_id)
        result = engine.active_descendants(session, root)
        titles = {d.title for d in result}
        assert titles == {"root", "child"}, (
            "root 포함 active 하위만 포함되어야 하며 이미 trashed 하위는 제외되어야 한다"
        )
        ids = {d.id for d in result}
        assert root_id in ids and child_id in ids
    finally:
        session.close()


# --- identify_bundles / get_bundle: 단일 시점 연결 서브트리 ---------------


def test_get_bundle_returns_connected_same_trashed_at_members(sessionmaker_factory):
    """get_bundle 은 루트에서 parent_id 로 내려가며 status=trashed 이고 동일 trashed_at 인
    연결 서브트리만 반환한다(다른 trashed_at·타 묶음 제외, Req 6.5)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="conn")
        ws = _make_workspace(seed, name="ws-conn")
        # 한 번의 삭제로 포착된 묶음(모두 동일 trashed_at=T2): root → a → b.
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="trashed", trashed_at=T2, sort_order=Decimal("100"),
        )
        a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="a", status="trashed", trashed_at=T2, sort_order=Decimal("100"),
        )
        b = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=a.id,
            title="b", status="trashed", trashed_at=T2, sort_order=Decimal("100"),
        )
        # root 아래 다른 시점(T1)에 먼저 trashed 된 하위 c — 별개 묶음이라 제외되어야 한다.
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="c-earlier", status="trashed", trashed_at=T1,
            sort_order=Decimal("200"),
        )
        # root 아래 active 하위 — trashed 아니라 묶음 구성원 아님.
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="d-active", status="active", sort_order=Decimal("300"),
        )
        seed.commit()
        root_id = root.id
        a_id, b_id = a.id, b.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        bundle = engine.get_bundle(session, root_id)
        assert isinstance(bundle, Bundle)
        assert bundle.root_document_id == root_id
        assert bundle.trashed_at == T2
        titles = {d.title for d in bundle.members}
        assert titles == {"root", "a", "b"}, (
            "동일 trashed_at 연결 서브트리만 포함되어야 한다(다른 시점·active 제외)"
        )
        member_ids = {d.id for d in bundle.members}
        assert member_ids == {root_id, a_id, b_id}
    finally:
        session.close()


def test_get_bundle_404_for_nonexistent(sessionmaker_factory):
    """get_bundle 은 미존재 id 에 404(NOT_FOUND)를 던진다(Req 6.5)."""
    session = sessionmaker_factory()
    try:
        engine = _engine()
        with pytest.raises(DomainError) as exc:
            engine.get_bundle(session, 999999)
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


def test_get_bundle_404_for_non_trashed(sessionmaker_factory):
    """get_bundle 은 active(비trashed) 문서 id 에 404 를 던진다(Req 6.5)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="nontrash")
        ws = _make_workspace(seed, name="ws-nontrash")
        doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, status="active"
        )
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        with pytest.raises(DomainError) as exc:
            engine.get_bundle(session, doc_id)
        assert exc.value.http_status == 404
    finally:
        session.close()


def test_get_bundle_404_for_non_root_member(sessionmaker_factory):
    """get_bundle 은 비루트 구성원 id(부모가 같은 trashed_at 으로 trashed)에 404 를 던진다
    (Req 6.5)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="nonroot")
        ws = _make_workspace(seed, name="ws-nonroot")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="trashed", trashed_at=T2, sort_order=Decimal("100"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child", status="trashed", trashed_at=T2,
            sort_order=Decimal("100"),
        )
        seed.commit()
        child_id = child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        with pytest.raises(DomainError) as exc:
            engine.get_bundle(session, child_id)
        assert exc.value.http_status == 404, (
            "부모가 같은 trashed_at 으로 trashed 된 구성원은 묶음 루트가 아니다"
        )
    finally:
        session.close()


# --- 비흡수 핵심 시나리오: 자식 먼저(t1)·부모 나중(t2) ---------------------


def test_child_first_parent_later_not_absorbed(sessionmaker_factory):
    """자식 먼저(t1) 삭제·부모 나중(t2) 삭제 시 자식은 자기 묶음 루트로, 부모는 별개 묶음
    루트로 식별되며 부모 묶음 구성원에 그 자식이 포함되지 않는다(비흡수, Req 6.1·6.4·6.5)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="nonabsorb")
        ws = _make_workspace(seed, name="ws-nonabsorb")
        # 부모 P(나중 t2 에 trashed).
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="trashed", trashed_at=T2, sort_order=Decimal("100"),
        )
        # 자식 C(먼저 t1 에 개별 trashed) — 부모의 자식이지만 별개 묶음이어야 한다.
        child_early = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="child-early", status="trashed", trashed_at=T1,
            sort_order=Decimal("100"),
        )
        # 부모와 같은 시점(t2) 에 캐스케이드로 trashed 된 다른 자식 D — 부모 묶음 구성원.
        sibling = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="sibling", status="trashed", trashed_at=T2,
            sort_order=Decimal("200"),
        )
        seed.commit()
        parent_id = parent.id
        child_early_id = child_early.id
        sibling_id = sibling.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()

        # identify_bundles: 두 묶음이 별개 루트로 분리 열거되어야 한다.
        bundles = engine.identify_bundles(session, ws_id_of(session, parent_id))
        roots = {(b.root_document_id, b.trashed_at) for b in bundles}
        assert (parent_id, T2) in roots, "부모는 t2 묶음의 루트여야 한다"
        assert (child_early_id, T1) in roots, "먼저 삭제된 자식은 t1 묶음의 루트여야 한다"
        assert len(bundles) == 2, "서로 다른 시점 묶음은 병합되지 않고 2개로 분리되어야 한다"

        # 부모 묶음은 sibling 만 포함하고 먼저 삭제된 자식은 제외.
        parent_bundle = next(b for b in bundles if b.root_document_id == parent_id)
        parent_member_ids = {d.id for d in parent_bundle.members}
        assert parent_member_ids == {parent_id, sibling_id}, (
            "부모 묶음은 자신과 같은 시점 자식만 포함하고 먼저 trashed 된 자식은 제외한다"
        )
        assert child_early_id not in parent_member_ids, "먼저 삭제된 자식은 흡수되지 않는다"

        # 자식 묶음은 자신 단독.
        child_bundle = next(
            b for b in bundles if b.root_document_id == child_early_id
        )
        assert {d.id for d in child_bundle.members} == {child_early_id}

        # get_bundle 로도 동일하게 확정된다.
        assert {d.id for d in engine.get_bundle(session, parent_id).members} == {
            parent_id,
            sibling_id,
        }
        assert {d.id for d in engine.get_bundle(session, child_early_id).members} == {
            child_early_id
        }
    finally:
        session.close()


def test_identify_bundles_partitions_multiple_workspaces_isolated(sessionmaker_factory):
    """identify_bundles 는 대상 WS 의 trashed 문서만 묶음으로 열거하고 다른 WS 는 제외한다."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="ws-iso")
        ws = _make_workspace(seed, name="ws-target")
        other = _make_workspace(seed, name="ws-other")
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="r1",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="r2",
            status="trashed", trashed_at=T2, sort_order=Decimal("200"),
        )
        # 다른 WS 의 trashed 는 제외되어야 한다.
        _make_document(
            seed, workspace_id=other.id, created_by=user.id, title="other-r",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        bundles = engine.identify_bundles(session, ws_id)
        titles = {b.members[0].title for b in bundles}
        assert titles == {"r1", "r2"}, "대상 WS 의 두 묶음만 열거되어야 한다"
        assert all(len(b.members) == 1 for b in bundles)
    finally:
        session.close()


# --- trash_document (Task 3.2 / Req 5.1~5.7, 6.1~6.4, 9.4) ----------------


def test_trash_document_traps_active_subtree_only(sessionmaker_factory):
    """active 문서 삭제 시 그 시점 active 하위(root 포함)만 공통 trashed_at 으로 trashed 되고,
    이미 trashed 된 하위는 흡수되지 않는다(비흡수, Req 5.1·5.2·6.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="trash-trap")
        ws = _make_workspace(seed, name="ws-trap")
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
        # 이미 trashed 된(과거 T1) 하위 — active_descendants 가 제외해야 한다(비흡수).
        already = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="already-trashed", status="trashed", trashed_at=T1,
            sort_order=Decimal("200"),
        )
        seed.commit()
        root_id, child_id, grandchild_id = root.id, child.id, grandchild.id
        already_id = already.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        root = DocumentRepository().get(session, root_id)
        bundle = engine.trash_document(session, root)

        assert bundle.root_document_id == root_id
        member_ids = {d.id for d in bundle.members}
        assert member_ids == {root_id, child_id, grandchild_id}, (
            "그 시점 active 하위(root 포함)만 포착되어야 한다"
        )
        assert already_id not in member_ids, "이미 trashed 된 하위는 흡수되지 않는다"
        assert all(d.status == "trashed" for d in bundle.members)
        assert all(d.trashed_at == bundle.trashed_at for d in bundle.members), (
            "모든 구성원이 단일 공통 trashed_at 을 공유해야 한다"
        )
    finally:
        session.close()

    # fresh 세션 재조회로 영속·공통값 확인.
    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        persisted = [repo.get(verify, i) for i in (root_id, child_id, grandchild_id)]
        assert all(d.status == "trashed" for d in persisted)
        trashed_ats = {d.trashed_at for d in persisted}
        assert len(trashed_ats) == 1 and None not in trashed_ats, (
            "포착 구성원 전체가 동일 trashed_at 으로 영속되어야 한다"
        )
        # 이미 trashed 된 하위는 자기 시점(T1) 을 그대로 유지(흡수·재기록 없음).
        stale = repo.get(verify, already_id)
        assert stale.status == "trashed" and stale.trashed_at == T1
    finally:
        verify.close()


def test_trash_child_first_parent_later_not_absorbed_inv11(sessionmaker_factory):
    """자식 먼저(t1) 삭제·부모 나중(t2) 삭제 시 자식이 부모 묶음에 흡수되지 않고
    child.trashed_at ≤ parent.trashed_at(INV-11) 이 성립한다(Req 6.3·6.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="trash-inv11")
        ws = _make_workspace(seed, name="ws-inv11")
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="active", sort_order=Decimal("100"),
        )
        # 자식은 부모보다 먼저(t1=T1) 개별 삭제된 상태로 시드 → 독립 묶음(6.3).
        child_early = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="child-early", status="trashed", trashed_at=T1,
            sort_order=Decimal("100"),
        )
        # 부모와 같은 시점(t2)에 캐스케이드될 active 형제.
        sibling = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="sibling", status="active", sort_order=Decimal("200"),
        )
        seed.commit()
        parent_id, child_early_id, sibling_id = (
            parent.id, child_early.id, sibling.id,
        )
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        parent = DocumentRepository().get(session, parent_id)
        bundle = engine.trash_document(session, parent)  # 부모 나중(t2=utcnow > T1)

        member_ids = {d.id for d in bundle.members}
        assert member_ids == {parent_id, sibling_id}, (
            "부모 묶음은 같은 시점 active 형제만 포함한다"
        )
        assert child_early_id not in member_ids, "먼저 삭제된 자식은 흡수되지 않는다"
        # INV-11: child.trashed_at(T1) ≤ parent.trashed_at(t2).
        assert T1 <= bundle.trashed_at, "child.trashed_at ≤ parent.trashed_at 이어야 한다"
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        stale_child = repo.get(verify, child_early_id)
        assert stale_child.trashed_at == T1, "먼저 삭제된 자식의 trashed_at 은 재기록되지 않는다"
    finally:
        verify.close()


def test_trash_non_active_raises_409(sessionmaker_factory):
    """비active(이미 trashed/deleted) 대상 삭제는 409(CONFLICT) 로 거부된다(Req 5.7)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="trash-409")
        ws = _make_workspace(seed, name="ws-409")
        trashed = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="already",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        deleted = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="gone",
            status="deleted", sort_order=Decimal("200"),
        )
        seed.commit()
        trashed_id, deleted_id = trashed.id, deleted.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        repo = DocumentRepository()
        for doc_id in (trashed_id, deleted_id):
            doc = repo.get(session, doc_id)
            with pytest.raises(DomainError) as exc:
                engine.trash_document(session, doc)
            assert exc.value.http_status == 409
            assert exc.value.code == ErrorCode.CONFLICT
    finally:
        session.close()


def test_trash_ignores_lock(sessionmaker_factory):
    """잠긴 문서(lock_user_id 세팅)도 잠금을 무시하고 정상 전이한다(상태·잠금 독립, Req 9.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="trash-lock")
        ws = _make_workspace(seed, name="ws-lock")
        doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="locked",
            status="active", sort_order=Decimal("100"),
        )
        # 잠금 필드를 직접 세팅해도 삭제가 막히지 않아야 한다.
        doc.lock_user_id = user.id
        doc.lock_acquired_at = datetime.utcnow()
        seed.commit()
        doc_id, locker_id = doc.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        doc = DocumentRepository().get(session, doc_id)
        bundle = engine.trash_document(session, doc)
        assert {d.id for d in bundle.members} == {doc_id}
        assert bundle.members[0].status == "trashed"
        # 잠금 값은 엔진이 건드리지 않는다(9.5): 세팅된 lock_user_id 가 그대로 남는다.
        assert bundle.members[0].lock_user_id == locker_id
    finally:
        session.close()


def ws_id_of(session, document_id):
    """시드된 문서의 workspace_id 를 조회하는 소형 헬퍼(테스트 편의)."""
    return DocumentRepository().get_workspace_id(session, document_id)


# --- restore_bundle (Task 3.3 / Req 7.1~7.7, 9.2) ------------------------


def test_restore_under_active_parent_restores_original_sort_order(sessionmaker_factory):
    """부모가 active 면 묶음을 부모 밑으로 복귀(parent_id 유지)하고 원래 sort_order 를 그대로
    복원한다 — 충돌 없으면 원위치(Req 7.1·7.3·7.7)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-active")
        ws = _make_workspace(seed, name="ws-restore-active")
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="active", sort_order=Decimal("100"),
        )
        # 부모 밑 생존 active 형제(원래 이웃) — 충돌하지 않는 위치.
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="sib", status="active", sort_order=Decimal("1000"),
        )
        # 복구 대상 묶음 루트 — 원래 sort_order=500 을 보존한 채 trashed.
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="root", status="trashed", trashed_at=T1, sort_order=Decimal("500"),
        )
        seed.commit()
        parent_id, root_id = parent.id, root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        restored = engine.restore_bundle(session, root_id)
        assert isinstance(restored, list)
        root = next(d for d in restored if d.id == root_id)
        assert root.parent_id == parent_id, "부모 참조를 유지해야 한다(7.1)"
        assert root.sort_order == Decimal("500"), "원래 sort_order 를 원위치 복원(7.3)"
        assert root.status == "active" and root.trashed_at is None
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        persisted = DocumentRepository().get(verify, root_id)
        assert persisted.parent_id == parent_id
        assert persisted.sort_order == Decimal("500")
        assert persisted.status == "active" and persisted.trashed_at is None
    finally:
        verify.close()


def test_restore_sort_order_collision_falls_back_to_midpoint(sessionmaker_factory):
    """원래 sort_order 가 생존 형제와 충돌하면 원래 직전·직후 형제 사이 중간값으로 삽입한다
    (Req 7.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-collide")
        ws = _make_workspace(seed, name="ws-restore-collide")
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="active", sort_order=Decimal("100"),
        )
        # 생존 형제: 100, 200(충돌 대상), 400 — 200 위치에 복구하면 충돌.
        for so in (Decimal("100"), Decimal("200"), Decimal("400")):
            _make_document(
                seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
                title=f"sib-{so}", status="active", sort_order=so,
            )
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="root", status="trashed", trashed_at=T1, sort_order=Decimal("200"),
        )
        seed.commit()
        parent_id, root_id = parent.id, root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        engine.restore_bundle(session, root_id)
        root = DocumentRepository().get(session, root_id)
        # 원래 이웃 100·400 사이 중간값(=250) — 200(충돌)과 다르고 300 이하.
        assert root.parent_id == parent_id
        assert root.sort_order == Decimal("250"), (
            "충돌 시 원래 직전(100)·직후(400) 사이 중간값으로 삽입되어야 한다"
        )
        assert root.status == "active"
    finally:
        session.close()


def test_restore_root_append_end_when_original_only_neighbor_below(sessionmaker_factory):
    """충돌하고 생존 이웃이 한쪽(아래)뿐이면 그 잔존 형제 뒤(근사)로 밀어 넣는다(Req 7.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-approx")
        ws = _make_workspace(seed, name="ws-restore-approx")
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="active", sort_order=Decimal("100"),
        )
        # 생존 형제: 100, 500(충돌 대상). 위쪽 이웃 없음.
        for so in (Decimal("100"), Decimal("500")):
            _make_document(
                seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
                title=f"sib-{so}", status="active", sort_order=so,
            )
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
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
        root = DocumentRepository().get(session, root_id)
        # 아래 잔존 형제(100) 기준 근사: 500 은 충돌이라 위쪽 이웃 없음 → 500+step.
        assert root.sort_order == Decimal("1500"), (
            "위쪽 이웃이 없으면 가장 가까운 잔존 형제(500) 뒤로 근사 삽입한다"
        )
    finally:
        session.close()


def test_restore_to_root_when_parent_trashed_appends_at_end(sessionmaker_factory):
    """부모가 non-active(trashed)면 root 로 복귀(parent_id=NULL)하고 원위치가 아니라 root 맨
    뒤에 배치한다(Req 7.2·7.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-toroot")
        ws = _make_workspace(seed, name="ws-restore-toroot")
        # 부모는 trashed(다른 시점 T2) — 복구 대상과 별개 묶음.
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="trashed", trashed_at=T2, sort_order=Decimal("100"),
        )
        # root 레벨 생존 active 형제: 1000, 2000.
        for so in (Decimal("1000"), Decimal("2000")):
            _make_document(
                seed, workspace_id=ws.id, created_by=user.id, title=f"root-sib-{so}",
                status="active", sort_order=so,
            )
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
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
        root = DocumentRepository().get(session, root_id)
        assert root.parent_id is None, "부모 non-active 면 parent_id=NULL(7.2)"
        assert root.sort_order == Decimal("3000"), (
            "root 맨 뒤(2000+step)에 배치하고 원래 sort_order(500)를 복원하지 않는다(7.4)"
        )
        assert root.status == "active" and root.trashed_at is None
    finally:
        session.close()


def test_restore_root_level_bundle_appends_not_original(sessionmaker_factory):
    """루트 레벨 묶음(부모 부재, parent_id=None)도 root 복귀로 취급해 원위치 대신 맨 뒤에
    배치한다(Req 7.2·7.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-rootlevel")
        ws = _make_workspace(seed, name="ws-restore-rootlevel")
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root-sib",
            status="active", sort_order=Decimal("1000"),
        )
        # parent_id=None 인 root 레벨 묶음, 원래 sort_order=500.
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="trashed", trashed_at=T1, sort_order=Decimal("500"),
        )
        seed.commit()
        root_id = root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        engine.restore_bundle(session, root_id)
        root = DocumentRepository().get(session, root_id)
        assert root.parent_id is None
        assert root.sort_order == Decimal("2000"), (
            "부모 부재는 root 복귀 → 맨 뒤(1000+step), 원래 500 복원 안 함"
        )
    finally:
        session.close()


def test_restore_transitions_all_members_and_preserves_hierarchy(sessionmaker_factory):
    """복구 시 구성원 전체가 active·trashed_at=NULL 로 전환되고 묶음 내부 상대 계층(부모 참조·
    정렬)은 유지된다(Req 7.7)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-hierarchy")
        ws = _make_workspace(seed, name="ws-restore-hierarchy")
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="parent",
            status="active", sort_order=Decimal("100"),
        )
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="root", status="trashed", trashed_at=T1, sort_order=Decimal("500"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child", status="trashed", trashed_at=T1, sort_order=Decimal("111"),
        )
        grandchild = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=child.id,
            title="grandchild", status="trashed", trashed_at=T1, sort_order=Decimal("222"),
        )
        seed.commit()
        root_id, child_id, gc_id = root.id, child.id, grandchild.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        restored = engine.restore_bundle(session, root_id)
        assert {d.id for d in restored} == {root_id, child_id, gc_id}
        assert all(d.status == "active" for d in restored)
        assert all(d.trashed_at is None for d in restored)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        child = repo.get(verify, child_id)
        gc = repo.get(verify, gc_id)
        # 내부 계층·정렬 유지(재삽입은 루트만): child→root, grandchild→child.
        assert child.parent_id == root_id and child.sort_order == Decimal("111")
        assert gc.parent_id == child_id and gc.sort_order == Decimal("222")
        assert all(
            d.status == "active" and d.trashed_at is None for d in (child, gc)
        )
    finally:
        verify.close()


def test_restore_no_auto_renest_child_stays_at_root(sessionmaker_factory):
    """자식을 root 로 복구한 뒤 그 부모를 복구해도 자식을 부모 밑으로 자동 재중첩하지 않는다
    (Req 7.5)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-norenest")
        ws = _make_workspace(seed, name="ws-restore-norenest")
        # 부모 P 는 T1, 자식 C(P 의 자식)는 T2 로 별개 삭제 → 별개 묶음.
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
        # 1) 자식 먼저 복구 → 부모(P)가 trashed 이므로 root 로 복귀(parent_id=NULL).
        engine.restore_bundle(session, child_id)
        child = DocumentRepository().get(session, child_id)
        assert child.parent_id is None, "부모가 trashed 라 자식은 root 로 복귀한다"

        # 2) 이제 부모 복구 → 자식은 이미 active(root)이며 자동 재중첩되지 않는다.
        engine.restore_bundle(session, parent_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        child = DocumentRepository().get(verify, child_id)
        assert child.parent_id is None, (
            "부모 복구가 이전에 root 로 복구된 자식을 자동으로 재중첩하지 않아야 한다(7.5)"
        )
        assert child.status == "active"
    finally:
        verify.close()


def test_restore_independent_bundle_leaves_others_untouched(sessionmaker_factory):
    """독립 묶음 단독 복구는 다른 독립 묶음을 함께 되살리지 않는다(Req 7.6)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore-independent")
        ws = _make_workspace(seed, name="ws-restore-independent")
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
            title="b2-child", status="trashed", trashed_at=T2, sort_order=Decimal("100"),
        )
        seed.commit()
        b1_id, b2_id, b2_child_id = b1.id, b2.id, b2_child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        engine.restore_bundle(session, b1_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        assert repo.get(verify, b1_id).status == "active", "복구된 묶음만 active"
        # 다른 독립 묶음(b2)은 그대로 trashed·trashed_at 유지.
        b2 = repo.get(verify, b2_id)
        b2_child = repo.get(verify, b2_child_id)
        assert b2.status == "trashed" and b2.trashed_at == T2
        assert b2_child.status == "trashed" and b2_child.trashed_at == T2
    finally:
        verify.close()


def test_restore_invalid_root_raises_404(sessionmaker_factory):
    """유효하지 않은 묶음 루트(미존재)를 복구하면 get_bundle 검증으로 404 를 던진다(Req 6.5 재사용)."""
    session = sessionmaker_factory()
    try:
        engine = _engine()
        with pytest.raises(DomainError) as exc:
            engine.restore_bundle(session, 999999)
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- purge_bundle (Task 3.4 / Req 8.1~8.5) -------------------------------


def test_purge_transitions_all_members_to_deleted_preserving_trashed_at(
    sessionmaker_factory,
):
    """완전삭제는 묶음 구성원 전체를 즉시 deleted 로 전환하고 단일 공통 trashed_at 을 보존한다
    (물리 삭제 없음, Req 8.1·8.4). 반환은 묶음(구성원 now-deleted)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="purge-all")
        ws = _make_workspace(seed, name="ws-purge-all")
        # 한 번의 삭제로 포착된 묶음(모두 동일 trashed_at=T1): root → a → b.
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
        bundle = engine.purge_bundle(session, root_id)

        assert isinstance(bundle, Bundle)
        assert bundle.root_document_id == root_id
        assert bundle.trashed_at == T1, "완전삭제는 trashed_at 을 보존한다(NULL 로 비우지 않음)"
        assert {d.id for d in bundle.members} == {root_id, a_id, b_id}
        assert all(d.status == "deleted" for d in bundle.members), (
            "구성원 전체가 즉시 deleted 로 전환되어야 한다(8.1)"
        )
        assert all(d.trashed_at == T1 for d in bundle.members), (
            "단일 공통 trashed_at 이 보존되어야 한다(비워지지 않음)"
        )
    finally:
        session.close()

    # fresh 세션 재조회로 영속·물리보존 확인(레코드가 삭제되지 않고 status=deleted 로 남는다).
    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        for doc_id in (root_id, a_id, b_id):
            persisted = repo.get(verify, doc_id)
            assert persisted is not None, "물리 삭제 없음 — 레코드가 보존되어야 한다(INV-4·8.4)"
            assert persisted.status == "deleted"
            assert persisted.trashed_at == T1, "완전삭제 후에도 trashed_at 이 보존된다"
    finally:
        verify.close()


def test_purge_leaves_other_independent_bundle_untouched(sessionmaker_factory):
    """완전삭제는 대상 묶음만 deleted 로 전환하고 다른 독립 묶음은 trashed·자기 trashed_at 을
    그대로 유지한다(Req 8.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="purge-indep")
        ws = _make_workspace(seed, name="ws-purge-indep")
        # 대상 묶음 b1(T1).
        b1 = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="b1",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        # 독립 묶음 b2(T2) + 그 자식 — 건드리면 안 된다.
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
        engine.purge_bundle(session, b1_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        assert repo.get(verify, b1_id).status == "deleted", "대상 묶음만 deleted"
        # 다른 독립 묶음(b2)은 그대로 trashed·trashed_at 유지.
        b2 = repo.get(verify, b2_id)
        b2_child = repo.get(verify, b2_child_id)
        assert b2.status == "trashed" and b2.trashed_at == T2, "독립 묶음은 불변(8.2)"
        assert b2_child.status == "trashed" and b2_child.trashed_at == T2
    finally:
        verify.close()


def test_purge_invalid_root_raises_404(sessionmaker_factory):
    """완전삭제는 미존재·비trashed(active)·비루트 구성원 루트에 404 를 던진다
    (get_bundle 검증 재사용, Req 6.5 → 8 전제)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="purge-404")
        ws = _make_workspace(seed, name="ws-purge-404")
        active = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="active",
            status="active", sort_order=Decimal("100"),
        )
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="trashed", trashed_at=T1, sort_order=Decimal("200"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child", status="trashed", trashed_at=T1,
            sort_order=Decimal("100"),
        )
        seed.commit()
        active_id, child_id = active.id, child.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        # 미존재.
        with pytest.raises(DomainError) as exc:
            engine.purge_bundle(session, 999999)
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
        # 비trashed(active).
        with pytest.raises(DomainError) as exc:
            engine.purge_bundle(session, active_id)
        assert exc.value.http_status == 404
        # 비루트 구성원(부모가 같은 trashed_at 으로 trashed).
        with pytest.raises(DomainError) as exc:
            engine.purge_bundle(session, child_id)
        assert exc.value.http_status == 404
    finally:
        session.close()


def test_purge_deleted_is_terminal(sessionmaker_factory):
    """deleted 는 종착 상태다(Req 8.3) — 완전삭제된 문서는 다시 trashed 될 수 없고(409),
    더는 trashed 가 아니므로 복구·묶음 조회도 404 로 거부된다(애플리케이션 복구 경로 없음)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="purge-terminal")
        ws = _make_workspace(seed, name="ws-purge-terminal")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="trashed", trashed_at=T1, sort_order=Decimal("100"),
        )
        seed.commit()
        root_id = root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        repo = DocumentRepository()
        engine.purge_bundle(session, root_id)

        purged = repo.get(session, root_id)
        assert purged.status == "deleted"

        # 재삭제 불가: deleted 는 active 가 아니므로 trash 는 409.
        with pytest.raises(DomainError) as exc:
            engine.trash_document(session, purged)
        assert exc.value.http_status == 409
        assert exc.value.code == ErrorCode.CONFLICT

        # 복구/묶음 조회 불가: 더는 trashed 가 아니므로 404(복구 경로 없음).
        with pytest.raises(DomainError) as exc:
            engine.restore_bundle(session, root_id)
        assert exc.value.http_status == 404
        with pytest.raises(DomainError) as exc:
            engine.get_bundle(session, root_id)
        assert exc.value.http_status == 404
    finally:
        session.close()
