"""워크스페이스·멤버십 요청/응답 스키마 (design.md §Components and Interfaces #WsMemberSchemas).

s01 Base Schemas 규약(`{Resource}Create/Read/Update`)을 상속하며 스키마 형태만 소유한다
(design.md §Data Contracts, Req 6.1). 공통 Read 베이스(`TimestampedRead`·`ORMReadModel`)와
`Page[T]` 는 s01 소유이며 여기서 재정의하지 않는다.

- `WorkspaceCreate` — 생성 요청. `name` 필수·공백 금지(2.1). 서버가 채우는 `is_shareable`·
  `trash_retention_days` 는 입력받지 않는다(생성 시 서비스가 기본값 적용).
- `WorkspaceUpdate` — 부분 갱신 요청. name·is_shareable·trash_retention_days 를 선택적으로
  받는다(2.1·2.2·2.3).
- `WorkspaceRead` — 응답. s01 `TimestampedRead`(id·created_at·updated_at) 를 상속해 Workspace
  ORM 객체로부터 직렬화된다(1.2·6.1).
- `MemberRole` — API 표현용 **문자열** Enum. 값은 s01 `workspace_member.role` ENUM
  (owner/editor/viewer)과 동일하다. **s01 `Role`(IntEnum, 위계 비교용)과는 별개다**: 권한
  게이팅에는 s01 `Role` 을, 요청/응답 직렬화에는 이 `MemberRole` 을 사용한다.
- `MemberCreate`/`MemberUpdate`/`MemberRead` — 멤버 추가·role 변경·응답 스키마(3.1·3.5).
- `OwnerChangeRequest` — admin 소유권 변경 요청. `new_owner_user_id` 필수(5.1).
"""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.schemas.base import ORMReadModel, TimestampedRead

__all__ = [
    "MemberRole",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceRead",
    "MemberCreate",
    "MemberUpdate",
    "MemberRead",
    "OwnerChangeRequest",
]


# 공백 제거 후 최소 1자를 요구하는 이름 타입(공백 전용 이름 금지, 2.1).
_NonBlankName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MemberRole(str, Enum):
    """멤버 role 의 API 직렬화용 문자열 Enum (3.4·6.1).

    문자열 값은 s01 `workspace_member.role` ENUM(owner/editor/viewer)과 동일하다.
    위계 비교·admin bypass 판정용 s01 `Role`(IntEnum)과는 별개의 타입이다.
    """

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class WorkspaceCreate(BaseModel):
    """워크스페이스 생성 요청 본문 (2.1).

    `name` 은 필수이며 공백 전용 이름은 거부된다. `is_shareable`·`trash_retention_days` 는
    입력받지 않고 서비스가 기본값(False·Settings 기본 보관일)으로 초기화한다.
    """

    name: _NonBlankName


class WorkspaceUpdate(BaseModel):
    """워크스페이스 부분 갱신 요청 본문 (2.1·2.2·2.3).

    owner/admin 이 이름·공유 게이트·보관일을 선택적으로 갱신한다. `trash_retention_days`
    의 양의 정수(>0) 규칙은 서비스에서 검증한다(형식 위반은 여기 pydantic 이 거부).
    """

    name: _NonBlankName | None = None
    is_shareable: bool | None = None
    trash_retention_days: int | None = None


class WorkspaceRead(TimestampedRead):
    """워크스페이스 응답용 정보 (1.2·6.1).

    s01 `TimestampedRead` 상속으로 id·created_at·updated_at 을 공통 제공하고
    `model_validate(workspace)` 가 ORM 속성 접근으로 동작한다.
    """

    name: str
    is_shareable: bool
    trash_retention_days: int


class MemberCreate(BaseModel):
    """멤버 추가 요청 본문 (3.1·3.4).

    `user_id` 는 전체 사용자 목록에서 선택하며, `role` 은 `MemberRole` 값만 허용한다
    (잘못된 role 문자열은 pydantic 이 거부).
    """

    user_id: int
    role: MemberRole


class MemberUpdate(BaseModel):
    """멤버 role 변경 요청 본문 (3.5)."""

    role: MemberRole


class MemberRead(ORMReadModel):
    """멤버십 응답용 정보 (6.1).

    s01 `ORMReadModel` 상속으로 `model_validate(member)` 가 workspace_member ORM 객체로부터
    동작한다. `role` 은 s01 ENUM 문자열과 동일한 `MemberRole` 로 직렬화된다.
    """

    id: int
    workspace_id: int
    user_id: int
    role: MemberRole


class OwnerChangeRequest(BaseModel):
    """admin 소유권 변경 요청 본문 (5.1).

    `new_owner_user_id` 는 필수이며, 서비스가 해당 사용자를 owner 로 upsert 한다.
    """

    new_owner_user_id: int
