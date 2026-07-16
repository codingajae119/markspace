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


def ws_id_of(session, document_id):
    """시드된 문서의 workspace_id 를 조회하는 소형 헬퍼(테스트 편의)."""
    return DocumentRepository().get_workspace_id(session, document_id)
