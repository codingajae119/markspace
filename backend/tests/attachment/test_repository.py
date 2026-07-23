"""AttachmentRepository 단위 테스트 (Task 1.3 / Req 1.3, 3.2, 4.1, 4.4, 4.5, 5.1, 5.5).

design.md §Components and Interfaces #AttachmentRepository(Feature/Data) 계약을 실제 DB 로
검증한다:
- `insert` 는 첨부를 `is_archived=False` 로 생성·영속화하고 id 가 확정된 행을 반환한다(1.3).
- `get` 은 단건을 로드하고 미존재 시 None 을 반환한다(서빙·게이트용).
- `mark_archived` 는 `file_path` 를 보관 경로로 갱신하고 `is_archived=True` 로 표시한다(관측
  전용, 물리 삭제 없음). 새 세션 재조회로 영속화를 확인한다.
- `list_unarchived_on_deleted_documents`(8.6 스코프)는 미보관이며 소속 문서가 deleted 인 첨부만
  열거하고, 이미 보관된 첨부·비-deleted 문서 첨부는 제외한다(멱등, Req 4.1·4.4·4.5).
- `list_unarchived_images_with_current_version`(8.7 스코프)는 미보관 image 이며 소속 문서가
  active/trashed 이고 current_version 이 존재하는 첨부와 그 현재 버전 메타(id·created_at)만
  열거하고, 보관된 첨부·kind=file·current_version_id NULL·deleted 문서는 제외한다(Req 5.1·5.5).

상태 전이·버전 생성은 하지 않는다(관측만). 격리: tests/trash/test_repository.py 의 확립된 테스트
DB 패턴을 재사용한다. `DB_NAME` 을 전용 테스트 DB(`markspace_test`)로 바꾸고
:func:`app.config.get_settings` 캐시를 비운 뒤 그 시점 URL 로 새 엔진·세션 팩토리를 만든다.
종료 시 테이블을 모두 제거하고 엔진을 dispose 한 뒤 환경변수·캐시를 원복한다. 공유 테스트 DB
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
from app.attachment.repository import AttachmentRepository
from app.common.db import Base
from app.models import Attachment, Document, DocumentVersion, User, Workspace

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


def _make_workspace(session, *, name="ws"):
    """Workspace 행을 삽입하고 flush 한다(attachment/document FK 충족용)."""
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
    title="문서",
    status="active",
    sort_order=Decimal("1000"),
):
    """Document 행을 직접 삽입하고 flush 한다(스코프 시드용)."""
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


def _make_version(session, *, document_id, created_by, content="본문", created_at):
    """DocumentVersion 행을 삽입하고 flush 한다(current_version 메타 시드용)."""
    ver = DocumentVersion(
        document_id=document_id,
        content=content,
        created_by=created_by,
        created_at=created_at,
    )
    session.add(ver)
    session.flush()
    return ver


def _make_attachment(
    session,
    *,
    workspace_id,
    document_id,
    kind="image",
    file_path=None,
    original_name="orig.png",
    is_archived=False,
    created_at=None,
):
    """Attachment 행을 직접 삽입하고 flush 한다(스코프 시드용)."""
    att = Attachment(
        workspace_id=workspace_id,
        document_id=document_id,
        file_path=file_path or f"{workspace_id}/{uuid4().hex}.png",
        original_name=original_name,
        kind=kind,
        is_archived=is_archived,
        created_at=created_at or datetime(2026, 7, 17, 9, 0, 0),
    )
    session.add(att)
    session.flush()
    return att


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


def test_insert_persists_unarchived_and_assigns_id(sessionmaker_factory):
    """insert 는 is_archived=False 로 첨부를 영속화하고 id 확정 행을 반환한다(Req 1.3)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        session.commit()

        repo = AttachmentRepository()
        att = repo.insert(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            file_path=f"{ws.id}/img.png",
            original_name="사진.png",
            kind="image",
        )
        assert att.id is not None, "삽입 후 id 가 확정되어야 한다"
        assert att.is_archived is False, "신규 첨부는 미보관이어야 한다"
        att_id = att.id
    finally:
        session.close()

    # 새 세션에서 재조회해 영속화를 확인(identity-map 캐시 배제).
    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row is not None
        assert row.original_name == "사진.png"
        assert row.kind == "image"
        assert row.file_path == f"{ws.id}/img.png"
        assert row.is_archived is False
    finally:
        verify.close()


# --- get -----------------------------------------------------------------


def test_get_returns_row_and_none_for_missing(sessionmaker_factory):
    """get 은 존재 첨부를 로드하고 미존재 id 에는 None 을 반환한다."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        att = _make_attachment(
            session, workspace_id=ws.id, document_id=doc.id
        )
        session.commit()
        att_id = att.id
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = AttachmentRepository()
        assert repo.get(session, att_id) is not None
        assert repo.get(session, 999_999_999) is None
    finally:
        session.close()


# --- mark_archived -------------------------------------------------------


def test_mark_archived_flips_flag_and_updates_path(sessionmaker_factory):
    """mark_archived 는 file_path 갱신·is_archived=True 로 표시하고 영속화한다(Req 4.1)."""
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        doc = _make_document(session, workspace_id=ws.id, created_by=user.id)
        att = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=doc.id,
            file_path=f"{ws.id}/live.png",
            is_archived=False,
        )
        session.commit()
        att_id = att.id
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = AttachmentRepository()
        att = repo.get(session, att_id)
        archived_path = f"{ws.id}/archive/live.png"
        result = repo.mark_archived(session, att, archived_path=archived_path)
        assert result.is_archived is True
        assert result.file_path == archived_path
    finally:
        session.close()

    # 새 세션 재조회로 영속화 확인(캐시 아님).
    verify = sessionmaker_factory()
    try:
        row = verify.get(Attachment, att_id)
        assert row.is_archived is True
        assert row.file_path == f"{ws.id}/archive/live.png"
    finally:
        verify.close()


# --- 8.6 scope: list_unarchived_on_deleted_documents ---------------------


def test_list_unarchived_on_deleted_documents_scope(sessionmaker_factory):
    """8.6 스코프: 미보관·deleted 문서 첨부만 열거하고 나머지는 제외한다(Req 4.1·4.4·4.5).

    포함: 미보관 첨부(deleted 문서). 제외: 보관 첨부(deleted 문서, 멱등),
    미보관 첨부(active/trashed 문서).
    """
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        active_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        trashed_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="trashed"
        )
        # 포함 대상: deleted 문서의 미보관 첨부.
        included = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            is_archived=False,
        )
        # 제외: deleted 문서지만 이미 보관됨(멱등).
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            is_archived=True,
        )
        # 제외: 미보관이나 문서가 deleted 아님.
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=active_doc.id,
            is_archived=False,
        )
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=trashed_doc.id,
            is_archived=False,
        )
        session.commit()
        included_id = included.id
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = AttachmentRepository()
        rows = repo.list_unarchived_on_deleted_documents(session)
        ids = {a.id for a in rows}
        assert included_id in ids, "deleted 문서의 미보관 첨부는 포함되어야 한다"
        assert len(ids) == 1, "보관 첨부·비-deleted 문서 첨부는 모두 제외되어야 한다"
        assert all(a.is_archived is False for a in rows)
    finally:
        session.close()


# --- 8.7 scope: list_unarchived_images_with_current_version --------------


def test_list_unarchived_images_with_current_version_scope(sessionmaker_factory):
    """8.7 스코프: 미보관 image·active/trashed·current_version 존재 첨부만 열거한다(Req 5.1·5.5).

    포함: active 문서의 미보관 image(현재 버전 존재) + 그 현재 버전 메타(id·created_at),
    trashed 문서의 미보관 image(현재 버전 존재).
    제외: 보관된 image, kind=file, current_version_id NULL 문서, deleted 문서.
    """
    ver_created = datetime(2026, 7, 17, 8, 30, 0)
    session = sessionmaker_factory()
    try:
        user = _make_user(session, login_id=f"u-{uuid4().hex[:12]}")
        ws = _make_workspace(session, name=f"ws-{uuid4().hex}")

        # active 문서 + 현재 버전.
        active_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )
        active_ver = _make_version(
            session,
            document_id=active_doc.id,
            created_by=user.id,
            created_at=ver_created,
        )
        active_doc.current_version_id = active_ver.id
        session.flush()

        # trashed 문서 + 현재 버전.
        trashed_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="trashed"
        )
        trashed_ver = _make_version(
            session,
            document_id=trashed_doc.id,
            created_by=user.id,
            created_at=ver_created,
        )
        trashed_doc.current_version_id = trashed_ver.id
        session.flush()

        # current_version 없는 active 문서.
        no_ver_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="active"
        )

        # deleted 문서 + 현재 버전(8.6 소관이므로 8.7 제외).
        deleted_doc = _make_document(
            session, workspace_id=ws.id, created_by=user.id, status="deleted"
        )
        deleted_ver = _make_version(
            session,
            document_id=deleted_doc.id,
            created_by=user.id,
            created_at=ver_created,
        )
        deleted_doc.current_version_id = deleted_ver.id
        session.flush()

        # 포함: active 문서의 미보관 image.
        inc_active = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=active_doc.id,
            kind="image",
            is_archived=False,
        )
        # 포함: trashed 문서의 미보관 image.
        inc_trashed = _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=trashed_doc.id,
            kind="image",
            is_archived=False,
        )
        # 제외: 보관된 image(active 문서).
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=active_doc.id,
            kind="image",
            is_archived=True,
        )
        # 제외: kind=file(active 문서).
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=active_doc.id,
            kind="file",
            is_archived=False,
        )
        # 제외: current_version_id NULL 문서.
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=no_ver_doc.id,
            kind="image",
            is_archived=False,
        )
        # 제외: deleted 문서(8.6 소관).
        _make_attachment(
            session,
            workspace_id=ws.id,
            document_id=deleted_doc.id,
            kind="image",
            is_archived=False,
        )
        session.commit()
        inc_active_id = inc_active.id
        inc_trashed_id = inc_trashed.id
        active_ver_id = active_ver.id
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = AttachmentRepository()
        rows = repo.list_unarchived_images_with_current_version(session)
        by_att = {att.id: (ver_id, ver_at) for att, ver_id, ver_at in rows}

        assert inc_active_id in by_att, "active·미보관 image·현재버전 존재는 포함"
        assert inc_trashed_id in by_att, "trashed·미보관 image·현재버전 존재는 포함"
        assert len(by_att) == 2, (
            "보관 image·kind=file·current_version NULL·deleted 문서는 제외되어야 한다"
        )

        # 현재 버전 메타(id·created_at)가 정확히 반환되는지 확인.
        ver_id, ver_at = by_att[inc_active_id]
        assert ver_id == active_ver_id
        assert ver_at == ver_created

        # 반환된 첨부는 전부 미보관 image.
        for att, _vid, _vat in rows:
            assert att.is_archived is False
            assert att.kind == "image"
    finally:
        session.close()
