"""AuthUserRepository 통합 테스트 (Task 1.2 / Req 1.1, 4.1, 5.1).

design.md §auth/Data #AuthUserRepository 계약을 검증한다:
- `find_by_login_id` 는 상태(is_active/is_deleted) 로 필터링하지 않고 반환한다
  (상태 게이트는 AuthService 가 수행 — 동일 401 통제). 비활동·삭제 사용자도 조회된다.
- `get_by_id` 는 PK 로 사용자를 로드하며, 없는 id 는 None 을 반환한다.
- `update_password_hash` 는 password_hash 를 교체하고 commit 하여 영속화한다
  (fresh 조회로 교체 증명).

격리: test_integration_wiring.py 의 확립된 테스트 DB 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`markspace_test`)로 바꾸고 :func:`app.config.get_settings`
캐시를 비운 뒤 그 시점 URL 로 새 엔진·세션 팩토리를 만든다. 종료 시 테이블을 모두
제거하고 엔진을 dispose 한 뒤 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.auth.repository import AuthUserRepository
from app.common.db import Base
from app.models import User

TEST_DB_NAME = "markspace_test"


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


def test_find_by_login_id_returns_active_user(sessionmaker_factory):
    """활성·미삭제 사용자를 login_id 로 조회한다 (Req 1.1)."""
    seed = sessionmaker_factory()
    try:
        _make_user(seed, login_id="alice")
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = AuthUserRepository(session)
        found = repo.find_by_login_id("alice")
        assert found is not None
        assert found.login_id == "alice"
    finally:
        session.close()


def test_find_by_login_id_returns_inactive_user(sessionmaker_factory):
    """비활동(is_active=False) 사용자도 상태 필터 없이 반환한다 (Req 1.4 게이트는 서비스 소유)."""
    seed = sessionmaker_factory()
    try:
        _make_user(seed, login_id="inactive-bob", is_active=False)
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = AuthUserRepository(session)
        found = repo.find_by_login_id("inactive-bob")
        assert found is not None, "비활동 사용자도 조회되어야 한다(상태 필터 금지)"
        assert found.is_active is False
    finally:
        session.close()


def test_find_by_login_id_returns_deleted_user(sessionmaker_factory):
    """삭제(is_deleted=True) 사용자도 상태 필터 없이 반환한다 (Req 1.5 게이트는 서비스 소유)."""
    seed = sessionmaker_factory()
    try:
        _make_user(seed, login_id="deleted-carol", is_deleted=True)
        seed.commit()
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = AuthUserRepository(session)
        found = repo.find_by_login_id("deleted-carol")
        assert found is not None, "삭제 사용자도 조회되어야 한다(상태 필터 금지)"
        assert found.is_deleted is True
    finally:
        session.close()


def test_find_by_login_id_returns_none_when_missing(sessionmaker_factory):
    """존재하지 않는 login_id 는 None 을 반환한다 (Req 1.1)."""
    session = sessionmaker_factory()
    try:
        repo = AuthUserRepository(session)
        assert repo.find_by_login_id("nobody") is None
    finally:
        session.close()


def test_get_by_id_returns_user(sessionmaker_factory):
    """PK 로 올바른 사용자를 로드한다 (Req 4.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(seed, login_id="dave")
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = AuthUserRepository(session)
        found = repo.get_by_id(user_id)
        assert found is not None
        assert found.id == user_id
        assert found.login_id == "dave"
    finally:
        session.close()


def test_get_by_id_returns_none_when_missing(sessionmaker_factory):
    """존재하지 않는 id 는 None 을 반환한다 (Req 4.1)."""
    session = sessionmaker_factory()
    try:
        repo = AuthUserRepository(session)
        assert repo.get_by_id(999999) is None
    finally:
        session.close()


def test_update_password_hash_persists(sessionmaker_factory):
    """update_password_hash 후 fresh 조회에서 교체된 해시가 영속됨을 증명한다 (Req 4.1)."""
    seed = sessionmaker_factory()
    try:
        user = _make_user(
            seed, login_id="erin", password_hash="hash-old"
        )
        seed.commit()
        user_id = user.id
    finally:
        seed.close()

    session = sessionmaker_factory()
    try:
        repo = AuthUserRepository(session)
        user = repo.get_by_id(user_id)
        repo.update_password_hash(user, "hash-new")
    finally:
        session.close()

    # 별도 세션(별도 커넥션)의 fresh 조회로 commit 영속화를 증명한다.
    verify = sessionmaker_factory()
    try:
        reloaded = verify.get(User, user_id)
        assert reloaded.password_hash == "hash-new", "새 해시가 영속되어야 한다"
    finally:
        verify.close()
