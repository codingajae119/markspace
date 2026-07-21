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
- `MemberRole` — API 표현용 **문자열** Enum. 값은 owner/member 2값이다(s26 Req 1.3, editor·
  viewer 제거). 이관 후 s01 `workspace_member.role` ENUM(owner/member, migration 0004)과 동일하다.
  **s01 `Role`(IntEnum, 위계 비교용)과는 별개다**: 권한 게이팅에는 s01 `Role` 을, 요청/응답
  직렬화에는 이 `MemberRole` 을 사용한다.
- `MemberCreate`/`MemberUpdate`/`MemberRead` — 멤버 추가·role 변경·응답 스키마(3.1·3.5).
- `OwnerChangeRequest` — admin 소유권 변경 요청. `new_owner_user_id` 필수(5.1).
- `AssignableUserRead` — 배정 가능 사용자 narrow 응답. 선언 필드(`id`·`name`·`email`)만
  직렬화해 계정 필드(`login_id`·`password_hash`·상태 flag·타임스탬프) 누출을 원천 차단한다
  (s23 Req 1.2·1.3). `admin_account.UserRead` 는 상태 flag 를 노출하므로 재사용하지 않는다.
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
    "AssignableUserRead",
    "MemberRosterRead",
]


# 공백 제거 후 최소 1자를 요구하는 이름 타입(공백 전용 이름 금지, 2.1).
_NonBlankName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MemberRole(str, Enum):
    """멤버 role 의 API 직렬화용 문자열 Enum (s26 Req 1.3·5.5, design D6).

    값은 owner/member 2값으로만 정의된다(editor·viewer 제거). 이 값 집합 축소로
    `MemberCreate`/`MemberUpdate` 의 `role: MemberRole` 필드가 "editor"/"viewer"
    요청을 pydantic 계층에서 자동 422 로 거부한다(Req 1.4, 서비스 재검증 없음).
    이관 후 s01 `workspace_member.role` ENUM(owner/member, migration 0004)과 동일하다.
    위계 비교·admin bypass 판정용 s01 `Role`(IntEnum)과는 별개의 타입이다.
    """

    OWNER = "owner"
    MEMBER = "member"


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

    `role` 은 호출자 관점의 멤버십 role 을 담는 가산 optional 필드다(s24 Req 1.1·1.5).
    목록 경로만 명시 주입하며(후속 task), 그 외 경로·role 속성이 없는 ORM `Workspace`
    를 `model_validate` 하면 기본값 None 으로 검증을 통과한다(하위 호환). admin 여부에
    따른 role 상승은 담지 않는다(INV-3, Req 1.2).
    """

    name: str
    is_shareable: bool
    trash_retention_days: int
    role: MemberRole | None = None


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


class AssignableUserRead(ORMReadModel):
    """배정 가능 사용자 narrow 응답용 정보 (s23 Req 1.2·1.3).

    s01 `ORMReadModel`(from_attributes) 상속으로 `model_validate(user)` 가 `User` ORM
    객체로부터 동작하되, **선언 필드만** 직렬화한다. `login_id`·`password_hash`·상태
    flag(`is_admin`/`is_active`/`is_deleted`)·타임스탬프(`created_at`/`updated_at`)는
    선언하지 않으므로 직렬화 대상에서 원천 제외된다(별도 화이트리스트 불필요, 1.2).
    `email` 은 nullable 이며 null 인 사용자도 검증을 통과한다(제외하지 않음, 1.3).
    """

    id: int
    name: str
    email: str | None = None


class MemberRosterRead(BaseModel):
    """멤버 로스터 행 narrow 응답용 정보 (Req 1.2·2.6).

    join 프로젝션(workspace_member ⋈ user)이므로 단일 ORM 엔티티가 아니다. 따라서
    `ORMReadModel`(from_attributes)을 상속하지 않고 `BaseModel` 을 상속해 `id→user_id`
    리네임 모호를 피하고, 서비스가 각 필드를 명시 생성한다(design.md §MemberRosterRead,
    research §6.3). **선언한 4필드만** 직렬화하므로 `login_id`·`password_hash`·상태
    flag(`is_admin`/`is_active`/`is_deleted`)·타임스탬프(`created_at`/`updated_at`)는
    응답 대상에서 원천 제외된다(별도 화이트리스트 불필요, 2.6).
    `email` 은 nullable 이며, 이메일이 없는(또는 비활성/삭제) 멤버도 `email: null` 로
    로스터에 포함된다(1.2·1.5). `role` 은 s01 ENUM 문자열과 동일한 `MemberRole` 로
    직렬화된다(위계 비교용 s01 `Role`(IntEnum)과는 별개).
    """

    user_id: int
    name: str
    email: str | None = None
    role: MemberRole
