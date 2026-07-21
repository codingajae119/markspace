"""user_settings 동작 오케스트레이션.

세션(s02)이 확정한 현재 사용자(``ctx.user_id``) 본인의 설정만 조회·수정한다.
대상은 **항상** ``ctx.user_id`` 이며 다른 사용자를 지정할 인자를 노출하지 않는다
(본인 것만, s02 비밀번호 변경과 동일한 원칙).

기본값 대체: ``user_setting`` 레코드가 없으면 s01 단일 Settings 의
``default_autosave_enabled`` 를 반환한다. 설정은 호출 시점에 ``get_settings()`` 로
읽어(캐시된 단일 인스턴스) ``os.environ`` 직접 접근 없이 주입된다.
"""

from app.common.auth import AuthContext
from app.config import get_settings
from app.user_settings.repository import UserSettingRepository
from app.user_settings.schemas import UserSettingsRead, UserSettingsUpdate

__all__ = ["UserSettingsService"]


class UserSettingsService:
    """본인 설정 조회·수정 오케스트레이션."""

    def __init__(self, repo: UserSettingRepository) -> None:
        self._repo = repo

    def get(self, ctx: AuthContext) -> UserSettingsRead:
        """현재 사용자 본인 설정을 조회한다.

        레코드가 있으면 그 값을, 없으면 공용 Settings 기본값
        (``default_autosave_enabled``)으로 채운 :class:`UserSettingsRead` 를 반환한다.
        레코드를 만들지 않는 순수 조회다.
        """
        setting = self._repo.get_by_user_id(ctx.user_id)
        if setting is None:
            return UserSettingsRead(
                autosave_enabled=get_settings().default_autosave_enabled
            )
        return UserSettingsRead.model_validate(setting)

    def update(self, ctx: AuthContext, payload: UserSettingsUpdate) -> UserSettingsRead:
        """현재 사용자 본인 설정을 부분 수정한다(PATCH 시맨틱).

        전달되지 않은(``None``) 필드는 현재 유효값을 유지한다. 현재 유효값은 기존
        레코드가 있으면 그 값, 없으면 공용 Settings 기본값이다. 결정된 값으로 본인
        행을 upsert 하고 갱신된 설정을 반환한다.
        """
        setting = self._repo.get_by_user_id(ctx.user_id)
        current_autosave = (
            setting.autosave_enabled
            if setting is not None
            else get_settings().default_autosave_enabled
        )
        autosave_enabled = (
            payload.autosave_enabled
            if payload.autosave_enabled is not None
            else current_autosave
        )
        # 마지막 선택 워크스페이스: 레코드 없으면 미선택(None)이 현재 유효값이다.
        current_last_ws = (
            setting.last_selected_workspace_id if setting is not None else None
        )
        last_selected_workspace_id = (
            payload.last_selected_workspace_id
            if payload.last_selected_workspace_id is not None
            else current_last_ws
        )
        updated = self._repo.upsert(
            ctx.user_id, autosave_enabled, last_selected_workspace_id
        )
        return UserSettingsRead.model_validate(updated)
