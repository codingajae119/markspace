"""LockVersionSchemas 단위 검증 (s09-lock-version task 1.1).

requirements.md 1.1·2.1·2.6·5.1·5.4·7.2·7.5, design.md §Components and Interfaces
#LockVersionSchemas 검증:
- `DocumentSaveRequest` 는 `content: str`(빈 문자열 허용)을 받는 요청 모델이며 타입 위반
  (None·비문자열)은 pydantic ValidationError 로 거부한다(2.1·2.6·7.5).
- `DocumentLockRead`·`DocumentVersionRead` 는 s01 `ORMReadModel`(from_attributes) 을 상속해
  ORM 속성 객체로부터 `model_validate` 로 직렬화된다(1.1·5.1·7.5).
- `DocumentVersionRead` 는 본문(content) 필드를 포함하지 않는다(과거 본문 조회·rollback
  없음, design §Non-Goals·5.3).
- 이 task 는 새 마이그레이션·새 의존성을 추가하지 않는다(7.2).
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from app.models import DocumentVersion
from app.schemas.base import ORMReadModel
from app.lock_version.schemas import (
    DocumentLockRead,
    DocumentSaveRequest,
    DocumentVersionRead,
)


# --- DocumentSaveRequest: content:str(빈 문자열 허용)·타입 위반 거부 (2.1·2.6·7.5) ---


def test_document_save_request_is_plain_request_model() -> None:
    """s07 create/update 요청처럼 순수 BaseModel(ORM-read 아님)."""
    assert issubclass(DocumentSaveRequest, BaseModel)
    assert not issubclass(DocumentSaveRequest, ORMReadModel)
    assert set(DocumentSaveRequest.model_fields) == {"content"}


def test_document_save_request_accepts_empty_string() -> None:
    """빈 markdown 본문 스냅샷 저장 허용(빈 문자열)."""
    payload = DocumentSaveRequest(content="")
    assert payload.content == ""


def test_document_save_request_accepts_markdown_content() -> None:
    payload = DocumentSaveRequest(content="# hello\n\nbody")
    assert payload.content == "# hello\n\nbody"


def test_document_save_request_rejects_none_content() -> None:
    with pytest.raises(ValidationError):
        DocumentSaveRequest(content=None)  # type: ignore[arg-type]


def test_document_save_request_rejects_non_str_content() -> None:
    with pytest.raises(ValidationError):
        DocumentSaveRequest(content=123)  # type: ignore[arg-type]


def test_document_save_request_requires_content() -> None:
    with pytest.raises(ValidationError):
        DocumentSaveRequest()  # type: ignore[call-arg]


# --- DocumentLockRead: ORMReadModel 상속 + from_attributes 직렬화 (1.1·7.5) ---


def test_document_lock_read_inherits_orm_read_model() -> None:
    assert issubclass(DocumentLockRead, ORMReadModel)
    assert DocumentLockRead.model_config.get("from_attributes") is True
    assert set(DocumentLockRead.model_fields) == {
        "document_id",
        "lock_user_id",
        "lock_acquired_at",
    }


def test_document_lock_read_validates_from_attributes() -> None:
    """잠금 획득 정보를 속성 객체(from_attributes)로부터 직렬화한다."""
    acquired = datetime(2026, 7, 17, 9, 30, 0)
    source = SimpleNamespace(
        document_id=42,
        lock_user_id=7,
        lock_acquired_at=acquired,
    )

    read = DocumentLockRead.model_validate(source)

    assert read.document_id == 42
    assert read.lock_user_id == 7
    assert read.lock_acquired_at == acquired


def test_document_lock_read_direct_construction() -> None:
    acquired = datetime(2026, 7, 17, 9, 30, 0)
    read = DocumentLockRead(document_id=1, lock_user_id=2, lock_acquired_at=acquired)
    assert read.model_dump() == {
        "document_id": 1,
        "lock_user_id": 2,
        "lock_acquired_at": acquired,
    }


# --- DocumentVersionRead: ORM 직렬화 + 본문 미포함 (5.1·5.4·5.3) ---


def test_document_version_read_inherits_orm_read_model() -> None:
    assert issubclass(DocumentVersionRead, ORMReadModel)
    assert DocumentVersionRead.model_config.get("from_attributes") is True
    assert set(DocumentVersionRead.model_fields) == {
        "id",
        "document_id",
        "created_by",
        "created_at",
    }


def test_document_version_read_has_no_content_field() -> None:
    """과거 본문 조회·rollback 미제공 — 버전 메타데이터에 본문(content) 없음(5.3)."""
    assert "content" not in DocumentVersionRead.model_fields
    assert "body" not in DocumentVersionRead.model_fields


def test_document_version_read_validates_from_orm_version() -> None:
    """s01 `document_version` ORM 객체로부터 메타데이터만 직렬화한다(본문 무시)."""
    created = datetime(2026, 7, 17, 9, 31, 0)
    version = DocumentVersion(
        id=101,
        document_id=42,
        content="# secret body should be ignored",
        created_by=7,
        created_at=created,
    )

    read = DocumentVersionRead.model_validate(version)
    dump = read.model_dump()

    assert dump == {
        "id": 101,
        "document_id": 42,
        "created_by": 7,
        "created_at": created,
    }
    assert "content" not in dump
