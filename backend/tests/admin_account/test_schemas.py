"""UserSchemas 단위 검증 (s03-admin-account task 1.1).

requirements.md 2.1·2.5·2.6·3.2·7.5·8.1, design.md §Components and Interfaces
#UserSchemas 검증:
- `UserCreate` 는 login_id·password·name 을 필수로 받고 email 은 선택이며, is_admin/상태
  flag 를 입력받지 않는다(2.1·2.6, 승격 금지 D3).
- `UserRead` 는 s01 `TimestampedRead` 를 상속해 User ORM 객체로부터 직렬화되며
  `password_hash` 등 민감 필드를 절대 노출하지 않는다(3.2·8.1).
- `UserUpdate` 는 부분 갱신 스키마이며 `is_admin` 필드를 포함하지 않는다(2.6, 승격 금지 D3).
- `AdminPasswordResetRequest` 는 `new_password` 를 필수로 받는다(7.5).
"""

import types

import pytest
from pydantic import ValidationError

from app.admin_account.schemas import (
    AdminPasswordResetRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.schemas.base import TimestampedRead


def _make_orm_user() -> types.SimpleNamespace:
    """DB 미접근으로 User ORM 을 흉내내는 속성 객체(from_attributes 덕 타이핑).

    `password_hash` 를 일부러 포함해 UserRead 직렬화가 이를 배제하는지 검증한다.
    """
    return types.SimpleNamespace(
        id=1,
        login_id="alice",
        password_hash="secret-hash",
        name="Alice",
        email="alice@example.com",
        is_admin=False,
        is_active=True,
        is_deleted=False,
        created_at="2026-07-16T00:00:00",
        updated_at=None,
    )


def test_user_create_accepts_required_and_optional_fields() -> None:
    payload = UserCreate(login_id="alice", password="pw12345678", name="Alice")

    assert payload.login_id == "alice"
    assert payload.password == "pw12345678"
    assert payload.name == "Alice"
    # email 은 선택이며 기본값 None (2.1)
    assert payload.email is None


@pytest.mark.parametrize("missing", ["login_id", "password", "name"])
def test_user_create_rejects_missing_required_field(missing: str) -> None:
    # 필수 항목 누락 → pydantic ValidationError (2.5)
    fields = {"login_id": "alice", "password": "pw12345678", "name": "Alice"}
    del fields[missing]
    with pytest.raises(ValidationError):
        UserCreate(**fields)


def test_user_create_has_no_privilege_or_status_fields() -> None:
    # 승격/상태 flag 입력 불가 (2.6, D3)
    assert "is_admin" not in UserCreate.model_fields
    assert "is_active" not in UserCreate.model_fields
    assert "is_deleted" not in UserCreate.model_fields


def test_user_read_inherits_timestamped_read() -> None:
    # id·created_at·updated_at 공통 필드는 s01 TimestampedRead 상속 (8.1)
    assert issubclass(UserRead, TimestampedRead)
    for field in ("id", "created_at", "updated_at"):
        assert field in UserRead.model_fields


def test_user_read_serializes_from_orm_without_password_hash() -> None:
    orm_user = _make_orm_user()

    read = UserRead.model_validate(orm_user)
    dump = read.model_dump()

    # 민감 필드 미노출 (3.2·8.1)
    assert "password_hash" not in dump
    assert not hasattr(read, "password_hash")
    # 상태·식별 필드는 그대로 노출 (3.2)
    assert dump["login_id"] == "alice"
    assert dump["name"] == "Alice"
    assert dump["email"] == "alice@example.com"
    assert dump["is_admin"] is False
    assert dump["is_active"] is True
    assert dump["is_deleted"] is False


def test_user_read_email_optional_defaults_none() -> None:
    orm_user = _make_orm_user()
    orm_user.email = None

    read = UserRead.model_validate(orm_user)

    assert read.email is None


def test_user_update_is_partial_all_fields_optional() -> None:
    # 모든 필드 생략 가능(부분 갱신)
    empty = UserUpdate()
    assert empty.name is None
    assert empty.email is None
    assert empty.is_active is None
    assert empty.is_deleted is None


def test_user_update_has_no_is_admin_field() -> None:
    # 승격 금지: is_admin 필드 부재 (2.6, D3)
    assert "is_admin" not in UserUpdate.model_fields


def test_admin_password_reset_requires_new_password() -> None:
    req = AdminPasswordResetRequest(new_password="newpw678")
    assert req.new_password == "newpw678"

    # 누락 시 ValidationError (7.5)
    with pytest.raises(ValidationError):
        AdminPasswordResetRequest()
