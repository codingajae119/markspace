"""user_settings 요청/응답 스키마.

s01 공통 Read 규약(`ORMReadModel`, from_attributes)을 재사용하며 스키마 형태만
소유한다. 명명 규약(s01 §Base Schemas): `{Resource}Read`/`{Resource}Update`.

- `UserSettingsRead`   — 설정 응답. `UserSetting` ORM 객체로부터 직렬화되며,
  레코드가 없을 때는 서비스가 기본값으로 직접 생성해 반환한다.
- `UserSettingsUpdate` — 부분 수정 요청 본문. 모든 필드는 선택적(Optional)이며,
  전달되지 않은 필드는 기존 값을 유지한다(PATCH 시맨틱).
"""

from pydantic import BaseModel

from app.schemas.base import ORMReadModel

__all__ = ["UserSettingsRead", "UserSettingsUpdate"]


class UserSettingsRead(ORMReadModel):
    """현재 사용자 설정 응답 (레코드 부재 시 기본값으로 대체됨).

    s01 `ORMReadModel` 상속으로 `model_validate(user_setting)` 이 ORM 속성 접근으로
    동작한다. 선언된 필드만 직렬화되므로 내부 식별자(id·user_id)는 노출되지 않는다.
    """

    autosave_enabled: bool


class UserSettingsUpdate(BaseModel):
    """본인 설정 부분 수정 요청 본문.

    필드는 선택적으로 정의한다(부분 수정 규약). ``None`` 은 "변경하지 않음"을
    의미하며, 전달된 필드만 갱신한다.
    """

    autosave_enabled: bool | None = None
