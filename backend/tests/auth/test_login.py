"""AuthService.authenticate 단위 테스트 (Task 2.1 / Req 1.1, 1.3, 1.4, 1.5, 1.6, 5.4).

design.md §auth/Service #AuthService Contracts 와 System Flows 로그인 흐름을 검증한다.

핵심 불변식:
- 성공: active·non-deleted 사용자 + 올바른 비밀번호 → 세션에 user_id 기록, AuthUserRead 반환.
- 계정 열거 방지(Req 1.3): 미존재·비밀번호 불일치·비활동·삭제 4개 실패가 모두
  **동일한** DomainError(code=unauthenticated, message 고정, http_status=401)를 던진다.
- 실패 시 세션은 write 되지 않는다(Req 1.4, 1.5).

DB 불필요: 가짜 repo(단순 객체)와 dict 세션으로 충분하다. 실 해시는 s01
`hash_password` 로 생성하여 `verify_password` 가 실제로 통과/실패하도록 한다.
"""

from datetime import datetime

import pytest

from app.auth.schemas import AuthUserRead
from app.auth.service import SESSION_USER_KEY, AuthService
from app.common.errors import DomainError, ErrorCode
from app.common.security import hash_password
from app.models import User

CORRECT_PW = "correct-pw"
WRONG_PW = "wrong-pw"


class _FakeRepo:
    """find_by_login_id 만 노출하는 최소 가짜 저장소."""

    def __init__(self, user: User | None) -> None:
        self._user = user
        self.calls: list[str] = []

    def find_by_login_id(self, login_id: str) -> User | None:
        self.calls.append(login_id)
        return self._user


def _make_user(
    *,
    user_id: int = 7,
    login_id: str = "alice",
    is_active: bool = True,
    is_deleted: bool = False,
) -> User:
    return User(
        id=user_id,
        login_id=login_id,
        password_hash=hash_password(CORRECT_PW),
        name="Alice",
        email="alice@example.com",
        is_admin=False,
        is_active=is_active,
        is_deleted=is_deleted,
        created_at=datetime(2026, 1, 1),
    )


def _service_for(user: User | None) -> AuthService:
    return AuthService(_FakeRepo(user))


# --- 성공 경로 -----------------------------------------------------------------


def test_authenticate_success_writes_session_and_returns_read_model():
    user = _make_user(user_id=42, login_id="alice")
    service = _service_for(user)
    session: dict = {}

    result = service.authenticate("alice", CORRECT_PW, session)

    assert session[SESSION_USER_KEY] == 42
    assert isinstance(result, AuthUserRead)
    assert result.id == 42
    assert result.login_id == "alice"
    assert result.name == "Alice"
    assert result.is_admin is False


def test_session_key_is_user_id_literal():
    # s01 common/auth.py get_current_user 가 읽는 키와 반드시 일치해야 한다.
    assert SESSION_USER_KEY == "user_id"


def test_authenticate_success_response_has_no_password_hash():
    user = _make_user()
    service = _service_for(user)

    result = service.authenticate("alice", CORRECT_PW, {})

    assert not hasattr(result, "password_hash")
    assert "password_hash" not in result.model_dump()


# --- 실패 경로: 각 원인별로 동일한 401 --------------------------------------------


def _assert_uniform_401(exc: DomainError) -> None:
    assert exc.code == ErrorCode.UNAUTHENTICATED
    assert exc.http_status == 401


def test_missing_user_raises_401():
    service = _service_for(None)
    session: dict = {}

    with pytest.raises(DomainError) as ei:
        service.authenticate("ghost", CORRECT_PW, session)

    _assert_uniform_401(ei.value)
    assert SESSION_USER_KEY not in session


def test_wrong_password_raises_same_401():
    service = _service_for(_make_user())
    session: dict = {}

    with pytest.raises(DomainError) as ei:
        service.authenticate("alice", WRONG_PW, session)

    _assert_uniform_401(ei.value)
    assert SESSION_USER_KEY not in session


def test_inactive_user_raises_same_401_and_no_session():
    service = _service_for(_make_user(is_active=False))
    session: dict = {}

    with pytest.raises(DomainError) as ei:
        service.authenticate("alice", CORRECT_PW, session)

    _assert_uniform_401(ei.value)
    assert SESSION_USER_KEY not in session


def test_deleted_user_raises_same_401_and_no_session():
    service = _service_for(_make_user(is_deleted=True))
    session: dict = {}

    with pytest.raises(DomainError) as ei:
        service.authenticate("alice", CORRECT_PW, session)

    _assert_uniform_401(ei.value)
    assert SESSION_USER_KEY not in session


def test_all_failure_causes_are_byte_identical():
    """미존재·비밀번호 불일치·비활동·삭제 4개 실패의 (code, message, http_status) 동일."""
    errors: list[DomainError] = []

    # 미존재
    with pytest.raises(DomainError) as ei:
        _service_for(None).authenticate("ghost", CORRECT_PW, {})
    errors.append(ei.value)

    # 비밀번호 불일치
    with pytest.raises(DomainError) as ei:
        _service_for(_make_user()).authenticate("alice", WRONG_PW, {})
    errors.append(ei.value)

    # 비활동
    with pytest.raises(DomainError) as ei:
        _service_for(_make_user(is_active=False)).authenticate("alice", CORRECT_PW, {})
    errors.append(ei.value)

    # 삭제
    with pytest.raises(DomainError) as ei:
        _service_for(_make_user(is_deleted=True)).authenticate("alice", CORRECT_PW, {})
    errors.append(ei.value)

    signatures = {(e.code, e.message, e.http_status) for e in errors}
    assert len(signatures) == 1, f"실패 원인별 401 이 드리프트함: {signatures}"
    (code, _message, status), = signatures
    assert code == ErrorCode.UNAUTHENTICATED
    assert status == 401
