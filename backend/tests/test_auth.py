"""세션 인증 의존성 단위 테스트 (Task 3.4 / Req 4.1~4.5).

``get_current_user`` 를 FastAPI DI 를 거치지 않고 평범한 함수로 직접 호출하여
세션 인증 판정(design.md §Common/Auth #SessionAuth, System Flows "세션 인증 판정")
을 결정적으로 검증한다.

격리: 개발 DB(``notion_lite``)를 건드리지 않도록 전용 테스트 DB
(``notion_lite_test``)를 대상으로 한다. ``DB_NAME`` 환경변수로 대상 DB 를 바꾸고
:func:`app.config.get_settings` 캐시를 비운 뒤, **그 시점의** 설정 URL 로 새 엔진을
직접 만든다(``app.common.db`` 의 모듈 수준 ``engine`` 은 import 시점의 개발 DB URL 에
바인딩되어 있으므로 재사용하지 않는다). 종료 시 테이블을 모두 제거하고 환경변수·캐시를
원복하여 이후 테스트가 다시 개발 DB 를 바라보게 한다(캐시·DB 누수 방지).

``request`` 는 ``.session`` 만 참조되므로 ``SimpleNamespace(session=...)`` 로 대체한다.
"""

import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.auth import AuthContext, get_current_user
from app.common.db import Base
from app.common.errors import DomainError, ErrorCode
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


@pytest.fixture
def test_session():
    """테스트 DB 에 전체 스키마를 생성하고 세션을 제공한 뒤 정리한다."""
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    # 모듈 수준 engine 은 import 시점의 개발 DB URL 에 묶여 있으므로 재사용하지 않고
    # 테스트 DB URL 로 새 엔진을 만든다.
    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    _drop_everything(engine)  # 시작 전 빈 상태 보증(격리 전제).
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionFactory()

    try:
        yield session
    finally:
        session.close()
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


def _make_user(session, *, is_admin=False, is_active=True, is_deleted=False):
    """테스트 세션에 User 를 한 명 삽입하고 flush 하여 id 를 확정한다."""
    suffix = f"{is_admin}-{is_active}-{is_deleted}-{datetime.utcnow().timestamp()}"
    user = User(
        login_id=f"user-{suffix}",
        password_hash="x",  # auth 는 비밀번호를 검증하지 않는다(s02 소유).
        name="테스트 사용자",
        is_admin=is_admin,
        is_active=is_active,
        is_deleted=is_deleted,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def _request_with_session(session_dict):
    return SimpleNamespace(session=session_dict)


def test_valid_active_non_admin_returns_auth_context(test_session):
    """유효·활성·비admin 사용자 → AuthContext(is_admin=False) (Req 4.1)."""
    user = _make_user(test_session, is_admin=False)
    request = _request_with_session({"user_id": user.id})

    ctx = get_current_user(request, db=test_session)

    assert isinstance(ctx, AuthContext)
    assert ctx.user_id == user.id
    assert ctx.is_admin is False


def test_valid_admin_exposes_is_admin_true(test_session):
    """유효·활성·admin 사용자 → AuthContext.is_admin=True (Req 4.4)."""
    user = _make_user(test_session, is_admin=True)
    request = _request_with_session({"user_id": user.id})

    ctx = get_current_user(request, db=test_session)

    assert ctx.user_id == user.id
    assert ctx.is_admin is True


def test_empty_session_raises_unauthenticated(test_session):
    """세션에 user_id 가 없으면 401 (Req 4.2)."""
    request = _request_with_session({})

    with pytest.raises(DomainError) as exc:
        get_current_user(request, db=test_session)

    assert exc.value.code == ErrorCode.UNAUTHENTICATED
    assert exc.value.http_status == 401


def test_session_pointing_to_nonexistent_user_raises_unauthenticated(test_session):
    """세션 user_id 가 존재하지 않는 사용자를 가리키면 401 (Req 4.2)."""
    request = _request_with_session({"user_id": 999_999_999})

    with pytest.raises(DomainError) as exc:
        get_current_user(request, db=test_session)

    assert exc.value.code == ErrorCode.UNAUTHENTICATED
    assert exc.value.http_status == 401


def test_inactive_user_raises_unauthenticated(test_session):
    """is_active=False 사용자는 인증 거부 401 (Req 4.3)."""
    user = _make_user(test_session, is_active=False)
    request = _request_with_session({"user_id": user.id})

    with pytest.raises(DomainError) as exc:
        get_current_user(request, db=test_session)

    assert exc.value.code == ErrorCode.UNAUTHENTICATED
    assert exc.value.http_status == 401


def test_deleted_user_raises_unauthenticated(test_session):
    """is_deleted=True 사용자는 인증 거부 401 (Req 4.3)."""
    user = _make_user(test_session, is_deleted=True)
    request = _request_with_session({"user_id": user.id})

    with pytest.raises(DomainError) as exc:
        get_current_user(request, db=test_session)

    assert exc.value.code == ErrorCode.UNAUTHENTICATED
    assert exc.value.http_status == 401


def test_missing_session_attribute_raises_unauthenticated(test_session):
    """SessionMiddleware 미등록 등으로 세션 접근이 불가하면 401 (Req 4.2)."""

    class _NoSessionRequest:
        @property
        def session(self):
            raise AssertionError("SessionMiddleware must be installed")

    with pytest.raises(DomainError) as exc:
        get_current_user(_NoSessionRequest(), db=test_session)

    assert exc.value.code == ErrorCode.UNAUTHENTICATED
    assert exc.value.http_status == 401
