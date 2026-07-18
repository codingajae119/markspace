"""user_settings 범위 데이터 접근.

본인 ``user_setting`` 행 조회와 upsert(없으면 생성, 있으면 갱신)만 소유한다.
s01 ``UserSetting`` 모델과 요청 스코프 세션(``get_db``)을 재사용하며 재정의하지
않는다. ``user_id`` UNIQUE 제약으로 사용자당 최대 한 행이 보장된다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserSetting

__all__ = ["UserSettingRepository"]


class UserSettingRepository:
    """본인 user_setting 조회·upsert."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_user_id(self, user_id: int) -> UserSetting | None:
        """``user_id`` 로 설정 행을 조회한다. 없으면 None 을 반환한다."""
        return self._db.scalar(
            select(UserSetting).where(UserSetting.user_id == user_id)
        )

    def upsert(self, user_id: int, autosave_enabled: bool) -> UserSetting:
        """설정 행을 생성하거나(없을 때) 갱신하고(있을 때) commit 하여 영속화한다.

        ``user_id`` UNIQUE 로 사용자당 한 행만 존재하므로, 조회 후 없으면 INSERT,
        있으면 UPDATE 한다. 갱신된(또는 생성된) 행을 반환한다.
        """
        setting = self.get_by_user_id(user_id)
        if setting is None:
            setting = UserSetting(user_id=user_id, autosave_enabled=autosave_enabled)
            self._db.add(setting)
        else:
            setting.autosave_enabled = autosave_enabled
        self._db.commit()
        self._db.refresh(setting)
        return setting
