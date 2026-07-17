"""잠금·저장·버전 요청/응답 스키마 (design.md §Components and Interfaces #LockVersionSchemas).

s01 Base Schemas 규약(`{Resource}Read`·`ORMReadModel`·`Page[T]`)을 상속하며 스키마 형태만
소유한다(design.md §Data Contracts, Req 7.5). 공통 Read 베이스(`ORMReadModel`)와 `Page[T]` 는
s01 소유이며 여기서 재정의하지 않는다.

- `DocumentSaveRequest` — 저장 요청. `content`(markdown 본문 스냅샷)만 받으며 **빈 문자열을
  허용**한다(2.1·2.6). s07 create/update 요청처럼 순수 `BaseModel`(ORM-read 아님)이다.
- `DocumentLockRead` — 잠금 획득/보유 정보 응답(1.1). `ORMReadModel` 상속으로 잠금 필드를
  속성 객체(from_attributes)로부터 직렬화한다. `document_id` 는 대상 문서 식별자다.
- `DocumentVersionRead` — 버전 메타데이터 응답(5.1·5.4). `ORMReadModel` 상속. 과거 본문
  조회·rollback 을 제공하지 않으므로(design §Non-Goals, 5.3) **본문(content) 필드를 두지
  않는다** — 식별자·저장자·저장 시각 메타데이터만 노출한다. 목록은 `Page[DocumentVersionRead]`.
"""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.base import ORMReadModel

__all__ = [
    "DocumentSaveRequest",
    "DocumentLockRead",
    "DocumentVersionRead",
]


class DocumentSaveRequest(BaseModel):
    """저장 요청 본문 (2.1·2.6).

    잠금 보유자가 저장할 markdown 본문 스냅샷을 담는다. `content` 는 필수이며 **빈 문자열을
    허용**한다(빈 문서 저장). 버전 생성·`current_version_id` 갱신·잠금 해제는 Service 소유다.
    """

    content: str


class DocumentLockRead(ORMReadModel):
    """편집 잠금 획득/보유 정보 응답 (1.1).

    s01 `ORMReadModel`(from_attributes) 상속으로 잠금 보유 상태를 속성 객체로부터 직렬화한다.
    잠금 판정 근거는 `document.lock_user_id` 단일 컬럼(INV-9)이며, 이 응답은 잠금이 설정된
    상태(요청자·획득 시각 존재)를 표현한다.
    """

    document_id: int
    lock_user_id: int
    lock_acquired_at: datetime


class DocumentVersionRead(ORMReadModel):
    """저장 버전 메타데이터 응답 (5.1·5.4).

    s01 `ORMReadModel`(from_attributes) 상속으로 `document_version` 속성 객체로부터 식별자·
    저장자·저장 시각만 직렬화한다. 과거 본문 조회·rollback 미제공(design §Non-Goals, 5.3)이므로
    본문(content) 필드를 포함하지 않는다. 목록은 `Page[DocumentVersionRead]` 로 반환한다.
    """

    id: int
    document_id: int
    created_by: int
    created_at: datetime
