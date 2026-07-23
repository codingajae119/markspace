"""UserSettingRepository 통합 테스트 (real DB).

design 계약을 검증한다:
- `get_by_user_id` 는 없는 사용자에 None 을, 있으면 해당 행을 반환한다.
- `upsert` 는 레코드가 없으면 생성(INSERT), 있으면 갱신(UPDATE)하고 commit 하여 영속화한다.
- `user_id` UNIQUE 로 사용자당 한 행만 유지된다(반복 upsert 후에도 단일 행).

격리: tests/auth/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base
from app.models import User, UserSetting
from app.user_settings.repository import UserSettingRepository

TEST_DB_NAME = "markspace_test"


def _drop_everything(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        names = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ]
        for name in names:
            conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def _make_user(session, *, login_id="alice") -> User:
    user = User(
        login_id=login_id,
        password_hash="hash",
        name="테스트 사용자",
        email=None,
        is_admin=False,
        is_active=True,
        is_deleted=False,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def sessionmaker_factory():
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    _drop_everything(engine)
    Base.metadata.create_all(engine)

    try:
        yield TestSessionLocal
    finally:
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


def test_get_by_user_id_returns_none_when_missing(sessionmaker_factory):
    session = sessionmaker_factory()
    try:
        repo = UserSettingRepository(session)
        assert repo.get_by_user_id(999999) is None
    finally:
        session.close()


def test_upsert_creates_row_when_absent(sessionmaker_factory):
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="alice")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserSettingRepository(session)
        created = repo.upsert(user_id, True, None)
        assert created.user_id == user_id
        assert created.autosave_enabled is True
    finally:
        session.close()

    # fresh 조회로 영속화 증명.
    verify = sessionmaker_factory()
    try:
        reloaded = verify.scalar(
            select(UserSetting).where(UserSetting.user_id == user_id)
        )
        assert reloaded is not None
        assert reloaded.autosave_enabled is True
    finally:
        verify.close()


def test_upsert_updates_existing_row_keeping_single_row(sessionmaker_factory):
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="bob")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    # 최초 upsert(생성) → 이후 반대 값으로 재차 upsert(갱신).
    session = sessionmaker_factory()
    try:
        repo = UserSettingRepository(session)
        repo.upsert(user_id, True, None)
    finally:
        session.close()

    session = sessionmaker_factory()
    try:
        repo = UserSettingRepository(session)
        updated = repo.upsert(user_id, False, None)
        assert updated.autosave_enabled is False
    finally:
        session.close()

    # 값이 갱신되고, user_id UNIQUE 로 행은 여전히 하나여야 한다.
    verify = sessionmaker_factory()
    try:
        count = verify.scalar(
            select(func.count())
            .select_from(UserSetting)
            .where(UserSetting.user_id == user_id)
        )
        assert count == 1
        reloaded = verify.scalar(
            select(UserSetting).where(UserSetting.user_id == user_id)
        )
        assert reloaded.autosave_enabled is False
    finally:
        verify.close()


def test_upsert_persists_last_selected_workspace(sessionmaker_factory):
    """last_selected_workspace_id 가 INSERT·UPDATE 모두에서 영속화되고 재조회로 확인된다."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="carol")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    # 최초 upsert(생성) 시 워크스페이스 5 선택.
    session = sessionmaker_factory()
    try:
        repo = UserSettingRepository(session)
        created = repo.upsert(user_id, True, 5)
        assert created.last_selected_workspace_id == 5
    finally:
        session.close()

    # 재조회로 영속화 확인 후, 이후 upsert(갱신)로 9 로 전환.
    session = sessionmaker_factory()
    try:
        repo = UserSettingRepository(session)
        reloaded = repo.get_by_user_id(user_id)
        assert reloaded is not None
        assert reloaded.last_selected_workspace_id == 5
        updated = repo.upsert(user_id, True, 9)
        assert updated.last_selected_workspace_id == 9
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        final = verify.scalar(
            select(UserSetting).where(UserSetting.user_id == user_id)
        )
        assert final.last_selected_workspace_id == 9
    finally:
        verify.close()
