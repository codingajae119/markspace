"""auth 요청/응답 스키마 (s02-auth design.md §auth/Contract #AuthSchemas).

s01 계약을 재사용하며 스키마 형태만 소유한다(Req 5.5). 공통 Read 규약(`ORMReadModel`)과
`ErrorResponse` 는 s01 소유이며 여기서 재정의하지 않는다.

- `LoginRequest` — `login_id`/`password` 로그인 요청 본문(Req 1.2).
- `AuthUserRead` — 로그인·me 응답. s01 `ORMReadModel`(from_attributes) 을 상속해 User ORM
  객체로부터 직렬화되며 `password_hash` 등 민감 필드를 절대 노출하지 않는다(Req 1.2·1.7).
- `PasswordChangeRequest` — 본인 비밀번호 변경 요청. 새 비밀번호 최소 길이 정책을 pydantic
  필드 검증으로 강제하고, 위반 시 s01 전역 핸들러가 422 validation_error 로 변환한다(Req 4.3).
"""

from pydantic import BaseModel, Field

from app.schemas.base import ORMReadModel

__all__ = ["LoginRequest", "AuthUserRead", "PasswordChangeRequest"]


class LoginRequest(BaseModel):
    """자격 증명 로그인 요청 본문 (Req 1.2)."""

    login_id: str
    password: str


class AuthUserRead(ORMReadModel):
    """로그인·me 응답용 비민감 사용자 정보 (Req 1.2·1.7).

    s01 `ORMReadModel` 상속으로 `model_validate(user)` 가 ORM 속성 접근으로 동작하며,
    선언된 필드만 직렬화되어 `password_hash` 등 민감 필드는 노출되지 않는다.
    """

    id: int
    login_id: str
    name: str
    email: str | None = None
    is_admin: bool


class PasswordChangeRequest(BaseModel):
    """본인 비밀번호 변경 요청 본문 (Req 4.3).

    `new_password` 는 최소 길이 정책(8자)을 강제한다. 위반 시 pydantic
    `ValidationError` 가 발생하고 s01 전역 핸들러가 422 응답으로 변환한다.
    """

    current_password: str
    new_password: str = Field(min_length=8)
