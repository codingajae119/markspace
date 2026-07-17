"""AttachmentSchemas 단위 검증 (s12-attachment task 1.1).

requirements.md 1.4·7.1, design.md §Components and Interfaces #AttachmentSchemas 검증:
- `AttachmentKind` 는 s01 `attachment.kind` ENUM 값(image/file)과 동일한 str Enum 이다.
- `AttachmentCreate` 는 multipart 업로드용 요청 스키마로 kind 를 생략할 수 있다(미지정 시
  content-type 추론은 상위 태스크 소관, 여기서는 스키마 형태만).
- `AttachmentRead` 는 s01 `ORMReadModel`(from_attributes) 을 상속한 첨부 메타데이터 스키마다(7.1).
- `url` 은 저장 컬럼이 아니라 응답 시 산정되는 파생값(`/attachments/{id}`)이며(1.4) 필수 필드다.
  `AttachmentRead.from_attachment(att)` 은 ORM `Attachment` 객체로부터 컬럼 필드를 읽고 `url` 을
  주입해 표시 스키마를 구성한다(ORM 객체에 url 속성이 없어 `model_validate(att)` 단독으로는 실패).
"""

from datetime import datetime
from enum import Enum

import pytest
from pydantic import BaseModel, ValidationError

from app.models import Attachment
from app.schemas.base import ORMReadModel
from app.attachment.schemas import (
    AttachmentCreate,
    AttachmentKind,
    AttachmentRead,
)


def _attachment(
    *,
    id: int = 42,
    workspace_id: int = 5,
    document_id: int = 10,
    kind: str = "image",
    original_name: str = "pasted.png",
    is_archived: bool = False,
    created_at: datetime | None = None,
) -> Attachment:
    """DB 세션 없이 in-memory ORM Attachment 인스턴스를 만든다(투영 검증용)."""
    return Attachment(
        id=id,
        workspace_id=workspace_id,
        document_id=document_id,
        file_path="5/abcd-1234.png",
        original_name=original_name,
        kind=kind,
        is_archived=is_archived,
        created_at=created_at or datetime(2026, 7, 1, 12, 0, 0),
    )


# --- AttachmentKind: s01 attachment.kind ENUM 값과 동일 ---


def test_attachment_kind_is_str_enum_with_image_file() -> None:
    assert issubclass(AttachmentKind, str)
    assert issubclass(AttachmentKind, Enum)
    assert AttachmentKind.IMAGE.value == "image"
    assert AttachmentKind.FILE.value == "file"
    assert {k.value for k in AttachmentKind} == {"image", "file"}


# --- AttachmentCreate: multipart 업로드 요청, kind 생략 가능 ---


def test_attachment_create_is_plain_base_model() -> None:
    assert issubclass(AttachmentCreate, BaseModel)
    assert not issubclass(AttachmentCreate, ORMReadModel)


def test_attachment_create_kind_optional_defaults_none() -> None:
    """kind 미지정 시 None 으로 기본값(추론은 상위 태스크 소관)."""
    assert AttachmentCreate().kind is None
    assert AttachmentCreate(kind=AttachmentKind.FILE).kind is AttachmentKind.FILE
    # 문자열도 enum 으로 수용(multipart Form 값 호환)
    assert AttachmentCreate(kind="image").kind is AttachmentKind.IMAGE


# --- AttachmentRead: ORMReadModel 상속·필드 규약 (7.1) ---


def test_attachment_read_inherits_orm_read_model() -> None:
    assert issubclass(AttachmentRead, ORMReadModel)
    assert AttachmentRead.model_config.get("from_attributes") is True
    assert set(AttachmentRead.model_fields) == {
        "id",
        "workspace_id",
        "document_id",
        "kind",
        "original_name",
        "is_archived",
        "created_at",
        "url",
    }


def test_attachment_read_url_is_required() -> None:
    """`url` 은 옵셔널이 아니라 서버 산정 필수 필드다(1.4)."""
    with pytest.raises(ValidationError):
        AttachmentRead(
            id=42,
            workspace_id=5,
            document_id=10,
            kind=AttachmentKind.IMAGE,
            original_name="pasted.png",
            is_archived=False,
            created_at=datetime(2026, 7, 1, 12, 0, 0),
        )  # type: ignore[call-arg]


def test_model_validate_on_raw_attachment_fails_without_url() -> None:
    """ORM Attachment 에는 url 속성이 없어 model_validate 단독으로는 구성 불가(파생값)."""
    att = _attachment()
    with pytest.raises(ValidationError):
        AttachmentRead.model_validate(att)


# --- from_attachment: ORM → 표시 스키마, url 산정 (1.4) ---


def test_from_attachment_computes_url_and_projects_columns() -> None:
    att = _attachment(id=42, workspace_id=5, document_id=10, kind="image")

    read = AttachmentRead.from_attachment(att)

    assert read.id == 42
    assert read.workspace_id == 5
    assert read.document_id == 10
    assert read.kind is AttachmentKind.IMAGE
    assert read.original_name == "pasted.png"
    assert read.is_archived is False
    assert read.created_at == datetime(2026, 7, 1, 12, 0, 0)
    assert read.url == "/attachments/42"


def test_from_attachment_url_tracks_id() -> None:
    assert AttachmentRead.from_attachment(_attachment(id=123)).url == "/attachments/123"
    assert AttachmentRead.from_attachment(_attachment(id=1)).url == "/attachments/1"


def test_from_attachment_preserves_file_kind_and_original_name() -> None:
    att = _attachment(kind="file", original_name="report.pdf")

    read = AttachmentRead.from_attachment(att)

    assert read.kind is AttachmentKind.FILE
    assert read.original_name == "report.pdf"
