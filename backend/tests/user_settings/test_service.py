"""UserSettingsService 단위 테스트 (DB 불필요, 가짜 저장소 + Settings 주입).

핵심 불변식:
- get: 레코드가 있으면 그 값, 없으면 공용 Settings `default_autosave_enabled` 를 반환한다(순수 조회, upsert 없음).
- update: 전달된 필드만 갱신하고, None 필드는 현재 유효값(기존 레코드 값 또는 기본값)을 유지한 뒤 upsert 한다.
- 대상은 항상 ctx.user_id (본인 것만).
"""

from types import SimpleNamespace

import pytest

from app.common.auth import AuthContext
from app.models import UserSetting
from app.user_settings.schemas import UserSettingsRead, UserSettingsUpdate
from app.user_settings.service import UserSettingsService


class _FakeRepo:
    """user_id → UserSetting 을 dict 로 흉내내는 최소 가짜 저장소."""

    def __init__(self, existing: UserSetting | None = None) -> None:
        self._store: dict[int, UserSetting] = {}
        if existing is not None:
            self._store[existing.user_id] = existing
        self.upsert_calls: list[tuple[int, bool]] = []

    def get_by_user_id(self, user_id: int) -> UserSetting | None:
        return self._store.get(user_id)

    def upsert(self, user_id: int, autosave_enabled: bool) -> UserSetting:
        self.upsert_calls.append((user_id, autosave_enabled))
        setting = self._store.get(user_id)
        if setting is None:
            setting = UserSetting(id=1, user_id=user_id, autosave_enabled=autosave_enabled)
            self._store[user_id] = setting
        else:
            setting.autosave_enabled = autosave_enabled
        return setting


def _ctx(user_id: int = 42) -> AuthContext:
    return AuthContext(user_id=user_id, is_admin=False)


@pytest.fixture
def default_true(monkeypatch):
    """공용 Settings 기본값 default_autosave_enabled=True 로 주입."""
    monkeypatch.setattr(
        "app.user_settings.service.get_settings",
        lambda: SimpleNamespace(default_autosave_enabled=True),
    )


@pytest.fixture
def default_false(monkeypatch):
    """공용 Settings 기본값 default_autosave_enabled=False 로 주입."""
    monkeypatch.setattr(
        "app.user_settings.service.get_settings",
        lambda: SimpleNamespace(default_autosave_enabled=False),
    )


# --- get -----------------------------------------------------------------------


def test_get_returns_default_when_no_record(default_true):
    repo = _FakeRepo(existing=None)
    service = UserSettingsService(repo)

    result = service.get(_ctx())

    assert isinstance(result, UserSettingsRead)
    assert result.autosave_enabled is True  # 기본값
    # 순수 조회는 upsert 를 유발하지 않는다.
    assert repo.upsert_calls == []


def test_get_returns_stored_value_over_default(default_true):
    existing = UserSetting(id=1, user_id=42, autosave_enabled=False)
    service = UserSettingsService(_FakeRepo(existing))

    result = service.get(_ctx())

    # 기본값이 True 여도 저장된 False 가 우선한다.
    assert result.autosave_enabled is False


# --- update --------------------------------------------------------------------


def test_update_sets_value_creating_record_when_absent(default_false):
    repo = _FakeRepo(existing=None)
    service = UserSettingsService(repo)

    result = service.update(_ctx(), UserSettingsUpdate(autosave_enabled=True))

    assert result.autosave_enabled is True
    assert repo.upsert_calls == [(42, True)]


def test_update_none_keeps_existing_value(default_false):
    existing = UserSetting(id=1, user_id=42, autosave_enabled=True)
    repo = _FakeRepo(existing)
    service = UserSettingsService(repo)

    # 빈 PATCH(autosave_enabled=None) 는 기존 True 를 유지한다.
    result = service.update(_ctx(), UserSettingsUpdate())

    assert result.autosave_enabled is True
    assert repo.upsert_calls == [(42, True)]


def test_update_none_uses_default_when_no_record(default_true):
    repo = _FakeRepo(existing=None)
    service = UserSettingsService(repo)

    # 레코드 없음 + 빈 PATCH → 기본값(True)로 upsert.
    result = service.update(_ctx(), UserSettingsUpdate())

    assert result.autosave_enabled is True
    assert repo.upsert_calls == [(42, True)]


def test_update_targets_only_ctx_user(default_false):
    repo = _FakeRepo(existing=None)
    service = UserSettingsService(repo)

    service.update(_ctx(user_id=7), UserSettingsUpdate(autosave_enabled=True))

    # upsert 대상 user_id 는 항상 ctx.user_id 다(본인 것만).
    assert repo.upsert_calls == [(7, True)]
