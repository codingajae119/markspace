"""ShareLinkService 단위 테스트 (Task 2.1 / Req 1.1, 1.2, 1.3, 1.4, 2.1, 2.4, 2.5, 4.1, 4.2, 4.3).

design.md §Components and Interfaces #ShareLinkService(Feature/Service) 계약과 §System Flows
(발급·재발급 flowchart, 토글 flowchart)을 실제 DB 로 검증한다:

- **issue_link**(발급/재발급): 대상 문서 존재 확인(부재→404), 문서 status 가 active 인지(비active→
  409)·소속 워크스페이스 `is_shareable` 가 true 인지(게이트 off→409, 7.1) 검사 후 `upsert_reissue`
  로 새 토큰·활성 링크를 발급한다(Req 1.1·1.4·2.1). 무효화 이후 재발급은 이전과 다른 새 토큰
  (INV-8·§4.5, Req 2.4).
- **toggle_link**(토글): 문서 링크 로드(부재→404). `is_enabled=false` 요청은 항상 허용(토큰 유지);
  `is_enabled=true` 요청은 게이트 on·문서 active 일 때만 허용(아니면 409, 토큰 유지). 토글은 새
  토큰을 만들지 않는 유일한 상태 기반 예외다(Req 4.1·4.2·4.3, 7.7).

관측만 한다(상태 전이·게이트 설정 없음). 격리: tests/sharing/test_repository.py 의 확립된 테스트
DB 패턴(전용 `notion_lite_test`, 캐시 원복, 종료 시 drop·dispose)을 재사용한다. 공유 테스트 DB
충돌을 피하려 이름/제목에 uuid4 접미사를, DATETIME(0) 반올림을 피하려 초 정밀도 시각을 쓴다.
"""

import os
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.errors import DomainError, ErrorCode
from app.common.db import Base
from app.models import Document, ShareLink, User, Workspace
from app.sharing.schemas import ShareLinkRead, ShareLinkUpdate
from app.sharing.service import ShareLinkService

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
    """Workspace 행을 삽입하고 flush 한다(게이트 관측 스코프 검증용, 기본 게이트 on)."""
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
    """Document 행을 직접 삽입하고 flush 한다(링크 시드용)."""
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


def _make_share_link(session, *, document_id, token=None, is_enabled=True):
    """ShareLink 행을 직접 삽입하고 flush 한다(토글 시드용)."""
    link = ShareLink(
        document_id=document_id,
        token=token or uuid4().hex,
        is_enabled=is_enabled,
        created_at=datetime(2026, 7, 17, 9, 0, 0),
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


def _seed_doc(session, *, is_shareable=True, status="active"):
    """user·workspace·document 를 시드하고 commit 한 뒤 문서를 반환한다."""
    user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
    ws = _make_workspace(
        session, name=f"ws-{uuid4().hex}", is_shareable=is_shareable
    )
    doc = _make_document(
        session, workspace_id=ws.id, created_by=user.id, status=status
    )
    session.commit()
    return doc


# --- issue_link (발급/재발급) --------------------------------------------


def test_issue_link_on_gate_on_active_returns_active_link_with_token(
    sessionmaker_factory,
):
    """게이트 on·active 문서에서 발급이 새 토큰의 활성 링크를 반환한다(Req 1.1·1.4·2.1)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")

        service = ShareLinkService()
        read = service.issue_link(session, ctx=None, document_id=doc.id)

        assert isinstance(read, ShareLinkRead)
        assert read.document_id == doc.id
        assert read.is_enabled is True, "발급 링크는 활성이어야 한다"
        assert read.token, "발급 링크는 토큰을 가져야 한다"
        assert read.share_url == f"/public/{read.token}", "share_url 규약(/public/{token})"
        link_id = read.id
        token = read.token
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


def test_issue_link_on_gate_off_raises_409(sessionmaker_factory):
    """게이트 off 워크스페이스에서 발급은 409(conflict)로 거부된다(Req 1.1, 7.1)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=False, status="active")

        service = ShareLinkService()
        with pytest.raises(DomainError) as exc:
            service.issue_link(session, ctx=None, document_id=doc.id)
        assert exc.value.http_status == 409
        assert exc.value.code == ErrorCode.CONFLICT

        # 게이트 off 발급은 링크를 만들지 않는다.
        assert (
            session.scalar(
                text("SELECT COUNT(*) FROM share_link WHERE document_id = :d")
                .bindparams(d=doc.id)
            )
            == 0
        )
    finally:
        session.close()


def test_issue_link_on_non_active_document_raises_409(sessionmaker_factory):
    """비active(trashed) 문서에서 발급은 409(conflict)로 거부된다(Req 1.4)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="trashed")

        service = ShareLinkService()
        with pytest.raises(DomainError) as exc:
            service.issue_link(session, ctx=None, document_id=doc.id)
        assert exc.value.http_status == 409
        assert exc.value.code == ErrorCode.CONFLICT
    finally:
        session.close()


def test_issue_link_on_missing_document_raises_404(sessionmaker_factory):
    """존재하지 않는 문서 발급은 404(not_found)로 거부된다(Req 2.1 부재)."""
    session = sessionmaker_factory()
    try:
        service = ShareLinkService()
        with pytest.raises(DomainError) as exc:
            service.issue_link(session, ctx=None, document_id=999_999_999)
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


def test_reissue_after_invalidation_yields_new_token(sessionmaker_factory):
    """무효화된 문서의 재발급은 이전과 다른 새 토큰을 만든다(INV-8·§4.5, Req 2.4)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")

        service = ShareLinkService()
        first = service.issue_link(session, ctx=None, document_id=doc.id)
        first_token = first.token

        # 이전 링크가 무효화(비활성)되어도 재발급은 이전 토큰을 되살리지 않는다.
        link = session.scalar(
            text("SELECT id FROM share_link WHERE document_id = :d").bindparams(
                d=doc.id
            )
        )
        session.execute(
            text("UPDATE share_link SET is_enabled = 0 WHERE id = :i").bindparams(
                i=link
            )
        )
        session.commit()

        second = service.issue_link(session, ctx=None, document_id=doc.id)
        assert second.token != first_token, "재발급은 이전 토큰과 다른 새 토큰"
        assert second.is_enabled is True, "재발급 링크는 활성"
        assert second.id == first.id, "문서당 링크 행은 최대 1개(같은 행 재사용)"
    finally:
        session.close()


# --- toggle_link (토글) ---------------------------------------------------


def test_toggle_off_then_on_keeps_same_token_and_flips_state(sessionmaker_factory):
    """토글 off→on 이 토큰을 유지한 채 상태만 전환한다(Req 4.1·4.2·4.3, 토큰 유지)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")
        link = _make_share_link(
            session, document_id=doc.id, token=f"tok-{uuid4().hex}", is_enabled=True
        )
        session.commit()
        original_token = link.token

        service = ShareLinkService()
        # 비활성화: 항상 허용, 토큰 유지.
        off = service.toggle_link(
            session, document_id=doc.id, payload=ShareLinkUpdate(is_enabled=False)
        )
        assert off.is_enabled is False
        assert off.token == original_token, "토글은 토큰을 유지한다"

        # 재활성화(게이트 on·active): 허용, 여전히 동일 토큰.
        on = service.toggle_link(
            session, document_id=doc.id, payload=ShareLinkUpdate(is_enabled=True)
        )
        assert on.is_enabled is True
        assert on.token == original_token, "재활성화도 토큰을 유지한다"
    finally:
        session.close()


def test_toggle_on_when_gate_off_raises_409_keeping_token(sessionmaker_factory):
    """게이트 off 에서 활성화 토글은 409 이며 토큰·상태를 유지한다(Req 4.2, 7.1)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=False, status="active")
        link = _make_share_link(
            session, document_id=doc.id, token=f"tok-{uuid4().hex}", is_enabled=False
        )
        session.commit()
        link_id = link.id
        original_token = link.token

        service = ShareLinkService()
        with pytest.raises(DomainError) as exc:
            service.toggle_link(
                session,
                document_id=doc.id,
                payload=ShareLinkUpdate(is_enabled=True),
            )
        assert exc.value.http_status == 409
        assert exc.value.code == ErrorCode.CONFLICT
    finally:
        session.close()

    # 실패한 활성화는 상태·토큰을 바꾸지 않는다.
    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row.is_enabled is False, "활성화 실패는 상태를 유지"
        assert row.token == original_token, "활성화 실패는 토큰을 유지"
    finally:
        verify.close()


def test_toggle_on_when_document_non_active_raises_409(sessionmaker_factory):
    """비active 문서에서 활성화 토글은 409 로 거부된다(Req 4.2)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="trashed")
        _make_share_link(
            session, document_id=doc.id, token=f"tok-{uuid4().hex}", is_enabled=False
        )
        session.commit()

        service = ShareLinkService()
        with pytest.raises(DomainError) as exc:
            service.toggle_link(
                session,
                document_id=doc.id,
                payload=ShareLinkUpdate(is_enabled=True),
            )
        assert exc.value.http_status == 409
        assert exc.value.code == ErrorCode.CONFLICT
    finally:
        session.close()


def test_toggle_off_always_allowed_even_when_gate_off(sessionmaker_factory):
    """게이트 off 여도 비활성화 토글은 항상 허용된다(토큰 유지, Req 4.1·4.3)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=False, status="trashed")
        link = _make_share_link(
            session, document_id=doc.id, token=f"tok-{uuid4().hex}", is_enabled=True
        )
        session.commit()
        original_token = link.token

        service = ShareLinkService()
        off = service.toggle_link(
            session, document_id=doc.id, payload=ShareLinkUpdate(is_enabled=False)
        )
        assert off.is_enabled is False, "비활성화는 게이트와 무관하게 허용"
        assert off.token == original_token, "토큰 유지"
    finally:
        session.close()


def test_toggle_on_missing_link_raises_404(sessionmaker_factory):
    """링크가 없는 문서의 토글은 404 로 거부된다(Req 4.1 부재)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")

        service = ShareLinkService()
        with pytest.raises(DomainError) as exc:
            service.toggle_link(
                session,
                document_id=doc.id,
                payload=ShareLinkUpdate(is_enabled=True),
            )
        assert exc.value.http_status == 404
        assert exc.value.code == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- get_link (읽기 전용 상태 조회) ---------------------------------------


def test_get_link_when_link_exists_returns_read_with_token_and_url(
    sessionmaker_factory,
):
    """링크가 있으면 token·is_enabled·share_url 을 담은 ShareLinkRead 를 반환한다(Req 1.1)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")
        link = _make_share_link(
            session,
            document_id=doc.id,
            token=f"tok-{uuid4().hex}",
            is_enabled=True,
        )
        session.commit()
        seeded_token = link.token

        service = ShareLinkService()
        read = service.get_link(session, document_id=doc.id)

        assert isinstance(read, ShareLinkRead)
        assert read.document_id == doc.id
        assert read.token == seeded_token, "조회는 기존 토큰을 그대로 반환한다"
        assert read.is_enabled is True
        assert read.share_url == f"/public/{seeded_token}", (
            "share_url 규약(/public/{token})"
        )
    finally:
        session.close()


def test_get_link_reflects_disabled_state(sessionmaker_factory):
    """비활성 링크도 오류 없이 is_enabled=False 로 그대로 반영한다(Req 1.1·1.2)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")
        _make_share_link(
            session,
            document_id=doc.id,
            token=f"tok-{uuid4().hex}",
            is_enabled=False,
        )
        session.commit()

        service = ShareLinkService()
        read = service.get_link(session, document_id=doc.id)

        assert isinstance(read, ShareLinkRead)
        assert read.is_enabled is False, "비활성 링크 상태를 그대로 반영한다"
    finally:
        session.close()


def test_get_link_when_no_link_returns_none(sessionmaker_factory):
    """링크가 없으면 오류가 아니라 None(링크 없음)을 반환한다(Req 1.2)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")

        service = ShareLinkService()
        read = service.get_link(session, document_id=doc.id)

        assert read is None, "링크 없음은 오류가 아니라 None 정상 응답"
    finally:
        session.close()


def test_get_link_is_read_only_leaves_row_unchanged(sessionmaker_factory):
    """조회 전후로 링크 행·토큰·활성 상태가 불변이다(읽기 전용, Req 1.3)."""
    session = sessionmaker_factory()
    try:
        doc = _seed_doc(session, is_shareable=True, status="active")
        link = _make_share_link(
            session,
            document_id=doc.id,
            token=f"tok-{uuid4().hex}",
            is_enabled=True,
        )
        session.commit()
        link_id = link.id
        before_token = link.token
        before_enabled = link.is_enabled

        service = ShareLinkService()
        service.get_link(session, document_id=doc.id)
    finally:
        session.close()

    # 새 세션 재조회로 상태 전이·물리 변경이 전혀 없었음을 확인(identity-map 배제).
    verify = sessionmaker_factory()
    try:
        rows = list(
            verify.scalars(
                text("SELECT id FROM share_link WHERE document_id = :d").bindparams(
                    d=doc.id
                )
            )
        )
        assert len(rows) == 1, "조회는 링크 행을 추가·삭제하지 않는다"

        row = verify.get(ShareLink, link_id)
        assert row is not None
        assert row.token == before_token, "조회는 토큰을 바꾸지 않는다"
        assert row.is_enabled == before_enabled, "조회는 활성 상태를 바꾸지 않는다"
    finally:
        verify.close()
