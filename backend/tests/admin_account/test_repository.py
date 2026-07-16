"""UserRepository 통합 테스트 (Task 2.1 / Req 2.2, 3.1, 3.3, 3.4, 4.1, 5.1, 6.1, 7.1, 8.3).

design.md §Components and Interfaces #UserRepository 계약을 검증한다:
- `create` 는 기본 상태(`is_active=True`·`is_deleted=False`·`is_admin=False`)로 행을
  생성하고 fresh 세션 재조회로 영속화를 증명한다(Req 2.2).
- `apply_updates` 는 제공된 키만 부분 갱신하며 `is_deleted`·`is_active` 를 독립적으로
  전환한다(한 flag 전환이 다른 flag 를 건드리지 않음, Req 4.5·6.2). soft-delete 후에도
  레코드가 물리적으로 존재함을 증명한다(INV-4, Req 8.3).
- `list_paginated` 는 삭제·비활동 계정을 제외하지 않고 반환하며 total 은 전체(삭제 포함)
  개수다. limit/offset 으로 페이지네이션한다(Req 3.1·3.3·3.4).
- `get_by_id`·`get_by_login_id` 는 행 또는 None 을 반환한다.
- `set_password_hash` 는 password_hash 를 교체하고 fresh 재조회로 영속화를 증명한다(Req 7.1).

격리: tests/auth/test_repository.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME` 을
전용 테스트 DB(`notion_lite_test`)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두 제거하고 엔진을 dispose
한 뒤 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.admin_account.repository import UserRepository
from app.common.db import Base
from app.models import User

TEST_DB_NAME = "notion_lite_test"


def _drop_everything(engine) -> None:
    """대상 DB 의 모든 테이블을 FK 무시하고 제거해 빈 상태로 만든다(견고한 teardown)."""
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


def _make_user(
    session,
    *,
    login_id,
    password_hash="hash-initial",
    is_admin=False,
    is_active=True,
    is_deleted=False,
):
    """테스트 DB 에 User 를 삽입하고 flush 하여 id 를 확정한다."""
    user = User(
        login_id=login_id,
        password_hash=password_hash,
        name="테스트 사용자",
        email=None,
        is_admin=is_admin,
        is_active=is_active,
        is_deleted=is_deleted,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def sessionmaker_factory():
    """테스트 DB 를 마이그레이션하고 세션 팩토리를 제공한다(격리·원복 보증)."""
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    TestSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    _drop_everything(engine)  # 시작 전 빈 상태 보증(격리 전제).
    Base.metadata.create_all(engine)  # 마이그레이션된 DB 계약을 물리적으로 생성.

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


# --- create --------------------------------------------------------------


def test_create_sets_default_flags_and_persists(sessionmaker_factory):
    """create 는 is_active=True·is_deleted=False·is_admin=False 로 생성하고 영속화한다 (Req 2.2)."""
    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        created = repo.create(
            session,
            login_id="new-user",
            password_hash="hash-new",
            name="새 사용자",
            email="new@example.com",
        )
        assert created.is_active is True
        assert created.is_deleted is False
        assert created.is_admin is False
        assert created.login_id == "new-user"
        assert created.password_hash == "hash-new"
        assert created.email == "new@example.com"
        assert created.created_at is not None
        user_id = created.id
        assert user_id is not None
    finally:
        session.close()

    # fresh 세션 재조회로 commit 영속화를 증명한다.
    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded is not None, "생성된 행이 영속되어야 한다"
        assert reloaded.is_active is True
        assert reloaded.is_deleted is False
        assert reloaded.is_admin is False
        assert reloaded.login_id == "new-user"
    finally:
        verify.close()


def test_create_accepts_none_email(sessionmaker_factory):
    """email 은 선택이며 None 으로 생성할 수 있다."""
    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        created = repo.create(
            session,
            login_id="no-email",
            password_hash="h",
            name="이메일없음",
            email=None,
        )
        user_id = created.id
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded is not None
        assert reloaded.email is None
    finally:
        verify.close()


# --- get_by_id / get_by_login_id ----------------------------------------


def test_get_by_id_returns_user_or_none(sessionmaker_factory):
    """get_by_id 는 존재 시 행을, 미존재 시 None 을 반환한다."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="byid")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        found = repo.get_by_id(session, user_id)
        assert found is not None
        assert found.id == user_id
        assert found.login_id == "byid"
        assert repo.get_by_id(session, 999999) is None
    finally:
        session.close()


def test_get_by_login_id_returns_user_or_none(sessionmaker_factory):
    """get_by_login_id 는 존재 시 행을, 미존재 시 None 을 반환한다."""
    seed = sessionmaker_factory()
    try:
        _make_user(seed, login_id="bylogin")
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        found = repo.get_by_login_id(session, "bylogin")
        assert found is not None
        assert found.login_id == "bylogin"
        assert repo.get_by_login_id(session, "nobody") is None
    finally:
        session.close()


# --- list_paginated ------------------------------------------------------


def test_list_paginated_includes_deleted_and_inactive(sessionmaker_factory):
    """목록은 삭제·비활동 계정을 제외하지 않고 total 은 전체 개수다 (Req 3.1·3.3)."""
    seed = sessionmaker_factory()
    try:
        _make_user(seed, login_id="active-1")
        _make_user(seed, login_id="inactive-1", is_active=False)
        _make_user(seed, login_id="deleted-1", is_deleted=True)
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        items, total = repo.list_paginated(session, limit=100, offset=0)
        logins = {u.login_id for u in items}
        assert total == 3, "total 은 삭제·비활동 포함 전체 개수여야 한다"
        assert logins == {"active-1", "inactive-1", "deleted-1"}, (
            "삭제·비활동 계정도 목록에 포함되어야 한다"
        )
    finally:
        session.close()


def test_list_paginated_applies_limit_and_offset(sessionmaker_factory):
    """limit/offset 은 items 에만 적용되고 total 은 전체를 반영한다 (Req 3.4)."""
    seed = sessionmaker_factory()
    try:
        for i in range(5):
            _make_user(seed, login_id=f"page-{i}")
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        items, total = repo.list_paginated(session, limit=2, offset=0)
        assert total == 5
        assert len(items) == 2

        items2, total2 = repo.list_paginated(session, limit=2, offset=4)
        assert total2 == 5
        assert len(items2) == 1  # 마지막 페이지 잔여 1건
    finally:
        session.close()


# --- apply_updates -------------------------------------------------------


def test_apply_updates_soft_delete_keeps_record(sessionmaker_factory):
    """is_deleted=True 전환은 레코드를 물리 삭제하지 않는다 (INV-4, Req 4.1·8.3)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="to-delete")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        user = repo.get_by_id(session, user_id)
        repo.apply_updates(session, user, {"is_deleted": True})
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded is not None, "soft-delete 후에도 행이 물리적으로 존재해야 한다"
        assert reloaded.is_deleted is True
        assert reloaded.is_active is True, "is_deleted 전환이 is_active 를 건드리면 안 된다"
    finally:
        verify.close()


def test_apply_updates_toggles_flags_independently(sessionmaker_factory):
    """is_active 와 is_deleted 는 독립 전환된다 (Req 4.5·6.2)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="indep", is_active=True, is_deleted=False)
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    # is_active 만 False 로 전환 → is_deleted 는 그대로 False.
    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        user = repo.get_by_id(session, user_id)
        repo.apply_updates(session, user, {"is_active": False})
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded.is_active is False
        assert reloaded.is_deleted is False, "is_active 전환이 is_deleted 를 건드리면 안 된다"
    finally:
        verify.close()


def test_apply_updates_reactivate_does_not_touch_is_active(sessionmaker_factory):
    """재활성화(is_deleted=False)는 is_active 를 자동 변경하지 않는다 (Req 6.2)."""
    seed = sessionmaker_factory()
    try:
        # 삭제 + 비활동 상태에서 시작.
        user = _make_user(
            seed, login_id="reactivate", is_active=False, is_deleted=True
        )
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        user = repo.get_by_id(session, user_id)
        repo.apply_updates(session, user, {"is_deleted": False})
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded.is_deleted is False, "삭제 flag 가 되돌려져야 한다"
        assert reloaded.is_active is False, "재활성화가 is_active 를 건드리면 안 된다"
    finally:
        verify.close()


def test_apply_updates_partial_only_changes_provided_keys(sessionmaker_factory):
    """apply_updates 는 제공된 키만 갱신하고 나머지 필드는 보존한다."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="partial")
        user.name = "원래이름"
        user.email = "orig@example.com"
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        user = repo.get_by_id(session, user_id)
        repo.apply_updates(session, user, {"name": "바뀐이름"})
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded.name == "바뀐이름"
        assert reloaded.email == "orig@example.com", "제공되지 않은 email 은 보존되어야 한다"
    finally:
        verify.close()


# --- set_password_hash ---------------------------------------------------


def test_set_password_hash_persists(sessionmaker_factory):
    """set_password_hash 후 fresh 재조회에서 교체된 해시가 영속됨을 증명한다 (Req 7.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="pwd", password_hash="hash-old")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = UserRepository()
        user = repo.get_by_id(session, user_id)
        repo.set_password_hash(session, user, "hash-new")
    finally:
        session.close()

    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded.password_hash == "hash-new", "새 해시가 영속되어야 한다"
    finally:
        verify.close()
