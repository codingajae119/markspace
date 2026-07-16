"""admin_account User 요청/응답 스키마 (design.md §Components and Interfaces #UserSchemas).

s01 Base Schemas 규약(`{Resource}Create/Read/Update`)을 상속하며 스키마 형태만 소유한다
(design.md §Data Contracts, Req 8.1). 공통 Read 베이스(`TimestampedRead`)와 `Page[T]` 는
s01 소유이며 여기서 재정의하지 않는다.

- `UserCreate` — 신규 계정 생성 요청. login_id·password·name 필수, email 선택. 관리자 표시나
  상태 flag 는 입력받지 않는다(Req 2.1·2.6, 승격 금지 D3).
- `UserRead` — 계정 응답. s01 `TimestampedRead`(id·created_at·updated_at) 를 상속해 User ORM
  객체로부터 직렬화되며 `password_hash` 등 민감 필드를 절대 노출하지 않는다(Req 3.2·8.1).
- `UserUpdate` — 부분 갱신 요청. name·email·is_active·is_deleted 만 선택적으로 받고 `is_admin`
  은 포함하지 않는다(Req 2.6, 승격 금지 D3).
- `AdminPasswordResetRequest` — admin 비밀번호 재설정 요청. 새 비밀번호 필수(Req 7.5).

NOTE: pydantic `EmailStr` 은 `email-validator` 패키지에 의존하나 프로젝트에 미설치되어 있고
(s02 `AuthUserRead` 도 동일 이유로 `str`), 신규 의존성 추가는 boundary 제약상 금지되어
`email` 은 `str | None` 으로 둔다.
"""

from pydantic import BaseModel

from app.schemas.base import TimestampedRead

__all__ = ["UserCreate", "UserRead", "UserUpdate", "AdminPasswordResetRequest"]


class UserCreate(BaseModel):
    """신규 사용자 생성 요청 본문 (Req 2.1·2.6).

    login_id·password·name 은 필수, email 은 선택이다. 비밀번호는 서비스가 즉시 해싱한다
    (평문 저장 금지). 관리자 표시(`is_admin`)나 상태 flag(`is_active`/`is_deleted`) 는
    입력받지 않아 애플리케이션 경로의 승격을 원천 차단한다(D3).
    """

    login_id: str
    password: str
    name: str
    email: str | None = None


class UserRead(TimestampedRead):
    """계정 응답용 사용자 정보 (Req 3.2·8.1).

    s01 `TimestampedRead` 상속으로 id·created_at·updated_at 을 공통 제공하고
    `model_validate(user)` 가 ORM 속성 접근으로 동작한다. 선언된 필드만 직렬화되어
    `password_hash` 등 민감 필드는 노출되지 않는다.
    """

    login_id: str
    name: str
    email: str | None = None
    is_admin: bool
    is_active: bool
    is_deleted: bool


class UserUpdate(BaseModel):
    """계정 부분 갱신 요청 본문 (Req 4·5·6, 2.6).

    이름·이메일 및 상태 flag(`is_active`/`is_deleted`) 를 선택적으로 갱신한다. 두 상태
    flag 는 독립적으로 취급된다(Req 4.5·6.2). `is_admin` 은 포함하지 않아 애플리케이션
    경로의 승격·강등을 차단한다(D3).
    """

    name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    is_deleted: bool | None = None


class AdminPasswordResetRequest(BaseModel):
    """admin 비밀번호 재설정 요청 본문 (Req 7.5).

    `new_password` 는 필수이며 서비스가 즉시 해싱하여 저장한다(평문 저장 금지).
    """

    new_password: str
