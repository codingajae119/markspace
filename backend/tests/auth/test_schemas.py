"""AuthSchemas 단위 검증 (s02-auth task 1.1).

requirements.md 1.2·1.7·4.3·5.5, design.md §auth/Contract #AuthSchemas 검증:
- `AuthUserRead` 는 s01 `ORMReadModel` 을 상속해 User ORM 객체로부터 직렬화되며
  `password_hash` 등 민감 필드를 절대 노출하지 않는다(1.7).
- `LoginRequest` 는 `login_id`/`password` 를 수용한다(1.2).
- `PasswordChangeRequest` 는 새 비밀번호 최소 길이 정책을 pydantic 검증으로 강제한다(4.3).
"""

import pytest
from pydantic import ValidationError

from app.auth.schemas import AuthUserRead, LoginRequest, PasswordChangeRequest
from app.models import User


def _make_user() -> User:
    """세션 없이 in-memory 로 User ORM 인스턴스를 구성한다(DB 미접근).

    DB autoincrement 가 적용되지 않으므로 `id` 는 명시 지정한다.
    """
    return User(
        id=1,
        login_id="alice",
        password_hash="secret-hash",
        name="Alice",
        email="alice@example.com",
        is_admin=False,
    )


def test_auth_user_read_serializes_from_orm_without_password_hash() -> None:
    user = _make_user()

    read = AuthUserRead.model_validate(user)
    dump = read.model_dump()

    # 민감 필드 미노출 (REQ-1.7)
    assert "password_hash" not in dump
    assert not hasattr(read, "password_hash")
    # 비민감 식별 정보는 그대로 노출 (REQ-1.2)
    assert dump == {
        "id": user.id,
        "login_id": "alice",
        "name": "Alice",
        "email": "alice@example.com",
        "is_admin": False,
    }


def test_auth_user_read_email_optional_defaults_none() -> None:
    user = User(
        id=2,
        login_id="bob",
        password_hash="secret-hash",
        name="Bob",
        email=None,
        is_admin=True,
    )

    read = AuthUserRead.model_validate(user)

    assert read.email is None
    assert read.is_admin is True


def test_login_request_accepts_login_id_and_password() -> None:
    req = LoginRequest(login_id="alice", password="pw12345678")

    assert req.login_id == "alice"
    assert req.password == "pw12345678"


def test_password_change_request_accepts_policy_compliant_new_password() -> None:
    req = PasswordChangeRequest(current_password="oldpw", new_password="newpw678")

    assert req.current_password == "oldpw"
    assert req.new_password == "newpw678"


def test_password_change_request_rejects_too_short_new_password() -> None:
    # 최소 길이 정책(8) 위반 → pydantic ValidationError (REQ-4.3)
    with pytest.raises(ValidationError):
        PasswordChangeRequest(current_password="oldpw", new_password="short")
