"""DocumentRepository 통합 테스트 (Task 1.2 / Req 1.1, 1.2, 2.1, 2.4, 3.1, 4.1,
5.2, 5.3, 6.1, 6.5, 7.1, 8.1, 9.3).

design.md §Components and Interfaces #DocumentRepository 계약을 실제 DB 로 검증한다:
- `insert` 는 status=active 문서 행을 만들고 `created_at` 을 설정하며 fresh 세션 재조회로
  영속화를 증명한다(Req 1.1).
- `collect_active_descendants` 는 트리에서 active 하위(root 포함)만 반환하고 trashed 하위·
  그 서브트리는 제외한다(비흡수 캐스케이드 소비, Req 6.1·9.3).
- `list_trashed_by_workspace` 는 trashed 문서를 반환한다(묶음 재구성, Req 7.1·8.1).
- `load_current_content` 는 current_version 부재 시 빈 문자열, 존재 시 해당 content 를
  반환한다(Req 2.1·2.4).
- `list_children`/`list_siblings` 는 sort_order 정렬 순으로 반환하고,
  `list_active_by_workspace` 는 limit/offset·total 을 올바로 적용하며,
  `set_status_bulk` 은 원자 상태 전이를, `set_parent_and_order` 는 부모/정렬 갱신을 한다.

격리: tests/workspace/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`markspace_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한
뒤 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.models import Document, DocumentVersion, User, Workspace
from app.document.repository import DocumentRepository

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
    current_version_id=None,
    trashed_at=None,
):
    """Document 행을 직접 삽입하고 flush 한다(트리·상태 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        current_version_id=current_version_id,
        trashed_at=trashed_at,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


def _make_version(session, *, document_id, created_by, content):
    """DocumentVersion 행을 삽입하고 flush 하여 id 를 확정한다(본문 로드용)."""
    version = DocumentVersion(
        document_id=document_id,
        content=content,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(version)
    session.flush()
    return version


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


# --- insert --------------------------------------------------------------


def test_insert_creates_active_document_and_persists(sessionmaker_factory):
    """insert 는 status=active 문서를 만들고 fresh 세션 재조회로 영속화를 증명한다 (Req 1.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="author")
        ws = _make_workspace(seed, name="ws-insert")
        seed.commit()
        ws_id, user_id = ws.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        created = repo.insert(
            session,
            workspace_id=ws_id,
            parent_id=None,
            title="첫 문서",
            sort_order=Decimal("1000"),
            created_by=user_id,
        )
        assert created.status == "active", "생성 문서는 status=active 여야 한다"
        assert created.created_at is not None, "created_at 은 설정되어야 한다"
        assert created.current_version_id is None, "생성 시 초기 버전을 만들지 않는다"
        doc_id = created.id
        assert doc_id is not None
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded is not None, "생성된 문서 행이 영속되어야 한다"
        assert reloaded.status == "active"
        assert reloaded.title == "첫 문서"
        assert reloaded.workspace_id == ws_id
        assert reloaded.parent_id is None
        assert reloaded.sort_order == Decimal("1000")
    finally:
        verify.close()


# --- get / get_workspace_id ---------------------------------------------


def test_get_returns_document_or_none(sessionmaker_factory):
    """get 은 존재 시 행을, 미존재 시 None 을 반환한다."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="g")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        found = repo.get(session, doc_id)
        assert found is not None
        assert found.id == doc_id
        assert repo.get(session, 999999) is None
    finally:
        session.close()


def test_get_workspace_id_returns_scalar_or_none(sessionmaker_factory):
    """get_workspace_id 는 문서의 workspace_id 를, 미존재 시 None 을 반환한다 (어댑터용, Req 4.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="wsid")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        seed.commit()
        doc_id, ws_id = doc.id, ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        assert repo.get_workspace_id(session, doc_id) == ws_id
        assert repo.get_workspace_id(session, 999999) is None
    finally:
        session.close()


# --- collect_active_descendants -----------------------------------------


def test_collect_active_descendants_excludes_trashed_subtrees(sessionmaker_factory):
    """collect_active_descendants 는 root 포함 active 하위만 반환하고 trashed 서브트리는 제외한다
    (핵심: 부모 active인데 자식이 trashed면 그 자식·그 서브트리 제외, Req 6.1·9.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="tree")
        ws = _make_workspace(seed, name="ws-tree")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            sort_order=Decimal("100"),
        )
        # root 아래 active 자식과 그 active 손자.
        child_a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child-a", status="active", sort_order=Decimal("100"),
        )
        grand_a = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=child_a.id,
            title="grand-a", status="active", sort_order=Decimal("100"),
        )
        # root 아래 trashed 자식과 그 아래 (여전히 active인) 손자 — 둘 다 제외되어야 한다.
        child_trashed = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child-trashed", status="trashed", sort_order=Decimal("200"),
            trashed_at=datetime.utcnow(),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id,
            parent_id=child_trashed.id, title="grand-under-trashed",
            status="active", sort_order=Decimal("100"),
        )
        seed.commit()
        root_id = root.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        root = repo.get(session, root_id)
        result = repo.collect_active_descendants(session, root)
        titles = {d.title for d in result}
        assert titles == {"root", "child-a", "grand-a"}, (
            "root 포함 active 하위만 포함되어야 하며 trashed 자식·그 서브트리는 제외되어야 한다"
        )
        assert root_id in {d.id for d in result}, "root 자신이 결과에 포함되어야 한다"
    finally:
        session.close()


# --- list_trashed_by_workspace ------------------------------------------


def test_list_trashed_by_workspace_returns_trashed_only(sessionmaker_factory):
    """list_trashed_by_workspace 는 해당 워크스페이스의 trashed 문서만 반환한다 (Req 7.1·8.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="trash")
        ws = _make_workspace(seed, name="ws-trash")
        other_ws = _make_workspace(seed, name="ws-other")
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="active-doc",
            status="active",
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="trashed-1",
            status="trashed", trashed_at=datetime.utcnow(),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="trashed-2",
            status="trashed", trashed_at=datetime.utcnow(),
        )
        # 다른 워크스페이스의 trashed 는 제외되어야 한다.
        _make_document(
            seed, workspace_id=other_ws.id, created_by=user.id,
            title="other-trashed", status="trashed", trashed_at=datetime.utcnow(),
        )
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        trashed = repo.list_trashed_by_workspace(session, ws_id)
        titles = {d.title for d in trashed}
        assert titles == {"trashed-1", "trashed-2"}
        assert all(d.status == "trashed" for d in trashed)
    finally:
        session.close()


# --- load_current_content ------------------------------------------------


def test_load_current_content_empty_when_no_current_version(sessionmaker_factory):
    """current_version_id 가 None 이면 빈 문자열을 반환한다 (Req 2.1·2.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="nover")
        ws = _make_workspace(seed)
        doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, current_version_id=None
        )
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        doc = repo.get(session, doc_id)
        assert repo.load_current_content(session, doc) == "", (
            "현재 버전이 없으면 빈 문자열이어야 한다"
        )
    finally:
        session.close()


def test_load_current_content_returns_version_content(sessionmaker_factory):
    """current_version_id 가 있으면 해당 버전의 content 를 반환한다 (Req 2.1·2.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="withver")
        ws = _make_workspace(seed)
        doc = _make_document(seed, workspace_id=ws.id, created_by=user.id)
        version = _make_version(
            seed, document_id=doc.id, created_by=user.id,
            content="# 제목\n본문 내용",
        )
        doc.current_version_id = version.id
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        doc = repo.get(session, doc_id)
        assert repo.load_current_content(session, doc) == "# 제목\n본문 내용"
    finally:
        session.close()


# --- list_children / list_siblings (정렬 순) -----------------------------


def test_list_children_returns_sorted_by_sort_order(sessionmaker_factory):
    """list_children 은 주어진 status 의 자식을 sort_order 순으로 반환한다 (Req 1.2·2.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="children")
        ws = _make_workspace(seed)
        parent = _make_document(seed, workspace_id=ws.id, created_by=user.id, title="p")
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="c-2", sort_order=Decimal("2000"),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="c-1", sort_order=Decimal("1000"),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="c-3", sort_order=Decimal("3000"),
        )
        # trashed 자식은 status="active" 조회에서 제외.
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="c-trashed", status="trashed", sort_order=Decimal("500"),
            trashed_at=datetime.utcnow(),
        )
        seed.commit()
        parent_id = parent.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        children = repo.list_children(session, parent_id, "active")
        assert [c.title for c in children] == ["c-1", "c-2", "c-3"], (
            "sort_order 오름차순 정렬이어야 하고 trashed 자식은 제외되어야 한다"
        )
    finally:
        session.close()


def test_list_siblings_root_level_uses_null_parent(sessionmaker_factory):
    """list_siblings 는 parent_id=None 이면 루트 형제(parent_id IS NULL)를 정렬 순으로 반환한다 (Req 4.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="siblings")
        ws = _make_workspace(seed, name="ws-sib")
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root-b",
            sort_order=Decimal("2000"),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root-a",
            sort_order=Decimal("1000"),
        )
        # 하위 문서는 루트 형제 조회에서 제외.
        parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root-a",
            sort_order=Decimal("1500"),
        )
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=parent.id,
            title="child", sort_order=Decimal("1000"),
        )
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        siblings = repo.list_siblings(session, ws_id, None, "active")
        assert all(s.parent_id is None for s in siblings), (
            "루트 형제는 parent_id IS NULL 이어야 한다"
        )
        assert [s.title for s in siblings] == ["root-a", "root-a", "root-b"], (
            "sort_order 오름차순 정렬이어야 한다"
        )
        assert len(siblings) == 3, "child(하위)는 루트 형제에서 제외되어야 한다"
    finally:
        session.close()


# --- list_active_by_workspace (limit/offset·total) -----------------------


def test_list_active_by_workspace_applies_limit_offset_and_total(sessionmaker_factory):
    """list_active_by_workspace 는 active 문서만 반환하고 total 은 전체·limit/offset 은 items 에 적용한다
    (Req 3.1·2.4)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="pager")
        ws = _make_workspace(seed, name="ws-page")
        for i in range(5):
            _make_document(
                seed, workspace_id=ws.id, created_by=user.id, title=f"a-{i}",
                status="active", sort_order=Decimal(str(1000 * (i + 1))),
            )
        # trashed 문서는 active 목록·total 에서 제외.
        _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="t",
            status="trashed", trashed_at=datetime.utcnow(),
        )
        seed.commit()
        ws_id = ws.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        items, total = repo.list_active_by_workspace(
            session, ws_id, limit=2, offset=0
        )
        assert total == 5, "total 은 active 전체 개수여야 한다(trashed 제외)"
        assert len(items) == 2
        assert all(d.status == "active" for d in items)

        items2, total2 = repo.list_active_by_workspace(
            session, ws_id, limit=2, offset=4
        )
        assert total2 == 5
        assert len(items2) == 1  # 마지막 페이지 잔여 1건
    finally:
        session.close()


# --- apply_updates -------------------------------------------------------


def test_apply_updates_changes_title_and_sets_updated_at(sessionmaker_factory):
    """apply_updates 는 title 부분 갱신하고 updated_at 을 설정하며 화이트리스트 밖 키는 무시한다 (Req 3.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="upd")
        ws = _make_workspace(seed)
        doc = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="원제목",
            status="active",
        )
        seed.commit()
        doc_id = doc.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        doc = repo.get(session, doc_id)
        # title 만 갱신. 화이트리스트 밖(status)은 무시되어야 한다.
        repo.apply_updates(session, doc, {"title": "새제목", "status": "trashed"})
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.title == "새제목"
        assert reloaded.status == "active", "status 는 화이트리스트 밖이라 무시되어야 한다"
        assert reloaded.updated_at is not None, "updated_at 이 설정되어야 한다"
    finally:
        verify.close()


# --- set_status_bulk (원자 전이) -----------------------------------------


def test_set_status_bulk_transitions_all_atomically(sessionmaker_factory):
    """set_status_bulk 은 전달된 docs 전체의 status·trashed_at 을 한 번에 세팅하고 커밋한다
    (묶음 전이 원자 적용점, Req 5.2·6.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="bulk")
        ws = _make_workspace(seed, name="ws-bulk")
        ids = []
        for i in range(3):
            d = _make_document(
                seed, workspace_id=ws.id, created_by=user.id, title=f"b-{i}",
                status="active",
            )
            ids.append(d.id)
        seed.commit()
    finally:
        seed.close()

    trashed_at = datetime(2026, 7, 16, 12, 0, 0)
    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        docs = [repo.get(session, i) for i in ids]
        repo.set_status_bulk(session, docs, status="trashed", trashed_at=trashed_at)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        for i in ids:
            reloaded = verify.get(Document, i)
            assert reloaded.status == "trashed"
            assert reloaded.trashed_at == trashed_at
    finally:
        verify.close()


def test_set_status_bulk_restores_null_trashed_at(sessionmaker_factory):
    """set_status_bulk 은 trashed_at=None 으로 복구 시 NULL 을 복원한다 (Req 5.2 복구 primitive 지원)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="restore")
        ws = _make_workspace(seed)
        d = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, status="trashed",
            trashed_at=datetime.utcnow(),
        )
        seed.commit()
        doc_id = d.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        doc = repo.get(session, doc_id)
        repo.set_status_bulk(session, [doc], status="active", trashed_at=None)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, doc_id)
        assert reloaded.status == "active"
        assert reloaded.trashed_at is None, "복구 시 trashed_at 이 NULL 로 복원되어야 한다"
    finally:
        verify.close()


# --- set_parent_and_order ------------------------------------------------


def test_set_parent_and_order_updates_and_persists(sessionmaker_factory):
    """set_parent_and_order 는 parent_id·sort_order 를 갱신하고 영속화한다 (Req 4.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="move")
        ws = _make_workspace(seed, name="ws-move")
        new_parent = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="new-parent"
        )
        moving = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="moving",
            parent_id=None, sort_order=Decimal("1000"),
        )
        seed.commit()
        moving_id, parent_id = moving.id, new_parent.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        doc = repo.get(session, moving_id)
        repo.set_parent_and_order(
            session, doc, parent_id=parent_id, sort_order=Decimal("2500")
        )
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(Document, moving_id)
        assert reloaded.parent_id == parent_id
        assert reloaded.sort_order == Decimal("2500")
    finally:
        verify.close()
