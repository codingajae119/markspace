"""ShareInvalidationSweep 단위 테스트 (Task 2.4 / Req 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.7).

design.md §Components and Interfaces #ShareInvalidationSweep(Feature/Service·Batch) 계약과
§System Flows 「무효화 반응 조정 스윕」flowchart 를 실제 DB 로 검증한다:
- `invalidate_by_observation(db)` 는 `list_enabled_invalidatable`(무효화 스코프)이 반환한, 활성
  이면서 문서 status 가 trashed/deleted 이거나 워크스페이스 게이트(off)인 링크만 retire(비활성 +
  토큰 교체)하고 그 건수를 반환한다(Req 5.1·5.2·5.3).
- retire 는 토큰을 교체하므로 이후 문서 복구·게이트 재활성에도 이전 토큰은 되살아나지 않는다
  (재발급 필수, Req 5.4·INV-8).
- 상태 전이·게이트 설정은 하지 않고 문서 status·게이트를 **관측만** 한다 — 스윕 후에도
  Document.status·Workspace.is_shareable 는 불변이어야 한다(Req 5.5·7.7).
- 이미 비활성 링크는 스코프에서 제외되어 재-retire 되지 않으며(멱등 스코프), 반복 실행이 중복
  retire/오류를 내지 않는다(Req 5.6).

격리: tests/sharing/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME` 을 전용
테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤 그 시점 URL
로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한 뒤 환경변수·
캐시를 원복한다. 공유 테스트 DB 충돌을 피하려 이름/제목에 uuid4 접미사를, DATETIME(0) 반올림을
피하려 초 정밀도 시각을 쓴다.
"""

import os
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.models import Document, ShareLink, User, Workspace
from app.sharing.invalidation import ShareInvalidationSweep

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


def _make_document(
    session,
    *,
    workspace_id,
    created_by,
    title="문서",
    status="active",
    sort_order=Decimal("1000"),
):
    """Document 행을 직접 삽입하고 flush 한다(링크·스코프 시드용)."""
    doc = Document(
        workspace_id=workspace_id,
        parent_id=None,
        title=title,
        status=status,
        sort_order=sort_order,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


def _make_share_link(
    session,
    *,
    document_id,
    token=None,
    is_enabled=True,
    created_at=None,
):
    """ShareLink 행을 직접 삽입하고 flush 한다(스코프 시드용)."""
    link = ShareLink(
        document_id=document_id,
        token=token or uuid4().hex,
        is_enabled=is_enabled,
        created_at=created_at or datetime(2026, 7, 17, 9, 0, 0),
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


def _seed_mixed_scope(session):
    """무효화 스코프 검증용 링크 5종을 시드하고 (문서/워크스페이스/링크 식별자)를 반환한다.

    - 활성·게이트 on·trashed 문서    → 무효(retire 대상)
    - 활성·게이트 on·deleted 문서    → 무효(retire 대상)
    - 활성·게이트 off·active 문서    → 무효(retire 대상)
    - 활성·게이트 on·active 문서     → 건강(불변)
    - 이미 비활성·게이트 on·trashed  → 스코프 제외(멱등, 재-retire 없음)
    """
    user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
    ws_on = _make_workspace(session, name=f"ws-on-{uuid4().hex}", is_shareable=True)
    ws_off = _make_workspace(session, name=f"ws-off-{uuid4().hex}", is_shareable=False)

    trashed_doc = _make_document(
        session, workspace_id=ws_on.id, created_by=user.id, status="trashed"
    )
    link_trashed = _make_share_link(
        session, document_id=trashed_doc.id, token=f"t-{uuid4().hex}", is_enabled=True
    )
    deleted_doc = _make_document(
        session, workspace_id=ws_on.id, created_by=user.id, status="deleted"
    )
    link_deleted = _make_share_link(
        session, document_id=deleted_doc.id, token=f"d-{uuid4().hex}", is_enabled=True
    )
    off_doc = _make_document(
        session, workspace_id=ws_off.id, created_by=user.id, status="active"
    )
    link_gate_off = _make_share_link(
        session, document_id=off_doc.id, token=f"g-{uuid4().hex}", is_enabled=True
    )

    healthy_doc = _make_document(
        session, workspace_id=ws_on.id, created_by=user.id, status="active"
    )
    link_healthy = _make_share_link(
        session, document_id=healthy_doc.id, token=f"h-{uuid4().hex}", is_enabled=True
    )

    already_off_doc = _make_document(
        session, workspace_id=ws_on.id, created_by=user.id, status="trashed"
    )
    link_already_off = _make_share_link(
        session,
        document_id=already_off_doc.id,
        token=f"x-{uuid4().hex}",
        is_enabled=False,
    )
    session.commit()

    return {
        "invalid_ids": [link_trashed.id, link_deleted.id, link_gate_off.id],
        "invalid_tokens": {
            link_trashed.id: link_trashed.token,
            link_deleted.id: link_deleted.token,
            link_gate_off.id: link_gate_off.token,
        },
        "healthy_id": link_healthy.id,
        "healthy_token": link_healthy.token,
        "already_off_id": link_already_off.id,
        "already_off_token": link_already_off.token,
        "trashed_doc_id": trashed_doc.id,
        "off_ws_id": ws_off.id,
    }


def test_invalidate_by_observation_retires_invalid_enabled_links(sessionmaker_factory):
    """무효(trashed/deleted 문서·게이트 off)한 활성 링크를 retire(비활성 + 토큰 교체)한다(Req 5.1·5.2·5.3)."""
    session = sessionmaker_factory()
    try:
        seed = _seed_mixed_scope(session)
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        sweep = ShareInvalidationSweep()
        count = sweep.invalidate_by_observation(session)
        assert count == 3, "무효 활성 링크 3건이 retire 되어야 한다(반환 건수)"
    finally:
        session.close()

    # 새 세션 재조회로 영속화 확인: 각 무효 링크는 비활성 + 토큰 교체.
    verify = sessionmaker_factory()
    try:
        for link_id in seed["invalid_ids"]:
            row = verify.get(ShareLink, link_id)
            assert row is not None, "retire 는 물리 삭제하지 않는다(행 유지, INV-4)"
            assert row.is_enabled is False, "무효 링크는 비활성화되어야 한다"
            assert row.token != seed["invalid_tokens"][link_id], (
                "retire 는 토큰을 교체해 이전 토큰을 영구 무효화한다(INV-8)"
            )
    finally:
        verify.close()


def test_invalidate_by_observation_leaves_healthy_and_already_disabled(
    sessionmaker_factory,
):
    """건강한 링크는 불변이고, 이미 비활성 링크는 재-retire 되지 않는다(멱등 스코프, Req 5.6)."""
    session = sessionmaker_factory()
    try:
        seed = _seed_mixed_scope(session)
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        sweep = ShareInvalidationSweep()
        sweep.invalidate_by_observation(session)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        # 건강한 링크: 여전히 활성 + 동일 토큰(스코프 밖).
        healthy = verify.get(ShareLink, seed["healthy_id"])
        assert healthy.is_enabled is True, "건강한 링크는 건드리지 않는다"
        assert healthy.token == seed["healthy_token"], "건강한 링크 토큰은 유지"

        # 이미 비활성 링크: 스코프에서 제외되어 토큰이 교체되지 않는다(재-retire 없음).
        already_off = verify.get(ShareLink, seed["already_off_id"])
        assert already_off.is_enabled is False
        assert already_off.token == seed["already_off_token"], (
            "이미 비활성 링크는 스코프 밖이라 재-retire 되지 않는다(토큰 불변, 멱등)"
        )
    finally:
        verify.close()


def test_invalidate_by_observation_is_idempotent_on_second_run(sessionmaker_factory):
    """반복 실행이 중복 retire/오류를 내지 않는다: 2회차는 0을 반환(Req 5.6)."""
    session = sessionmaker_factory()
    try:
        _seed_mixed_scope(session)
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        sweep = ShareInvalidationSweep()
        first = sweep.invalidate_by_observation(session)
        assert first == 3, "1회차는 무효 활성 링크 3건을 retire"
    finally:
        session.close()

    # 2회차: 무효 링크는 이미 비활성이라 스코프에서 빠져 아무 것도 retire 하지 않는다.
    session = sessionmaker_factory()
    try:
        sweep = ShareInvalidationSweep()
        second = sweep.invalidate_by_observation(session)
        assert second == 0, "2회차는 새로 retire 할 링크가 없어 0을 반환하고 오류가 없다"
    finally:
        session.close()


def test_invalidate_by_observation_does_not_transition_state_or_set_gate(
    sessionmaker_factory,
):
    """관측만: 스윕 후에도 Document.status·Workspace.is_shareable 는 불변이어야 한다(Req 5.5·7.7)."""
    session = sessionmaker_factory()
    try:
        seed = _seed_mixed_scope(session)
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        sweep = ShareInvalidationSweep()
        sweep.invalidate_by_observation(session)
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        # 스윕은 상태 전이를 하지 않는다: trashed 문서는 여전히 trashed.
        doc = verify.get(Document, seed["trashed_doc_id"])
        assert doc.status == "trashed", "스윕은 문서 상태를 전이시키지 않는다(관측만)"
        # 스윕은 게이트를 설정하지 않는다: off 워크스페이스는 여전히 off.
        ws = verify.get(Workspace, seed["off_ws_id"])
        assert ws.is_shareable is False, "스윕은 워크스페이스 게이트를 설정하지 않는다(관측만)"
    finally:
        verify.close()


def test_invalidate_by_observation_no_invalid_links_returns_zero(sessionmaker_factory):
    """무효 링크가 없으면 0을 반환하고 건강한 링크는 불변이다(멱등·관측만)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}", is_shareable=True)
        doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        link = _make_share_link(
            session, document_id=doc.id, token=f"h-{uuid4().hex}", is_enabled=True
        )
        session.commit()
        link_id = link.id
        token = link.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        sweep = ShareInvalidationSweep()
        count = sweep.invalidate_by_observation(session)
        assert count == 0, "무효 링크가 없으면 retire 건수는 0"
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row.is_enabled is True and row.token == token, "건강 링크 불변"
    finally:
        verify.close()
