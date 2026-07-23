"""PublicShareService.render_public_document 단위 테스트
(Task 2.2 / Req 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.2, 7.7).

design.md §Components and Interfaces #PublicShareService(Feature/Service) 계약을 실제 DB 로
검증한다:
- 활성 링크(is_enabled·문서 active·게이트 on) 접근은 문서 + 현재 active 하위 트리를 안전 렌더로
  반환한다(Req 3.1·3.2). 최소 노출: id·title·content_html·children 만 노출한다(Req 7.1 계약).
- 하위 추가 후 재요청 시 새 하위가 동적으로 포함되고(Req 3.4), trashed 하위는 제외된다(Req 3.5).
- 문서 trashed·게이트 off 접근은 404 이며 그 관측이 링크를 retire(비활성 + 토큰 교체)로 영구화
  한다(lazy retire, Req 5.1·5.2·INV-8). 이미 비활성 링크는 re-retire 하지 않는다(멱등 스코프).
- 미존재 토큰은 404(Req 3.6, 정보 비노출).
- content_html 의 `/attachments/{id}` 참조는 `/public/{token}/attachments/{id}` 로 재작성되며
  id 경계를 정확히 구분한다(Req 8.4 이미지 로딩; `/attachments/5` 와 `/attachments/50` 비오염).
- markdown 의 `<script>`/`onerror` 는 s07 안전 렌더로 제거된다(Req 3.2, XSS 방지).

격리: tests/sharing/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. 공유 테스트 DB
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
from app.common.db import Base
from app.common.errors import ErrorCode
from app.models import Document, DocumentVersion, ShareLink, User, Workspace
from app.sharing.public_service import PublicShareService
from app.sharing.repository import ShareLinkRepository
from app.sharing.schemas import PublicDocumentNode

TEST_DB_NAME = "markspace_test"

# DATETIME(0) 반올림을 피하기 위한 초 정밀도 고정 시각.
_FIXED_TIME = datetime(2026, 7, 17, 9, 0, 0)


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
    user = User(
        login_id=login_id,
        password_hash="hash-initial",
        name="테스트 사용자",
        email=None,
        is_admin=False,
        is_active=True,
        is_deleted=False,
        created_at=_FIXED_TIME,
    )
    session.add(user)
    session.flush()
    return user


def _make_workspace(session, *, name="ws", is_shareable=True):
    ws = Workspace(
        name=name,
        is_shareable=is_shareable,
        trash_retention_days=30,
        created_at=_FIXED_TIME,
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
    doc = Document(
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        created_by=created_by,
        created_at=_FIXED_TIME,
    )
    session.add(doc)
    session.flush()
    return doc


def _set_content(session, *, document, content, created_by):
    """문서에 현재 버전을 만들어 본문(markdown)을 붙인다(current_version_id 지정)."""
    version = DocumentVersion(
        document_id=document.id,
        content=content,
        created_by=created_by,
        created_at=_FIXED_TIME,
    )
    session.add(version)
    session.flush()
    document.current_version_id = version.id
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

    _drop_everything(engine)
    Base.metadata.create_all(engine)

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


# --- (a) 활성 링크 → 루트 + active 하위 트리 안전 렌더 ---------------------


def test_active_link_returns_root_with_active_subtree(sessionmaker_factory):
    """활성 링크 접근은 문서 + 현재 active 하위 트리를 안전 렌더로 반환한다(Req 3.1·3.2)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(
            session, workspace_id=ws.id, created_by=user.id, title="루트"
        )
        child = _make_document(
            session,
            workspace_id=ws.id,
            created_by=user.id,
            parent_id=root.id,
            title="자식",
            sort_order=Decimal("2000"),
        )
        _set_content(session, document=root, content="# 루트 본문", created_by=user.id)
        _set_content(session, document=child, content="자식 본문", created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        root_id, child_id = root.id, child.id
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        result = PublicShareService().render_public_document(session, token)
        assert result.root.id == root_id
        assert result.root.title == "루트"
        assert "<h1>루트 본문</h1>" in result.root.content_html
        assert len(result.root.children) == 1
        assert result.root.children[0].id == child_id
        assert "자식 본문" in result.root.children[0].content_html
        # 최소 노출: 노드 필드가 id·title·content_html·children 만 존재.
        assert set(PublicDocumentNode.model_fields) == {
            "id",
            "title",
            "content_html",
            "children",
        }
    finally:
        session.close()


def test_document_without_current_version_renders_empty_html(sessionmaker_factory):
    """현재 버전이 없는 문서는 빈 content_html 로 렌더된다(load_current_content 규약)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        result = PublicShareService().render_public_document(session, token)
        assert result.root.content_html == ""
        assert result.root.children == []
    finally:
        session.close()


# --- (b) 하위 추가 → 동적 포함 --------------------------------------------


def test_added_child_is_dynamically_included(sessionmaker_factory):
    """하위 추가 후 재요청 시 새 하위가 트리에 동적으로 포함된다(Req 3.4)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        root_id = root.id
    finally:
        session.close()

    # 최초 요청: 하위 없음.
    session = sessionmaker_factory()
    try:
        result = PublicShareService().render_public_document(session, token)
        assert result.root.children == []
    finally:
        session.close()

    # 하위 문서 추가.
    session = sessionmaker_factory()
    try:
        user = session.scalar(select_first(User))
        child = _make_document(
            session,
            workspace_id=session.get(Document, root_id).workspace_id,
            created_by=user.id,
            parent_id=root_id,
            title="새 하위",
        )
        session.commit()
        child_id = child.id
    finally:
        session.close()

    # 재요청: 새 하위가 동적 포함.
    session = sessionmaker_factory()
    try:
        result = PublicShareService().render_public_document(session, token)
        assert [c.id for c in result.root.children] == [child_id]
    finally:
        session.close()


# --- (c) trashed 하위 제외 -------------------------------------------------


def test_trashed_child_is_excluded(sessionmaker_factory):
    """trashed 상태의 하위는 트리에서 제외된다(Req 3.5)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        child = _make_document(
            session,
            workspace_id=ws.id,
            created_by=user.id,
            parent_id=root.id,
            title="자식",
        )
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        child_id = child.id
    finally:
        session.close()

    # 하위 존재 확인.
    session = sessionmaker_factory()
    try:
        result = PublicShareService().render_public_document(session, token)
        assert [c.id for c in result.root.children] == [child_id]
    finally:
        session.close()

    # 하위 trashed 처리.
    session = sessionmaker_factory()
    try:
        child = session.get(Document, child_id)
        child.status = "trashed"
        session.commit()
    finally:
        session.close()

    # trashed 하위 제외.
    session = sessionmaker_factory()
    try:
        result = PublicShareService().render_public_document(session, token)
        assert result.root.children == []
    finally:
        session.close()


# --- (d) 문서 trashed → 404 + lazy retire ---------------------------------


def test_trashed_document_raises_404_and_retires_link(sessionmaker_factory):
    """문서 trashed 접근은 404 이며 링크를 retire(비활성 + 토큰 교체)로 영구화한다(Req 5.1·INV-8)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        link_id = link.id
        root_id = root.id
    finally:
        session.close()

    # 문서 trashed 처리(s07/s10 이 만든 상태를 관측).
    session = sessionmaker_factory()
    try:
        session.get(Document, root_id).status = "trashed"
        session.commit()
    finally:
        session.close()

    # 무효 접근 → 404.
    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().render_public_document(session, token)
        assert getattr(exc.value, "http_status", None) == 404
        assert getattr(exc.value, "code", None) == ErrorCode.NOT_FOUND
    finally:
        session.close()

    # lazy retire 관측: is_enabled False + 토큰 교체(이전 토큰 조회 불가).
    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row is not None, "retire 는 물리 삭제하지 않는다"
        assert row.is_enabled is False
        assert row.token != token, "retire 는 토큰을 교체한다"
        assert (
            ShareLinkRepository().get_by_token(verify, token) is None
        ), "이전 토큰은 영구 소멸(재발급 필요, INV-8)"
    finally:
        verify.close()


# --- (e) 게이트 off → 404 + lazy retire ------------------------------------


def test_gate_off_raises_404_and_retires_link(sessionmaker_factory):
    """게이트 off(is_shareable=False) 접근은 404 이며 링크를 retire 한다(Req 5.2·INV-8)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}", is_shareable=True)
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
        link_id = link.id
        ws_id = ws.id
    finally:
        session.close()

    # 게이트 off(s05 가 만든 상태를 관측).
    session = sessionmaker_factory()
    try:
        session.get(Workspace, ws_id).is_shareable = False
        session.commit()
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().render_public_document(session, token)
        assert getattr(exc.value, "http_status", None) == 404
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row.is_enabled is False
        assert row.token != token
    finally:
        verify.close()


# --- 이미 비활성 링크 → 404, re-retire 없음(멱등) -------------------------


def test_disabled_link_raises_404_without_reretire(sessionmaker_factory):
    """이미 비활성(is_enabled=False) 링크 접근은 404 이며 토큰을 다시 교체하지 않는다(멱등)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        link = ShareLink(
            document_id=root.id,
            token=f"disabled-{uuid4().hex}",
            is_enabled=False,
            created_at=_FIXED_TIME,
        )
        session.add(link)
        session.flush()
        session.commit()
        token = link.token
        link_id = link.id
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().render_public_document(session, token)
        assert getattr(exc.value, "http_status", None) == 404
    finally:
        session.close()

    # 비활성 링크는 re-retire 하지 않으므로 토큰이 유지된다(retire 스코프=enabled-only).
    verify = sessionmaker_factory()
    try:
        row = verify.get(ShareLink, link_id)
        assert row.is_enabled is False
        assert row.token == token, "이미 비활성 링크는 토큰을 다시 교체하지 않는다"
    finally:
        verify.close()


# --- (f) 미존재 토큰 → 404 -------------------------------------------------


def test_unknown_token_raises_404(sessionmaker_factory):
    """존재하지 않는 토큰 접근은 404 를 반환한다(Req 3.6, 정보 비노출)."""
    session = sessionmaker_factory()
    try:
        with pytest.raises(Exception) as exc:
            PublicShareService().render_public_document(session, "no-such-token")
        assert getattr(exc.value, "http_status", None) == 404
        assert getattr(exc.value, "code", None) == ErrorCode.NOT_FOUND
    finally:
        session.close()


# --- (g) 첨부 참조 재작성 + id 경계 ---------------------------------------


def test_attachment_refs_rewritten_to_link_scope(sessionmaker_factory):
    """content_html 의 `/attachments/{id}` 참조가 링크 스코프 경로로 재작성되며 id 경계를 구분한다(Req 8.4)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        _set_content(
            session,
            document=root,
            content="![i](/attachments/5) 그리고 ![j](/attachments/50)",
            created_by=user.id,
        )
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        result = PublicShareService().render_public_document(session, token)
        html = result.root.content_html
        # 링크 스코프로 재작성됨(id 경계 정확: 5 와 50 이 서로 오염되지 않음).
        assert f"/public/{token}/attachments/5" in html
        assert f"/public/{token}/attachments/50" in html
        # 재작성 경로를 제거하면 bare `/attachments/` 참조가 남지 않아야 한다.
        stripped = html.replace(f"/public/{token}/attachments/", "")
        assert "/attachments/" not in stripped, "bare 첨부 참조가 남으면 안 된다"
    finally:
        session.close()


# --- (h) 안전 렌더(script/onerror 제거) -----------------------------------


def test_render_strips_script_and_event_handlers(sessionmaker_factory):
    """markdown 의 `<script>`/`onerror` 는 s07 안전 렌더로 제거된다(Req 3.2, XSS 방지)."""
    dangerous = (
        "# 제목\n\n본문 <script>alert('xss')</script> 그리고 "
        "<b onerror=alert(1)>굵게</b>"
    )
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        root = _make_document(session, workspace_id=ws.id, created_by=user.id)
        _set_content(session, document=root, content=dangerous, created_by=user.id)
        link = ShareLinkRepository().upsert_reissue(session, root.id)
        session.commit()
        token = link.token
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        html = PublicShareService().render_public_document(session, token).root.content_html
        lowered = html.lower()
        assert "<script" not in lowered, "script 태그가 제거되어야 한다"
        assert "onerror" not in lowered, "이벤트 핸들러가 제거되어야 한다"
        assert "굵게" in html, "안전한 서식 내용은 보존되어야 한다"
    finally:
        session.close()


def select_first(model):
    """가장 먼저 삽입된 행 하나를 얻는 편의 select(테스트 헬퍼)."""
    from sqlalchemy import select

    return select(model).order_by(model.id).limit(1)
