"""ShareLinkRepository 단위 테스트 (Task 1.2 / Req 1.1, 2.1, 2.4, 2.5, 4.1, 5.1, 5.3, 5.6, 7.5).

design.md §Components and Interfaces #ShareLinkRepository(Feature/Data) 계약을 실제 DB 로
검증한다:
- `upsert_reissue` 는 행이 없으면 활성 링크를 새 토큰으로 생성하고(Req 1.1·2.1), 행이 있으면
  **이전과 다른 새 토큰 + is_enabled=True** 로 갱신한다(재발급 통일, Req 2.4·INV-8). created_at 은
  유지한다(재발급이 발급 시각을 되살리지 않음).
- `get_by_document`/`get_by_token` 은 단건을 로드하고 미존재 시 None 을 반환한다(Req 2.1·2.5).
- `set_enabled` 는 `is_enabled` 만 전환하고 **토큰을 유지**한다(토글, 재발급 통일의 유일한 예외,
  Req 4.1).
- `retire` 는 `is_enabled=False` 로 비활성화하고 **토큰을 교체**해 이전 토큰을 영구 무효화한다
  (물리 삭제 없음, Req 5.3·INV-8).
- `list_enabled_invalidatable`(무효화 스코프)는 `is_enabled=True` 이면서 소속 문서가 trashed/
  deleted 이거나 소속 워크스페이스 `is_shareable=False` 인 링크만 열거하고, 이미 비활성 링크·건강한
  링크(active 문서·게이트 on)는 제외한다(멱등 스코프, Req 5.1·5.6·7.5).

상태 전이·게이트 설정은 하지 않는다(관측만). 격리: tests/attachment/test_repository.py 의 확립된
테스트 DB 패턴을 재사용한다. `DB_NAME` 을 전용 테스트 DB(`markspace_test`)로 바꾸고
:func:`app.config.get_settings` 캐시를 비운 뒤 그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료
시 테이블을 모두 제거하고 엔진을 dispose 한 뒤 환경변수·캐시를 원복한다. 공유 테스트 DB 충돌을
피하려 이름/제목에 uuid4 접미사를, DATETIME(0) 반올림을 피하려 초 정밀도 시각을 쓴다.
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
from app.sharing.repository import ShareLinkRepository

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


def _make_workspace(session, *, name="ws", is_shareable=True):
    """Workspace 행을 삽입하고 flush 한다(document/share_link FK 충족용).

    게이트 관측 스코프 검증을 위해 `is_shareable` 를 매개변수로 받는다(기본 게이트 on).
    """
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


# --- upsert_reissue (발급) ------------------------------------------------


def test_upsert_reissue_inserts_active_link_with_token(sessionmaker_factory):
    """행이 없으면 활성 링크를 새 토큰으로 생성·영속화한다(Req 1.1·2.1)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        session.commit()

        repo = ShareLinkRepository()
        link = repo.upsert_reissue(session, doc.id)
        assert link.id is not None, "발급 후 id 가 확정되어야 한다"
        assert link.document_id == doc.id
        assert link.is_enabled is True, "발급 링크는 활성이어야 한다"
        assert link.token, "발급 링크는 토큰을 가져야 한다"
        assert len(link.token) <= 64, "토큰은 VARCHAR(64) 한도 내여야 한다"
        link_id = link.id
        token = link.token
    finally:
        session.close()

    # 새 세션 재조회로 영속화 확인(identity-map 캐시 배제).
    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row is not None
        assert row.token == token
        assert row.is_enabled is True
    finally:
        verify.close()


def test_upsert_reissue_on_existing_row_issues_new_token(sessionmaker_factory):
    """행이 있으면 이전과 다른 새 토큰 + 활성으로 갱신하고 created_at 은 유지한다(Req 2.4·INV-8)."""
    original_created = datetime(2026, 7, 10, 8, 0, 0)
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        # 이전에 무효화(비활성)된 링크가 존재.
        existing = _make_share_link(
            session,
            document_id=doc.id,
            token="old-token-to-be-replaced",
            is_enabled=False,
            created_at=original_created,
        )
        session.commit()
        existing_id = existing.id
        old_token = existing.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = ShareLinkRepository()
        link = repo.upsert_reissue(session, doc.id)
        assert link.id == existing_id, "문서당 링크 행은 최대 1개(같은 행 재사용)"
        assert link.token != old_token, "재발급은 이전 토큰을 되살리지 않고 새 토큰을 만든다"
        assert link.is_enabled is True, "재발급 링크는 활성이어야 한다"
        assert link.created_at == original_created, "재발급은 발급 시각을 유지한다"
        new_token = link.token
    finally:
        session.close()

    # 이전 토큰은 영구 소멸(조회 불가), 새 토큰만 유효.
    verify = sessionmaker_factory()
    try:
        repo = ShareLinkRepository()
        assert repo.get_by_token(verify, old_token) is None
        assert repo.get_by_token(verify, new_token) is not None
    finally:
        verify.close()


def test_upsert_reissue_is_per_document(sessionmaker_factory):
    """한 문서의 재발급이 다른 문서의 링크에 영향을 주지 않는다(Req 2.5)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc_a = _make_document(session, workspace_id=ws.id, created_by=user.id)
        doc_b = _make_document(session, workspace_id=ws.id, created_by=user.id)
        session.commit()

        repo = ShareLinkRepository()
        link_a = repo.upsert_reissue(session, doc_a.id)
        link_b = repo.upsert_reissue(session, doc_b.id)
        token_a_before = link_a.token

        # doc_a 재발급.
        link_a2 = repo.upsert_reissue(session, doc_a.id)
        assert link_a2.token != token_a_before

        # doc_b 링크는 그대로.
        assert repo.get_by_document(session, doc_b.id).token == link_b.token
    finally:
        session.close()


# --- get_by_document / get_by_token --------------------------------------


def test_get_by_document_and_token(sessionmaker_factory):
    """get_by_document·get_by_token 은 존재 링크를 로드하고 미존재 시 None(Req 2.1·2.5)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = _make_share_link(session, document_id=doc.id, token=f"tok-{uuid4().hex}")
        session.commit()
        doc_id = doc.id
        token = link.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = ShareLinkRepository()
        assert repo.get_by_document(session, doc_id) is not None
        assert repo.get_by_document(session, 999_999_999) is None
        assert repo.get_by_token(session, token) is not None
        assert repo.get_by_token(session, "no-such-token") is None
    finally:
        session.close()


# --- set_enabled (토글) ---------------------------------------------------


def test_set_enabled_toggles_flag_keeping_token(sessionmaker_factory):
    """set_enabled 는 is_enabled 만 전환하고 토큰을 유지한다(Req 4.1, 재발급 예외)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = _make_share_link(
            session, document_id=doc.id, token=f"tok-{uuid4().hex}", is_enabled=True
        )
        session.commit()
        link_id = link.id
        token = link.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = ShareLinkRepository()
        link = repo.get_by_document(session, doc.id)
        # 비활성화: 토큰 유지.
        off = repo.set_enabled(session, link, enabled=False)
        assert off.is_enabled is False
        assert off.token == token, "토글은 토큰을 유지한다"
        # 재활성화: 여전히 동일 토큰.
        on = repo.set_enabled(session, link, enabled=True)
        assert on.is_enabled is True
        assert on.token == token, "재활성화도 토큰을 유지한다"
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row.is_enabled is True
        assert row.token == token
    finally:
        verify.close()


# --- retire (무효화 + 토큰 교체) -----------------------------------------


def test_retire_disables_and_replaces_token(sessionmaker_factory):
    """retire 는 is_enabled=False 로 비활성화하고 토큰을 교체한다(물리 삭제 없음, Req 5.3·INV-8)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = _make_share_link(
            session, document_id=doc.id, token="live-token", is_enabled=True
        )
        session.commit()
        link_id = link.id
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = ShareLinkRepository()
        link = repo.get_by_document(session, doc.id)
        old_token = link.token
        retired = repo.retire(session, link)
        assert retired.is_enabled is False, "retire 는 비활성화한다"
        assert retired.token != old_token, "retire 는 토큰을 교체한다"
        new_token = retired.token
    finally:
        session.close()

    # 물리 삭제 없음(행 유지) + 이전 토큰 영구 소멸.
    verify = sessionmaker_factory()
    try:
        repo = ShareLinkRepository()
        row = verify.get(ShareLink, link_id)
        assert row is not None, "retire 는 물리 삭제하지 않는다(행 유지)"
        assert row.is_enabled is False
        assert repo.get_by_token(verify, old_token) is None, "이전 토큰은 영구 소멸"
        assert repo.get_by_token(verify, new_token) is not None
    finally:
        verify.close()


# --- list_enabled_invalidatable (무효화 스코프) --------------------------


def test_list_enabled_invalidatable_scope(sessionmaker_factory):
    """무효화 스코프: 활성이면서 (문서 trashed/deleted OR 게이트 off)인 링크만 열거한다(Req 5.1·5.6·7.5).

    포함: 게이트 on WS 의 trashed·deleted 문서의 활성 링크 + 게이트 off WS 의 active 문서 활성 링크.
    제외: 건강한 링크(게이트 on WS·active 문서), 이미 비활성 링크(문서 trashed 이라도, 멱등).
    """
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws_on = _make_workspace(session, name=f"ws-on-{uuid4().hex}", is_shareable=True)
        ws_off = _make_workspace(
            session, name=f"ws-off-{uuid4().hex}", is_shareable=False
        )

        # 포함: 게이트 on·trashed 문서의 활성 링크.
        trashed_doc = _make_document(
            session, workspace_id=ws_on.id, created_by=user.id, status="trashed"
        )
        inc_trashed = _make_share_link(
            session, document_id=trashed_doc.id, token=f"t-{uuid4().hex}", is_enabled=True
        )
        # 포함: 게이트 on·deleted 문서의 활성 링크.
        deleted_doc = _make_document(
            session, workspace_id=ws_on.id, created_by=user.id, status="deleted"
        )
        inc_deleted = _make_share_link(
            session, document_id=deleted_doc.id, token=f"d-{uuid4().hex}", is_enabled=True
        )
        # 포함: 게이트 off·active 문서의 활성 링크.
        off_doc = _make_document(
            session, workspace_id=ws_off.id, created_by=user.id, status="active"
        )
        inc_gate_off = _make_share_link(
            session, document_id=off_doc.id, token=f"g-{uuid4().hex}", is_enabled=True
        )

        # 제외: 게이트 on·active 문서의 활성 링크(건강).
        healthy_doc = _make_document(
            session, workspace_id=ws_on.id, created_by=user.id, status="active"
        )
        _make_share_link(
            session, document_id=healthy_doc.id, token=f"h-{uuid4().hex}", is_enabled=True
        )
        # 제외: 이미 비활성 링크(문서 trashed 이라도 멱등 스코프).
        trashed_doc2 = _make_document(
            session, workspace_id=ws_on.id, created_by=user.id, status="trashed"
        )
        _make_share_link(
            session,
            document_id=trashed_doc2.id,
            token=f"x-{uuid4().hex}",
            is_enabled=False,
        )
        session.commit()
        expected = {inc_trashed.id, inc_deleted.id, inc_gate_off.id}
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = ShareLinkRepository()
        rows = repo.list_enabled_invalidatable(session)
        ids = {link.id for link in rows}
        assert ids == expected, (
            "활성이면서 (문서 trashed/deleted 또는 게이트 off)인 링크만 포함; "
            "건강한 링크·이미 비활성 링크는 제외되어야 한다"
        )
        assert all(link.is_enabled is True for link in rows), "비활성 링크는 스코프 밖"
        # 결정적 순서(id 오름차순) 확인.
        assert [link.id for link in rows] == sorted(ids)
    finally:
        session.close()
