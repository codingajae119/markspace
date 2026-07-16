"""AuthService.logout / get_me 단위 테스트 (Task 2.2 / Req 2.1, 3.1).

design.md §auth/Service #AuthService Contracts (`logout(session)`, `get_me(ctx) -> AuthUserRead`)
를 검증한다.

핵심 불변식:
- logout: 세션에서 user_id 가 사라진다(session.clear).
- get_me: ctx.user_id 로 사용자를 로드하여 AuthUserRead 를 반환하며 password_hash 를
  노출하지 않는다(Req 2.1, 3.1). 방어적으로 사용자가 없으면 authenticate 와 동일한 401.

DB 불필요: 가짜 repo(단순 객체)와 dict 세션으로 충분하다.
"""

from datetime import datetime

import pytest

from app.auth.schemas import AuthUserRead
from app.auth.service import SESSION_USER_KEY, AuthService
from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.common.security import hash_password
from app.models import User


class _FakeRepo:
    """get_by_id 만 노출하는 최소 가짜 저장소."""

    def __init__(self, user: User | None) -> None:
        self._user = user
        self.calls: list[int] = []

    def get_by_id(self, user_id: int) -> User | None:
        self.calls.append(user_id)
        return self._user


def _make_user(
    *,
    user_id: int = 7,
    login_id: str = "alice",
    is_admin: bool = False,
) -> User:
    return User(
        id=user_id,
        login_id=login_id,
        password_hash=hash_password("correct-pw"),
        name="Alice",
        email="alice@example.com",
        is_admin=is_admin,
        is_active=True,
        is_deleted=False,
        created_at=datetime(2026, 1, 1),
    )


def _service_for(user: User | None) -> AuthService:
    return AuthService(_FakeRepo(user))


# --- logout --------------------------------------------------------------------


def test_logout_removes_user_id_from_session():
    service = _service_for(None)
    session: dict = {SESSION_USER_KEY: 7, "csrf": "abc"}

    result = service.logout(session)

    assert result is None
    assert SESSION_USER_KEY not in session


def test_logout_is_idempotent_on_empty_session():
    service = _service_for(None)
    session: dict = {}

    service.logout(session)

    assert SESSION_USER_KEY not in session


# --- get_me --------------------------------------------------------------------


def test_get_me_returns_read_model_for_ctx_user():
    user = _make_user(user_id=7, login_id="alice")
    repo = _FakeRepo(user)
    service = AuthService(repo)

    result = service.get_me(AuthContext(user_id=7, is_admin=False))

    assert repo.calls == [7]
    assert isinstance(result, AuthUserRead)
    assert result.id == 7
    assert result.login_id == "alice"
    assert result.name == "Alice"
    assert result.is_admin is False


def test_get_me_response_has_no_password_hash():
    service = _service_for(_make_user(user_id=7))

    result = service.get_me(AuthContext(user_id=7, is_admin=False))

    assert not hasattr(result, "password_hash")
    assert "password_hash" not in result.model_dump()


def test_get_me_missing_user_raises_uniform_401():
    service = _service_for(None)

    with pytest.raises(DomainError) as ei:
        service.get_me(AuthContext(user_id=999, is_admin=False))

    assert ei.value.code == ErrorCode.UNAUTHENTICATED
    assert ei.value.http_status == 401
