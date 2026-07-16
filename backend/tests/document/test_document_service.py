"""DocumentService 단위 테스트 (Task 2.1 / Req 1.1~1.5, 2.1, 2.3, 2.4, 2.7).

design.md §Components → DocumentService 계약(Contracts·Preconditions/Postconditions)과
§Error Handling error table(404 부재·409 상태/WS 위반)을 검증한다. 이 task 범위는 생성·
조회·목록 세 메서드이며 상태 전이(삭제 등)는 엔진 위임(후속 task)이라 여기서 다루지 않는다.

세션(`db`)은 메서드별 인자로 전달받는 계약이므로 가짜 repo 는 각 메서드의 첫 인자로 `db`
를 받는다(workspace/admin_account 리포지토리 정합). `DocumentRead.from_document` 가 ORM
속성 접근으로 응답을 구성하므로 가짜 repo 는 **실제 ORM `Document` 인스턴스**를 반환한다.
렌더는 순수·빠른 실제 `MarkdownRenderer` 를 그대로 사용한다.

핵심 불변식:
- create_document: 루트·하위 문서가 status=active·created_by=요청자·current_version_id=NULL
  (초기 버전 없음)로 생성되고, 형제 마지막 순서로 sort_order 를 부여한다(Req 1.1·1.2·1.5).
  부모 미존재 → 404, 부모 타 WS·비active → 409(Req 1.3·1.4, INV-6).
- get_document: 미존재 → 404. 현재 버전 본문(content)과 안전 렌더(content_html) 포함.
  현재 버전 부재 문서는 content="" · 빈/안전 content_html(Req 2.1·2.3·2.4).
- list_documents: WS active 문서를 Page[DocumentRead](total 포함)로 반환하며 각 항목도
  content/content_html 을 채운다(Req 2.1).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.document.renderer import MarkdownRenderer
from app.document.schemas import (
    DocumentCreate,
    DocumentMoveRequest,
    DocumentRead,
    DocumentUpdate,
)
from app.document.service import DocumentService
from app.models import Document
from app.schemas.base import Page

USER_CTX = AuthContext(user_id=42, is_admin=False)


def _make_doc(
    *,
    doc_id: int,
    workspace_id: int = 1,
    parent_id: int | None = None,
    title: str = "Doc",
    status: str = "active",
    sort_order: Decimal = Decimal("1000"),
    current_version_id: int | None = None,
    created_by: int = 42,
) -> Document:
    """모든 DocumentRead 필드를 채운 실제 ORM Document 인스턴스를 만든다.

    `DocumentRead.from_document` 가 model_fields(파생 필드 제외) 를 속성 접근으로 읽으므로
    id·타임스탬프·계약 컬럼을 모두 세팅한다.
    """
    return Document(
        id=doc_id,
        workspace_id=workspace_id,
        parent_id=parent_id,
        title=title,
        status=status,
        sort_order=sort_order,
        current_version_id=current_version_id,
        created_by=created_by,
        created_at=datetime(2026, 1, 1),
        updated_at=None,
    )


class _FakeDb:
    """세션 인자 계약(db-first-arg) 확인용 최소 가짜 세션."""


class _FakeRepo:
    """DocumentService 가 호출하는 DocumentRepository 계약의 최소 가짜 구현.

    모든 메서드는 첫 인자로 `db` 를 받는다. get 은 id→Document 매핑, list_siblings 는
    미리 설정한 형제 목록, insert 는 전달된 값으로 Document 를 만들어 반환하며 호출 인자를
    기록한다. load_current_content 는 id→content 매핑(없으면 "").
    """

    START = Decimal("1000")

    def __init__(self) -> None:
        self.get_map: dict[int, Document] = {}
        self.siblings_result: list[Document] = []
        self.content_map: dict[int, str] = {}
        self.list_result: tuple[list[Document], int] = ([], 0)
        self.insert_calls: list[dict] = []
        self.siblings_calls: list[tuple] = []
        self.list_calls: list[tuple] = []
        self.apply_updates_calls: list[dict] = []
        self.set_parent_calls: list[dict] = []
        self._next_id = 500

    def get(self, db, document_id: int) -> Document | None:
        assert isinstance(db, _FakeDb)
        return self.get_map.get(document_id)

    def list_siblings(self, db, workspace_id, parent_id, status) -> list[Document]:
        assert isinstance(db, _FakeDb)
        self.siblings_calls.append((workspace_id, parent_id, status))
        return self.siblings_result

    def insert(
        self, db, *, workspace_id, parent_id, title, sort_order, created_by
    ) -> Document:
        assert isinstance(db, _FakeDb)
        self.insert_calls.append(
            {
                "workspace_id": workspace_id,
                "parent_id": parent_id,
                "title": title,
                "sort_order": sort_order,
                "created_by": created_by,
            }
        )
        doc = _make_doc(
            doc_id=self._next_id,
            workspace_id=workspace_id,
            parent_id=parent_id,
            title=title,
            status="active",
            sort_order=sort_order,
            current_version_id=None,
            created_by=created_by,
        )
        self._next_id += 1
        return doc

    def load_current_content(self, db, doc: Document) -> str:
        assert isinstance(db, _FakeDb)
        return self.content_map.get(doc.id, "")

    def list_active_by_workspace(
        self, db, workspace_id, limit, offset
    ) -> tuple[list[Document], int]:
        assert isinstance(db, _FakeDb)
        self.list_calls.append((workspace_id, limit, offset))
        return self.list_result

    def apply_updates(self, db, doc: Document, changes: dict) -> Document:
        assert isinstance(db, _FakeDb)
        # 실제 리포지토리 계약 반영: {"title"} 화이트리스트만 적용, 그 외 키 무시.
        self.apply_updates_calls.append(dict(changes))
        for key, value in changes.items():
            if key == "title":
                setattr(doc, key, value)
        return doc

    def set_parent_and_order(
        self, db, doc: Document, *, parent_id, sort_order
    ) -> Document:
        assert isinstance(db, _FakeDb)
        self.set_parent_calls.append(
            {"id": doc.id, "parent_id": parent_id, "sort_order": sort_order}
        )
        doc.parent_id = parent_id
        doc.sort_order = sort_order
        return doc


def _service(repo: _FakeRepo) -> DocumentService:
    return DocumentService(repo, MarkdownRenderer())


# --- create_document ----------------------------------------------------------


def test_create_root_document_active_created_by_no_version():
    db = _FakeDb()
    repo = _FakeRepo()
    service = _service(repo)

    result = service.create_document(
        db, USER_CTX, workspace_id=1, payload=DocumentCreate(title="Root")
    )

    # 정확히 한 번 삽입되었고 요청자가 created_by 다.
    assert len(repo.insert_calls) == 1
    call = repo.insert_calls[0]
    assert call["workspace_id"] == 1
    assert call["parent_id"] is None
    assert call["title"] == "Root"
    assert call["created_by"] == USER_CTX.user_id

    # 응답은 active·버전 없음·빈 본문.
    assert isinstance(result, DocumentRead)
    assert result.status == "active"
    assert result.created_by == USER_CTX.user_id
    assert result.current_version_id is None
    assert result.content == ""
    assert result.content_html == ""


def test_create_root_first_sibling_uses_start_sort_order():
    db = _FakeDb()
    repo = _FakeRepo()
    repo.siblings_result = []  # 형제 없음
    service = _service(repo)

    service.create_document(
        db, USER_CTX, workspace_id=1, payload=DocumentCreate(title="First")
    )

    assert repo.insert_calls[0]["sort_order"] == _FakeRepo.START


def test_create_sort_order_after_last_sibling():
    db = _FakeDb()
    repo = _FakeRepo()
    # 형제는 sort_order 오름차순 정렬(repo 계약). 마지막이 최대값.
    repo.siblings_result = [
        _make_doc(doc_id=1, sort_order=Decimal("1000")),
        _make_doc(doc_id=2, sort_order=Decimal("2000")),
        _make_doc(doc_id=3, sort_order=Decimal("3000")),
    ]
    service = _service(repo)

    service.create_document(
        db, USER_CTX, workspace_id=1, payload=DocumentCreate(title="Last")
    )

    # 기존 형제 최대값보다 큰 값을 부여한다.
    assigned = repo.insert_calls[0]["sort_order"]
    assert assigned > Decimal("3000")


def test_create_child_document_validates_active_same_ws_parent():
    db = _FakeDb()
    repo = _FakeRepo()
    parent = _make_doc(doc_id=7, workspace_id=1, status="active")
    repo.get_map = {7: parent}
    service = _service(repo)

    result = service.create_document(
        db, USER_CTX, workspace_id=1, payload=DocumentCreate(title="Child", parent_id=7)
    )

    assert repo.insert_calls[0]["parent_id"] == 7
    assert result.parent_id == 7
    # 형제 조회는 부모 기준(같은 parent_id).
    assert repo.siblings_calls[0][1] == 7


def test_create_parent_missing_raises_404():
    db = _FakeDb()
    repo = _FakeRepo()  # get_map 비어 있음 → 부모 미존재
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.create_document(
            db, USER_CTX, workspace_id=1, payload=DocumentCreate(title="X", parent_id=99)
        )

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert repo.insert_calls == []


def test_create_parent_other_workspace_raises_409():
    db = _FakeDb()
    repo = _FakeRepo()
    repo.get_map = {7: _make_doc(doc_id=7, workspace_id=2, status="active")}
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.create_document(
            db, USER_CTX, workspace_id=1, payload=DocumentCreate(title="X", parent_id=7)
        )

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.insert_calls == []


def test_create_parent_non_active_raises_409():
    db = _FakeDb()
    repo = _FakeRepo()
    repo.get_map = {7: _make_doc(doc_id=7, workspace_id=1, status="trashed")}
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.create_document(
            db, USER_CTX, workspace_id=1, payload=DocumentCreate(title="X", parent_id=7)
        )

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.insert_calls == []


# --- get_document -------------------------------------------------------------


def test_get_document_missing_raises_404():
    db = _FakeDb()
    repo = _FakeRepo()
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.get_document(db, 404)

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404


def test_get_document_includes_content_and_rendered_html():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, current_version_id=55)
    repo.get_map = {10: doc}
    repo.content_map = {10: "# Title"}
    service = _service(repo)

    result = service.get_document(db, 10)

    assert isinstance(result, DocumentRead)
    assert result.content == "# Title"
    # 안전 렌더된 HTML(헤딩 태그 포함).
    assert "<h1>" in result.content_html
    assert "Title" in result.content_html


def test_get_document_no_version_returns_empty_body():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=11, current_version_id=None)
    repo.get_map = {11: doc}
    service = _service(repo)

    result = service.get_document(db, 11)

    assert result.content == ""
    assert result.content_html == ""


def test_get_document_sanitizes_dangerous_html():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=12, current_version_id=77)
    repo.get_map = {12: doc}
    repo.content_map = {12: "<script>alert(1)</script>hello"}
    service = _service(repo)

    result = service.get_document(db, 12)

    assert "<script>" not in result.content_html


# --- list_documents -----------------------------------------------------------


def test_list_documents_returns_page_with_total_and_bodies():
    db = _FakeDb()
    repo = _FakeRepo()
    d1 = _make_doc(doc_id=20, current_version_id=1)
    d2 = _make_doc(doc_id=21, current_version_id=None)
    repo.list_result = ([d1, d2], 5)
    repo.content_map = {20: "**bold**"}
    service = _service(repo)

    page = service.list_documents(db, workspace_id=1, limit=10, offset=0)

    assert isinstance(page, Page)
    assert page.total == 5
    assert [i.id for i in page.items] == [20, 21]
    assert all(isinstance(i, DocumentRead) for i in page.items)
    # 각 항목도 현재 버전 기준 본문/렌더를 채운다.
    assert page.items[0].content == "**bold**"
    assert "<strong>" in page.items[0].content_html
    assert page.items[1].content == ""
    assert page.items[1].content_html == ""
    assert repo.list_calls == [(1, 10, 0)]


def test_list_documents_empty_workspace_returns_empty_page():
    db = _FakeDb()
    repo = _FakeRepo()
    repo.list_result = ([], 0)
    service = _service(repo)

    page = service.list_documents(db, workspace_id=9, limit=10, offset=0)

    assert page.items == []
    assert page.total == 0


# --- update_document ----------------------------------------------------------


def test_update_document_updates_title_returns_read_with_body():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=30, title="Old", current_version_id=88)
    repo.get_map = {30: doc}
    repo.content_map = {30: "# Body"}
    service = _service(repo)

    result = service.update_document(
        db, document_id=30, changes=DocumentUpdate(title="New")
    )

    # 제목이 갱신되고, 응답은 현재 버전 본문/안전 렌더를 함께 담는다.
    assert isinstance(result, DocumentRead)
    assert result.title == "New"
    assert result.content == "# Body"
    assert "<h1>" in result.content_html
    # 부분 갱신: 제공된 title 필드만 apply_updates 로 전달한다(exclude_unset).
    assert repo.apply_updates_calls == [{"title": "New"}]


def test_update_document_missing_raises_404():
    db = _FakeDb()
    repo = _FakeRepo()  # get_map 비어 있음 → 대상 미존재
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.update_document(
            db, document_id=404, changes=DocumentUpdate(title="X")
        )

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert repo.apply_updates_calls == []


def test_update_document_leaves_body_and_version_untouched():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=31, title="Old", current_version_id=99)
    repo.get_map = {31: doc}
    service = _service(repo)

    result = service.update_document(
        db, document_id=31, changes=DocumentUpdate(title="Renamed")
    )

    # 본문/버전 필드는 이 경계에서 건드리지 않는다(s09 소유).
    assert result.current_version_id == 99
    assert doc.current_version_id == 99
    # 화이트리스트(title) 외 컬럼은 apply_updates 로 흘러가지 않는다.
    assert repo.apply_updates_calls == [{"title": "Renamed"}]


def test_update_document_no_fields_provided_applies_empty_changes():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=32, title="Keep", current_version_id=None)
    repo.get_map = {32: doc}
    service = _service(repo)

    result = service.update_document(
        db, document_id=32, changes=DocumentUpdate()
    )

    # 아무 필드도 제공하지 않으면 exclude_unset 이 빈 변경셋을 전달하고 제목은 불변.
    assert result.title == "Keep"
    assert repo.apply_updates_calls == [{}]


# --- move_document ------------------------------------------------------------


def test_move_missing_target_raises_404():
    db = _FakeDb()
    repo = _FakeRepo()  # get_map 비어 있음 → 대상 미존재
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.move_document(db, 404, DocumentMoveRequest(new_parent_id=None))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert repo.set_parent_calls == []


def test_move_non_active_target_raises_409():
    db = _FakeDb()
    repo = _FakeRepo()
    repo.get_map = {10: _make_doc(doc_id=10, status="trashed")}
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.move_document(db, 10, DocumentMoveRequest(new_parent_id=None))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.set_parent_calls == []


def test_move_under_self_raises_409():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    repo.get_map = {10: doc}
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.move_document(db, 10, DocumentMoveRequest(new_parent_id=10))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.set_parent_calls == []


def test_move_under_descendant_raises_409():
    db = _FakeDb()
    repo = _FakeRepo()
    root = _make_doc(doc_id=10, workspace_id=1, parent_id=None, status="active")
    child = _make_doc(doc_id=20, workspace_id=1, parent_id=10, status="active")
    grand = _make_doc(doc_id=30, workspace_id=1, parent_id=20, status="active")
    repo.get_map = {10: root, 20: child, 30: grand}
    service = _service(repo)

    # 루트(10)를 자신의 손자(30) 밑으로 이동 → 사이클.
    with pytest.raises(DomainError) as ei:
        service.move_document(db, 10, DocumentMoveRequest(new_parent_id=30))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.set_parent_calls == []
    # 계층 무변: 대상·손자 parent_id 그대로.
    assert root.parent_id is None
    assert grand.parent_id == 20


def test_move_to_other_workspace_parent_raises_409():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    other = _make_doc(doc_id=50, workspace_id=2, status="active")
    repo.get_map = {10: doc, 50: other}
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.move_document(db, 10, DocumentMoveRequest(new_parent_id=50))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.set_parent_calls == []


def test_move_new_parent_missing_raises_404():
    db = _FakeDb()
    repo = _FakeRepo()
    repo.get_map = {10: _make_doc(doc_id=10, workspace_id=1, status="active")}
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.move_document(db, 10, DocumentMoveRequest(new_parent_id=99))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert repo.set_parent_calls == []


def test_move_new_parent_non_active_raises_409():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="trashed")
    repo.get_map = {10: doc, 50: parent}
    service = _service(repo)

    with pytest.raises(DomainError) as ei:
        service.move_document(db, 10, DocumentMoveRequest(new_parent_id=50))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.set_parent_calls == []


def test_move_to_root_sets_parent_null():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, parent_id=5, status="active")
    repo.get_map = {10: doc}
    repo.siblings_result = []  # 루트에 다른 형제 없음
    service = _service(repo)

    result = service.move_document(db, 10, DocumentMoveRequest(new_parent_id=None))

    assert len(repo.set_parent_calls) == 1
    call = repo.set_parent_calls[0]
    assert call["parent_id"] is None
    assert call["sort_order"] == Decimal("1000")
    assert result.parent_id is None


def test_move_normal_updates_parent_and_order():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, parent_id=None, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = []  # 새 부모에 형제 없음 → append
    service = _service(repo)

    result = service.move_document(db, 10, DocumentMoveRequest(new_parent_id=50))

    call = repo.set_parent_calls[0]
    assert call["parent_id"] == 50
    assert call["sort_order"] == Decimal("1000")
    assert result.parent_id == 50


def test_move_between_two_siblings_uses_midpoint_no_reorder():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, parent_id=None, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, sib_b]
    service = _service(repo)

    result = service.move_document(
        db,
        10,
        DocumentMoveRequest(new_parent_id=50, after_sibling_id=1, before_sibling_id=2),
    )

    call = repo.set_parent_calls[0]
    assert call["parent_id"] == 50
    # 인접 형제 중간값(1000·2000 → 1500) 부여.
    assert call["sort_order"] == Decimal("1500")
    assert result.sort_order == Decimal("1500")
    # 다른 형제 sort_order 는 재배치되지 않는다(핵심 acceptance 4.5).
    assert sib_a.sort_order == Decimal("1000")
    assert sib_b.sort_order == Decimal("2000")


def test_move_after_sibling_only_inserts_before_next():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    sib_c = _make_doc(doc_id=3, workspace_id=1, parent_id=50, sort_order=Decimal("3000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, sib_b, sib_c]
    service = _service(repo)

    service.move_document(
        db, 10, DocumentMoveRequest(new_parent_id=50, after_sibling_id=1)
    )

    # sib_a(1000) 뒤, 다음 형제 sib_b(2000) 앞 → 1500.
    assert repo.set_parent_calls[0]["sort_order"] == Decimal("1500")
    assert [sib_a.sort_order, sib_b.sort_order, sib_c.sort_order] == [
        Decimal("1000"),
        Decimal("2000"),
        Decimal("3000"),
    ]


def test_move_after_last_sibling_appends_to_end():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, sib_b]
    service = _service(repo)

    service.move_document(
        db, 10, DocumentMoveRequest(new_parent_id=50, after_sibling_id=2)
    )

    # 마지막 형제 뒤 → max + step(2000 + 1000 = 3000).
    assert repo.set_parent_calls[0]["sort_order"] == Decimal("3000")


def test_move_before_sibling_only_inserts_after_previous():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    sib_c = _make_doc(doc_id=3, workspace_id=1, parent_id=50, sort_order=Decimal("3000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, sib_b, sib_c]
    service = _service(repo)

    service.move_document(
        db, 10, DocumentMoveRequest(new_parent_id=50, before_sibling_id=2)
    )

    # sib_b(2000) 앞, 이전 형제 sib_a(1000) 뒤 → 1500.
    assert repo.set_parent_calls[0]["sort_order"] == Decimal("1500")


def test_move_before_first_sibling_prepends():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, sib_b]
    service = _service(repo)

    service.move_document(
        db, 10, DocumentMoveRequest(new_parent_id=50, before_sibling_id=1)
    )

    # 첫 형제 앞 → min - step(1000 - 1000 = 0).
    assert repo.set_parent_calls[0]["sort_order"] == Decimal("0")


def test_move_no_refs_appends_to_end():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, sib_b]
    service = _service(repo)

    service.move_document(db, 10, DocumentMoveRequest(new_parent_id=50))

    assert repo.set_parent_calls[0]["sort_order"] == Decimal("3000")


def test_move_excludes_target_from_siblings_when_same_parent():
    db = _FakeDb()
    repo = _FakeRepo()
    # 대상(10)이 이미 부모 50 의 형제 목록에 포함됨.
    doc = _make_doc(
        doc_id=10, workspace_id=1, parent_id=50, sort_order=Decimal("1500"), status="active"
    )
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, doc, sib_b]
    service = _service(repo)

    # 참조 없음 → 대상 제외 후 마지막(2000) 뒤 → 3000.
    service.move_document(db, 10, DocumentMoveRequest(new_parent_id=50))

    assert repo.set_parent_calls[0]["sort_order"] == Decimal("3000")


def test_move_unknown_sibling_ref_raises_422():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a]
    service = _service(repo)

    # after_sibling_id=99 는 새 부모의 형제가 아님.
    with pytest.raises(DomainError) as ei:
        service.move_document(
            db, 10, DocumentMoveRequest(new_parent_id=50, after_sibling_id=99)
        )

    assert ei.value.http_status == 422
    assert repo.set_parent_calls == []


def test_move_contradictory_sibling_refs_raises_422():
    db = _FakeDb()
    repo = _FakeRepo()
    doc = _make_doc(doc_id=10, workspace_id=1, status="active")
    parent = _make_doc(doc_id=50, workspace_id=1, status="active")
    sib_a = _make_doc(doc_id=1, workspace_id=1, parent_id=50, sort_order=Decimal("1000"))
    sib_b = _make_doc(doc_id=2, workspace_id=1, parent_id=50, sort_order=Decimal("2000"))
    repo.get_map = {10: doc, 50: parent}
    repo.siblings_result = [sib_a, sib_b]
    service = _service(repo)

    # after=sib_b(뒤), before=sib_a(앞) → 순서 모순(비인접/역순).
    with pytest.raises(DomainError) as ei:
        service.move_document(
            db,
            10,
            DocumentMoveRequest(new_parent_id=50, after_sibling_id=2, before_sibling_id=1),
        )

    assert ei.value.http_status == 422
    assert repo.set_parent_calls == []
