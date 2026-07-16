"""문서 요청/응답·이동 스키마 (design.md §Components and Interfaces #DocumentSchemas).

s01 Base Schemas 규약(`{Resource}Create/Read/Update`)을 상속하며 스키마 형태만 소유한다
(design.md §Data Contracts, Req 10.1). 공통 Read 베이스(`TimestampedRead`·`ORMReadModel`)와
`Page[T]` 는 s01 소유이며 여기서 재정의하지 않는다.

- `DocumentCreate` — 생성 요청. `title` 필수·공백 금지(1.1). `parent_id` 는 None 이면 루트,
  지정 시 하위 문서(1.2). 서버가 채우는 status·sort_order·created_by 는 입력받지 않는다.
- `DocumentUpdate` — 부분 갱신 요청. `title` 만 선택적으로 받는다(3.1). 본문 내용·버전
  저장은 s09 소유이므로 필드를 두지 않는다(3.4). 이동은 별도 `DocumentMoveRequest`.
- `DocumentMoveRequest` — 이동/재정렬 요청. 새 부모(`new_parent_id`)와 두 형제 사이 삽입
  기준(`before_sibling_id`·`after_sibling_id`)을 받는다(4.1·4.5). 정렬 규약 확정은 Service 소유.
- `DocumentRead` — 응답. s01 `TimestampedRead`(id·created_at·updated_at) 를 상속한다(1.1·10.1).
  `status` 문자열은 s01 `document.status` ENUM(active/trashed/deleted)과 동일 값이다.

파생 필드(content·content_html) 구성 규약
----------------------------------------
`content`(현재 버전 markdown 본문)·`content_html`(안전 렌더 HTML)은 ORM `document` 컬럼이
아니라 service 가 채우는 **파생 필드**다. `from_attributes` 로 ORM 객체만 검증하면 이 둘이
없어 실패하므로, service 는 `DocumentRead.from_document(doc, content=..., content_html=...)`
classmethod 로 ORM 컬럼과 파생값을 함께 넘겨 구성한다(design.md §DocumentSchemas 4.4·4.5).
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.schemas.base import TimestampedRead

__all__ = [
    "DocumentCreate",
    "DocumentUpdate",
    "DocumentMoveRequest",
    "DocumentRead",
]


# 공백 제거 후 최소 1자를 요구하는 제목 타입(공백 전용 title 금지, 1.1).
_NonBlankTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# ORM document 컬럼이 아닌, service 가 채우는 파생 응답 필드.
_DERIVED_FIELDS = frozenset({"content", "content_html"})


class DocumentCreate(BaseModel):
    """문서/하위 문서 생성 요청 본문 (1.1·1.2).

    `title` 은 필수이며 공백 전용 제목은 거부된다. `parent_id` 가 None 이면 루트 문서,
    지정되면 해당 문서를 부모로 하는 하위 문서를 생성한다(부모 존재·active·동일 WS 검증은
    Service 소유). status=active·sort_order·created_by 는 서버가 채운다.
    """

    title: _NonBlankTitle
    parent_id: int | None = None


class DocumentUpdate(BaseModel):
    """문서 부분 갱신 요청 본문 (3.1·3.4).

    editor 이상 사용자가 제목을 갱신한다. 본문 내용 저장·버전 생성은 이 경계가 아니라
    s09(lock-version)에 위임하므로 title 외 필드를 두지 않는다. 이동/재정렬은
    `DocumentMoveRequest` 가 담당한다.
    """

    title: _NonBlankTitle | None = None


class DocumentMoveRequest(BaseModel):
    """문서 이동/재정렬 요청 본문 (4.1·4.5).

    `new_parent_id` 가 None 이면 root 로 이동, 지정되면 그 문서를 새 부모로 삼는다. 두 형제
    사이 삽입은 `before_sibling_id`·`after_sibling_id` 로 지정하며, 인접 `sort_order` 중간값
    부여 등 정렬 규약 확정은 Service 소유다(다른 형제 재배치 없음).
    """

    new_parent_id: int | None = None
    before_sibling_id: int | None = None
    after_sibling_id: int | None = None


class DocumentRead(TimestampedRead):
    """문서 응답용 정보 (1.1·10.1).

    s01 `TimestampedRead` 상속으로 id·created_at·updated_at 을 공통 제공한다. `status` 는 s01
    `document.status` ENUM(active/trashed/deleted)과 동일한 문자열이다. `content`·
    `content_html` 은 ORM 컬럼이 아닌 파생 필드이므로 `from_document` 로 함께 구성한다.
    """

    workspace_id: int
    parent_id: int | None
    title: str
    status: str
    sort_order: Decimal
    current_version_id: int | None
    created_by: int
    content: str
    content_html: str

    @classmethod
    def from_document(
        cls, document: object, *, content: str, content_html: str
    ) -> "DocumentRead":
        """ORM `document` 객체와 파생값(content·content_html)으로 응답을 구성한다.

        ORM 컬럼 필드는 속성 접근으로 읽고, ORM 에 없는 파생 필드는 인자로 주입한다.
        service 가 현재 버전 본문과 `MarkdownRenderer` 렌더 결과를 채워 호출하는 단일 경로다.
        """
        orm_fields = {
            name: getattr(document, name)
            for name in cls.model_fields
            if name not in _DERIVED_FIELDS
        }
        return cls(**orm_fields, content=content, content_html=content_html)
