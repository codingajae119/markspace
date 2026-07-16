"""DocumentSchemas 단위 검증 (s07-document-core task 1.1).

requirements.md 1.1·1.2·3.1·4.1·10.1, design.md §Components and Interfaces
#DocumentSchemas 검증:
- `DocumentRead` 는 s01 `TimestampedRead` 를 상속하며, ORM document 객체 + 파생값
  (content·content_html)으로 구성되어 직렬화된다(1.1·1.2·10.1).
- `status` 문자열 값이 s01 `document.status` ENUM(active/trashed/deleted)과 일치한다.
- `DocumentCreate` 는 title 누락·공백 전용을 검증 오류로 거부한다(1.1).
- `DocumentUpdate`/`DocumentMoveRequest` 의 부분 갱신·optional 기본값(3.1·4.1).
"""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.document import Document
from app.schemas.base import TimestampedRead
from app.document.schemas import (
    DocumentCreate,
    DocumentMoveRequest,
    DocumentRead,
    DocumentUpdate,
)


def _make_orm_document(**overrides: object) -> Document:
    """DB 미접근으로 구성한 Document ORM 인스턴스(파생값 주입 대상).

    content/content_html 은 ORM 컬럼이 아니므로 여기서 세팅하지 않는다 —
    DocumentRead 구성 시 service 가 채우는 파생 필드다.
    """
    defaults: dict[str, object] = {
        "id": 42,
        "workspace_id": 7,
        "parent_id": None,
        "title": "Root Doc",
        "status": "active",
        "sort_order": Decimal("1.500000000000000"),
        "current_version_id": None,
        "created_by": 3,
        "created_at": datetime(2026, 7, 16, 0, 0, 0),
        "updated_at": None,
    }
    defaults.update(overrides)
    return Document(**defaults)


# --- DocumentRead: TimestampedRead 상속 + ORM + 파생값 구성 (1.1·1.2·10.1) ---


def test_document_read_inherits_timestamped_read() -> None:
    assert issubclass(DocumentRead, TimestampedRead)
    for field in (
        "id",
        "created_at",
        "updated_at",
        "workspace_id",
        "parent_id",
        "title",
        "status",
        "sort_order",
        "current_version_id",
        "created_by",
        "content",
        "content_html",
    ):
        assert field in DocumentRead.model_fields


def test_document_read_constructs_from_orm_with_derived_content() -> None:
    """ORM document + content/content_html 파생값으로 구성·직렬화됨(설계상 service 경로)."""
    doc = _make_orm_document()

    read = DocumentRead.from_document(
        doc, content="# hello", content_html="<h1>hello</h1>"
    )
    dump = read.model_dump()

    assert dump["id"] == 42
    assert dump["workspace_id"] == 7
    assert dump["parent_id"] is None
    assert dump["title"] == "Root Doc"
    assert dump["status"] == "active"
    assert dump["sort_order"] == Decimal("1.500000000000000")
    assert dump["current_version_id"] is None
    assert dump["created_by"] == 3
    assert dump["created_at"] == datetime(2026, 7, 16, 0, 0, 0)
    assert dump["updated_at"] is None
    assert dump["content"] == "# hello"
    assert dump["content_html"] == "<h1>hello</h1>"


def test_document_read_serializes_child_document() -> None:
    doc = _make_orm_document(id=99, parent_id=42, title="Child", current_version_id=5)

    read = DocumentRead.from_document(doc, content="body", content_html="<p>body</p>")

    assert read.parent_id == 42
    assert read.current_version_id == 5
    assert read.content == "body"


def test_document_read_requires_content_fields_without_derived_values() -> None:
    """content/content_html 은 파생 필수 필드 — 값 없이 bare 검증은 실패(설계 결정 문서화)."""
    doc = _make_orm_document()
    with pytest.raises(ValidationError):
        DocumentRead.model_validate(doc)


@pytest.mark.parametrize("status", ["active", "trashed", "deleted"])
def test_document_read_accepts_all_status_enum_values(status: str) -> None:
    doc = _make_orm_document(status=status)

    read = DocumentRead.from_document(doc, content="", content_html="")

    assert read.status == status


def test_document_read_status_matches_s01_model_enum() -> None:
    """DocumentRead 가 표현하는 status 값 집합 == s01 document.status ENUM(하드코딩 금지)."""
    model_enum_values = set(Document.__table__.c.status.type.enums)

    assert model_enum_values == {"active", "trashed", "deleted"}


# --- DocumentCreate: 필수/공백 title 검증 (1.1) ---


def test_document_create_accepts_valid_title() -> None:
    payload = DocumentCreate(title="My Doc")
    assert payload.title == "My Doc"
    assert payload.parent_id is None


def test_document_create_accepts_parent_id() -> None:
    payload = DocumentCreate(title="Child", parent_id=42)
    assert payload.parent_id == 42


def test_document_create_rejects_missing_title() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate()  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_document_create_rejects_blank_title(blank: str) -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(title=blank)


# --- DocumentUpdate: 부분 갱신 (3.1) ---


def test_document_update_is_partial_title_optional() -> None:
    assert DocumentUpdate().title is None
    assert DocumentUpdate(title="New Title").title == "New Title"


@pytest.mark.parametrize("blank", ["", "   "])
def test_document_update_rejects_blank_title(blank: str) -> None:
    with pytest.raises(ValidationError):
        DocumentUpdate(title=blank)


# --- DocumentMoveRequest: optional 기본값 (4.1) ---


def test_document_move_request_defaults_none() -> None:
    move = DocumentMoveRequest()
    assert move.new_parent_id is None
    assert move.before_sibling_id is None
    assert move.after_sibling_id is None


def test_document_move_request_accepts_sibling_fields() -> None:
    move = DocumentMoveRequest(
        new_parent_id=42, before_sibling_id=1, after_sibling_id=2
    )
    assert move.new_parent_id == 42
    assert move.before_sibling_id == 1
    assert move.after_sibling_id == 2
