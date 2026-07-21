"""user_settings 스키마 단위 테스트.

명명 규약(`{Resource}Read`/`{Resource}Update`)과 스키마 동작을 검증한다:
- `UserSettingsRead` 는 ORM 객체로부터 직렬화되며 내부 식별자(id·user_id)를 노출하지 않는다.
- `UserSettingsUpdate` 는 부분 수정 본문으로 모든 필드가 선택적(기본 None)이다.
"""

from app.models import UserSetting
from app.user_settings.schemas import UserSettingsRead, UserSettingsUpdate


def test_read_serializes_from_orm_object_and_hides_internal_ids():
    setting = UserSetting(
        id=5, user_id=42, autosave_enabled=True, last_selected_workspace_id=7
    )

    read = UserSettingsRead.model_validate(setting)

    dumped = read.model_dump()
    assert dumped == {"autosave_enabled": True, "last_selected_workspace_id": 7}
    # 내부 식별자는 응답 계약에 노출되지 않는다.
    assert "id" not in dumped
    assert "user_id" not in dumped


def test_read_last_selected_workspace_defaults_none_when_unset():
    setting = UserSetting(id=5, user_id=42, autosave_enabled=True)

    read = UserSettingsRead.model_validate(setting)

    assert read.last_selected_workspace_id is None


def test_read_can_be_constructed_directly_for_default_case():
    read = UserSettingsRead(autosave_enabled=False)
    assert read.autosave_enabled is False
    assert read.last_selected_workspace_id is None


def test_update_all_fields_optional_default_none():
    empty = UserSettingsUpdate()
    assert empty.autosave_enabled is None
    assert empty.last_selected_workspace_id is None


def test_update_accepts_explicit_value():
    payload = UserSettingsUpdate(autosave_enabled=True, last_selected_workspace_id=9)
    assert payload.autosave_enabled is True
    assert payload.last_selected_workspace_id == 9
