"""첨부 업로드/응답 스키마 (design.md §Components and Interfaces #AttachmentSchemas).

s01 Base Schemas 규약(`{Resource}Create/Read`·`ORMReadModel`)을 상속하며 **스키마 형태와
참조 URL 규약만** 소유한다(Req 7.1). 공통 Read 베이스(`ORMReadModel`)는 s01 소유이며 여기서
재정의하지 않는다. `attachment` 스키마(테이블 계약)는 s01 소유이므로 재정의하지 않는다.

- `AttachmentKind` — s01 `attachment.kind` ENUM 값(image/file)과 동일한 str Enum.
- `AttachmentCreate` — multipart 업로드 요청. `kind` 는 선택(미지정 시 라우터/서비스가 업로드
  content-type 으로 image/file 추론; 추론 자체는 상위 태스크 소관). 파일 바이너리는 라우터에서
  `UploadFile` 로 별도 수신하므로 스키마에는 두지 않는다.
- `AttachmentRead` — 첨부 메타데이터 응답(바이너리 아님). s01 `ORMReadModel`(from_attributes)
  상속.

`url` 규약 (Req 1.4)
--------------------
`url`(문서 본문에서의 안정 참조)은 ORM `attachment` 컬럼이 아니라 응답 시 산정되는 **파생값**
(`/attachments/{id}`)이며 필수 필드다. 8.7 참조 소멸 판정의 근거이자 s07 렌더가 소비하는 규약이다.
ORM 객체에는 `url` 속성이 없어 `model_validate(att)` 단독으로는 필수 `url` 이 없어 실패하므로,
서비스는 `AttachmentRead.from_attachment(att)` 로 ORM 컬럼과 산정된 url 을 함께 넘겨 구성한다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.base import ORMReadModel

__all__ = ["AttachmentKind", "AttachmentCreate", "AttachmentRead"]


# ORM attachment 컬럼이 아닌, 응답 시 서버가 산정하는 파생 필드.
_DERIVED_FIELDS = frozenset({"url"})


class AttachmentKind(str, Enum):
    """첨부 종류 — s01 `attachment.kind` ENUM 값과 동일(image/file)."""

    IMAGE = "image"
    FILE = "file"


class AttachmentCreate(BaseModel):
    """첨부 업로드 요청(multipart/form-data) 스키마 (1.4·2.1·2.2).

    파일 바이너리(`UploadFile`)는 라우터에서 별도 수신하고, 이 스키마는 선택 메타데이터인
    `kind` 만 담는다. `kind` 미지정 시 업로드 content-type 으로 image/file 추론(추론 규약은
    상위 태스크 소관이며 여기서는 스키마 형태만 확정).
    """

    kind: AttachmentKind | None = None


class AttachmentRead(ORMReadModel):
    """첨부 메타데이터 응답 (Req 1.4·7.1).

    s01 `ORMReadModel`(from_attributes) 상속으로 ORM `attachment` 속성 객체로부터 직렬화한다.
    `url` 은 ORM 컬럼이 아닌 서버 산정 파생값(`/attachments/{id}`)이므로 `from_attachment` 로
    함께 구성한다. 바이너리 응답은 스키마가 아니라 `StreamingResponse` 다.
    """

    id: int
    workspace_id: int
    document_id: int
    kind: AttachmentKind
    original_name: str
    is_archived: bool
    created_at: datetime
    url: str  # = "/attachments/{id}" (문서 본문 참조 규약, 서버 산정 파생값)

    @classmethod
    def from_attachment(cls, attachment: object) -> AttachmentRead:
        """ORM `attachment` 객체와 산정된 `url` 로 응답을 구성한다.

        ORM 컬럼 필드는 속성 접근으로 읽고, ORM 에 없는 파생 필드 `url` 은 첨부 id 로부터
        `/attachments/{id}` 규약으로 산정해 주입한다. 서비스가 응답을 만드는 단일 경로다.
        """
        orm_fields = {
            name: getattr(attachment, name)
            for name in cls.model_fields
            if name not in _DERIVED_FIELDS
        }
        return cls(**orm_fields, url=f"/attachments/{attachment.id}")
