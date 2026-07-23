"""상태·잠금 독립 및 엔진 primitive 재사용 통합 검증 (Task 5.3).

design.md §4.3(상태·잠금 독립)·§DocumentStateEngine 재사용 경계, requirements Req 8.5·9.1·
9.2·9.4·9.5 를 마이그레이션된 실 DB 위에서 통합 수준으로 검증한다. test_engine.py 의 단위
수준 `test_trash_ignores_lock`(3.2) 과 달리, 여기서는 (1) 잠긴 문서의 상태 전이가 잠금과
독립적으로 동작하고 이 spec 이 lock 값을 스스로 설정하지 않음, (2) 동일 엔진의
`trash_document`→`restore_bundle`→(재삭제)→`purge_bundle` 왕복이 상태를 일관되게 전이시켜
s10 이 라우터 없이 소비할 복구·완전삭제·묶음 열거 primitive 계약이 성립함을 폭넓게 확인한다.

격리: tests/document/test_engine.py 의 확립된 테스트 DB 하네스를 자족적으로 복제한다
(sessionmaker_factory·시더·_engine). s07 앱 코드·기존 테스트 파일은 수정하지 않는다.
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


# --- Clause (1): 상태·잠금 독립 (§4.3, Req 9.4·9.5) -----------------------


def test_trash_transitions_locked_subtree_and_leaves_lock_untouched(
    sessionmaker_factory,
):
    """`lock_user_id`/`lock_acquired_at` 이 직접 세팅된 문서(s09 가 잠금 보유 중이라 가정)도
    `trash_document` 가 잠금과 독립적으로 정상 전이시키며(전이 차단 없음), 엔진은 잠금 값을
    읽어 막지도 새로 쓰지도 않는다(상태·잠금 독립, §4.3·Req 9.4·9.5).

    fresh 세션 재조회로 status='trashed' 와 세팅했던 lock_user_id 가 그대로 보존됨을 확인한다.
    """
    lock_ts = datetime(2026, 7, 15, 9, 30, 0)
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="lock-indep")
        ws = _make_workspace(seed, name="ws-lock-indep")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="locked-root",
            status="active", sort_order=Decimal("100"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child", status="active", sort_order=Decimal("100"),
        )
        # 루트에만 잠금을 직접 세팅(s09 편집 잠금 시뮬레이션). 삭제가 막히면 안 된다.
        root.lock_user_id = user.id
        root.lock_acquired_at = lock_ts
        seed.commit()
        root_id, child_id, locker_id = root.id, child.id, user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        root = DocumentRepository().get(session, root_id)
        bundle = engine.trash_document(session, root)
        # 잠금이 전이를 막지 않는다: 잠긴 루트 + active 하위가 정상 포착·전이.
        assert {d.id for d in bundle.members} == {root_id, child_id}
        assert all(d.status == "trashed" for d in bundle.members)
        # 엔진이 잠금 값을 새로 쓰거나 지우지 않는다: 세팅값 그대로.
        trashed_root = next(d for d in bundle.members if d.id == root_id)
        assert trashed_root.lock_user_id == locker_id
        assert trashed_root.lock_acquired_at == lock_ts
    finally:
        session.close()

    # fresh 세션: 상태 전이는 영속되고 잠금 값은 손대지 않은 채 보존된다.
    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        persisted_root = repo.get(verify, root_id)
        assert persisted_root.status == "trashed", "잠금과 독립적으로 상태가 전이되어야 한다"
        assert persisted_root.lock_user_id == locker_id, (
            "엔진은 lock_user_id 를 건드리지 않아야 한다(9.5)"
        )
        assert persisted_root.lock_acquired_at == lock_ts
        # 잠기지 않았던 자식은 여전히 잠금 없음 — 엔진이 잠금을 새로 부여하지 않는다.
        persisted_child = repo.get(verify, child_id)
        assert persisted_child.status == "trashed"
        assert persisted_child.lock_user_id is None
        assert persisted_child.lock_acquired_at is None
    finally:
        verify.close()


def test_lifecycle_never_sets_lock_on_unlocked_document(sessionmaker_factory):
    """잠금이 없던 문서는 create 후 trash→restore→(재)trash→purge 왕복을 거쳐도 엔진/서비스가
    lock 값을 스스로 채우지 않는다(Req 9.5) — 왕복 내내 lock_user_id/lock_acquired_at 은 NULL.
    """
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="lock-never-set")
        ws = _make_workspace(seed, name="ws-lock-never")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="unlocked-root",
            status="active", sort_order=Decimal("100"),
        )
        child = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, parent_id=root.id,
            title="child", status="active", sort_order=Decimal("100"),
        )
        # 시드는 잠금 없이 생성(직접 세팅하지 않음) — 이후 엔진이 채우는지 관찰한다.
        seed.commit()
        root_id, child_id = root.id, child.id
        assert root.lock_user_id is None and child.lock_user_id is None
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        repo = DocumentRepository()
        engine.trash_document(session, repo.get(session, root_id))
        engine.restore_bundle(session, root_id)
        engine.trash_document(session, repo.get(session, root_id))
        engine.purge_bundle(session, root_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        for doc_id in (root_id, child_id):
            persisted = repo.get(verify, doc_id)
            assert persisted.lock_user_id is None, (
                "엔진/서비스는 lock_user_id 를 스스로 설정하지 않는다(9.5)"
            )
            assert persisted.lock_acquired_at is None, (
                "엔진/서비스는 lock_acquired_at 을 스스로 설정하지 않는다(9.5)"
            )
    finally:
        verify.close()


# --- Clause (2): 엔진 primitive 재사용 왕복 계약 (Req 9.1·9.2·8.5) ----------


def test_engine_primitive_roundtrip_is_consistent_for_s10_reuse(
    sessionmaker_factory,
):
    """라우터 없이 엔진 primitive 만으로 전체 생명주기를 왕복시켜 s10 이 소비할 복구·완전삭제·
    묶음 열거 계약이 실 DB 에서 일관되게 성립함을 검증한다(Req 9.1·9.2).

    create(active 서브트리) → trash_document(묶음 trashed·공통 trashed_at·identify/get_bundle
    포착) → restore_bundle(active 복귀·trashed_at=NULL·열거에서 사라짐) → 재trash(새 묶음·fresh
    trashed_at) → purge_bundle(deleted·종착·물리보존) 를 단일 세션에서 수행하고, fresh 세션
    재조회로 상태 일관성을 확인한다.
    """
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="roundtrip")
        ws = _make_workspace(seed, name="ws-roundtrip")
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
        ws_id = ws.id
        root_id, child_id, gc_id = root.id, child.id, grandchild.id
        all_ids = {root_id, child_id, gc_id}
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        repo = DocumentRepository()

        # 1) trash_document — active 서브트리를 묶음으로 포착.
        bundle1 = engine.trash_document(session, repo.get(session, root_id))
        assert isinstance(bundle1, Bundle)
        assert bundle1.root_document_id == root_id
        assert {d.id for d in bundle1.members} == all_ids
        assert all(d.status == "trashed" for d in bundle1.members)
        first_trashed_at = bundle1.trashed_at
        assert first_trashed_at is not None
        assert all(d.trashed_at == first_trashed_at for d in bundle1.members), (
            "묶음 구성원은 단일 공통 trashed_at 을 공유해야 한다"
        )
        # 열거·조회 primitive 가 이 묶음을 본다(s10 소비 계약).
        listed = engine.identify_bundles(session, ws_id)
        assert root_id in {b.root_document_id for b in listed}
        assert {d.id for d in engine.get_bundle(session, root_id).members} == all_ids

        # 2) restore_bundle — active 복귀, trashed_at=NULL, 열거에서 사라짐.
        restored = engine.restore_bundle(session, root_id)
        assert {d.id for d in restored} == all_ids
        assert all(d.status == "active" for d in restored)
        assert all(d.trashed_at is None for d in restored)
        assert root_id not in {
            b.root_document_id for b in engine.identify_bundles(session, ws_id)
        }, "복구된 묶음은 더 이상 trashed 묶음으로 열거되지 않는다"
        with pytest.raises(DomainError) as exc:
            engine.get_bundle(session, root_id)  # 더는 trashed 아님 → 404.
        assert exc.value.http_status == 404

        # 3) 재trash — 새 묶음, 이전과 구별되는 fresh trashed_at.
        bundle2 = engine.trash_document(session, repo.get(session, root_id))
        assert {d.id for d in bundle2.members} == all_ids
        assert bundle2.trashed_at is not None
        assert bundle2.trashed_at >= first_trashed_at, (
            "재삭제는 새로 산정된(이전 이상) trashed_at 을 갖는다"
        )

        # 4) purge_bundle — 즉시 deleted, trashed_at 보존, 종착.
        purged = engine.purge_bundle(session, root_id)
        assert isinstance(purged, Bundle)
        assert {d.id for d in purged.members} == all_ids
        assert all(d.status == "deleted" for d in purged.members)
        assert all(d.trashed_at == bundle2.trashed_at for d in purged.members), (
            "완전삭제는 trashed_at 을 보존한다(NULL 화 없음, 8.4)"
        )

        # 종착 계약: 재삭제 409, 복구·묶음조회 404(복구 경로 없음, 8.3).
        purged_root = repo.get(session, root_id)
        with pytest.raises(DomainError) as exc:
            engine.trash_document(session, purged_root)
        assert exc.value.http_status == 409
        assert exc.value.code == ErrorCode.CONFLICT
        with pytest.raises(DomainError) as exc:
            engine.restore_bundle(session, root_id)
        assert exc.value.http_status == 404
        with pytest.raises(DomainError) as exc:
            engine.get_bundle(session, root_id)
        assert exc.value.http_status == 404
    finally:
        session.close()

    # fresh 세션: 왕복 결과가 물리 보존된 채 deleted 로 일관되게 영속된다.
    verify = sessionmaker_factory()
    try:
        repo = DocumentRepository()
        for doc_id in all_ids:
            persisted = repo.get(verify, doc_id)
            assert persisted is not None, "물리 삭제 없음 — 레코드 보존(INV-4·8.4)"
            assert persisted.status == "deleted"
            assert persisted.trashed_at is not None, "완전삭제 후에도 trashed_at 보존"
        # purge 는 상태 전이만 수행 — 버전 참조를 건드리지 않는다(8.5 경계).
        assert repo.get(verify, root_id).current_version_id is None
    finally:
        verify.close()


def test_purge_only_transitions_state_not_version_concerns(sessionmaker_factory):
    """완전삭제 primitive 는 상태 전이에 한정되며 버전(current_version_id) 등 s09/s12 관심사를
    건드리지 않는다(Req 8.5) — 시드해 둔 current_version_id 가 purge 후에도 그대로 보존된다.
    """
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="purge-8-5")
        ws = _make_workspace(seed, name="ws-purge-8-5")
        root = _make_document(
            seed, workspace_id=ws.id, created_by=user.id, title="root",
            status="trashed", trashed_at=datetime(2026, 7, 16, 8, 0, 0),
            sort_order=Decimal("100"),
        )
        seed.flush()
        # 버전 행을 만들고 current_version_id 를 세팅(s09 소유 필드) — purge 가 보존해야 한다.
        version = app.models.DocumentVersion(
            document_id=root.id,
            content="본문",
            created_by=user.id,
            created_at=datetime.utcnow(),
        )
        seed.add(version)
        seed.flush()
        root.current_version_id = version.id
        seed.commit()
        root_id, version_id = root.id, version.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        engine = _engine()
        engine.purge_bundle(session, root_id)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        persisted = DocumentRepository().get(verify, root_id)
        assert persisted.status == "deleted", "상태만 전이한다(8.1)"
        assert persisted.current_version_id == version_id, (
            "완전삭제는 버전 참조를 건드리지 않는다(상태 전이 한정, 8.5)"
        )
    finally:
        verify.close()
