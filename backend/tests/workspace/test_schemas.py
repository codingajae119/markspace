"""WsMemberSchemas 단위 검증 (s05-workspace task 1.1).

requirements.md 1.2·2.1·3.1·3.4·5.1·6.1, design.md §Components and Interfaces
#WsMemberSchemas 검증:
- `WorkspaceRead` 는 s01 `TimestampedRead` 를 상속해 workspace ORM 객체로부터
  직렬화된다(1.2·6.1).
- `MemberCreate` 는 잘못된 role 문자열을 검증 오류로 거부한다(3.1·3.4).
- `WorkspaceCreate`/`WorkspaceUpdate` 는 필수/형식 위반을 검증 오류로 거부한다(2.1).
- `MemberRole` 문자열 값이 s01 `workspace_member.role` ENUM 값과 정확히 일치한다(3.4·6.1).
"""

from datetime import datetime
from enum import Enum

import pytest
from pydantic import ValidationError

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.base import ORMReadModel, TimestampedRead
from app.workspace.schemas import (
    AssignableUserRead,
    MemberCreate,
    MemberRead,
    MemberRole,
    MemberUpdate,
    OwnerChangeRequest,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)


def _make_orm_workspace() -> Workspace:
    """DB 미접근으로 구성한 Workspace ORM 인스턴스(from_attributes 직렬화 대상)."""
    return Workspace(
        id=7,
        name="Team Space",
        is_shareable=True,
        trash_retention_days=45,
        created_at=datetime(2026, 7, 16, 0, 0, 0),
        updated_at=None,
    )


# --- WorkspaceRead: ORM 직렬화 (1.2·6.1) ---


def test_workspace_read_inherits_timestamped_read() -> None:
    assert issubclass(WorkspaceRead, TimestampedRead)
    for field in ("id", "created_at", "updated_at"):
        assert field in WorkspaceRead.model_fields


def test_workspace_read_serializes_from_orm_object() -> None:
    ws = _make_orm_workspace()

    read = WorkspaceRead.model_validate(ws)
    dump = read.model_dump()

    assert dump["id"] == 7
    assert dump["name"] == "Team Space"
    assert dump["is_shareable"] is True
    assert dump["trash_retention_days"] == 45
    assert dump["created_at"] == datetime(2026, 7, 16, 0, 0, 0)
    assert dump["updated_at"] is None


# --- WorkspaceCreate: 필수/공백 name 검증 (2.1) ---


def test_workspace_create_accepts_valid_name() -> None:
    assert WorkspaceCreate(name="My Workspace").name == "My Workspace"


def test_workspace_create_rejects_missing_name() -> None:
    with pytest.raises(ValidationError):
        WorkspaceCreate()  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_workspace_create_rejects_blank_name(blank: str) -> None:
    with pytest.raises(ValidationError):
        WorkspaceCreate(name=blank)


# --- WorkspaceUpdate: 부분 갱신 + 형식 위반 (2.1) ---


def test_workspace_update_is_partial_all_fields_optional() -> None:
    empty = WorkspaceUpdate()
    assert empty.name is None
    assert empty.is_shareable is None
    assert empty.trash_retention_days is None


def test_workspace_update_rejects_bad_type_for_retention() -> None:
    # trash_retention_days 형식 위반(정수 아님) → ValidationError (2.1)
    with pytest.raises(ValidationError):
        WorkspaceUpdate(trash_retention_days="not-an-int")  # type: ignore[arg-type]


# --- MemberRole: s01 ENUM 값 일치 (3.4·6.1) ---


def test_member_role_is_str_enum() -> None:
    assert issubclass(MemberRole, str)
    assert issubclass(MemberRole, Enum)


def test_member_role_values_match_s01_model_enum() -> None:
    """MemberRole 문자열 값 == s01 workspace_member.role ENUM 값(하드코딩 금지)."""
    model_enum_values = set(WorkspaceMember.__table__.c.role.type.enums)
    schema_role_values = {r.value for r in MemberRole}

    assert schema_role_values == model_enum_values
    assert schema_role_values == {"owner", "editor", "viewer"}


# --- MemberCreate / MemberUpdate: 잘못된 role 거부 (3.1·3.4) ---


def test_member_create_accepts_valid_role() -> None:
    payload = MemberCreate(user_id=3, role="editor")
    assert payload.user_id == 3
    assert payload.role is MemberRole.EDITOR


def test_member_create_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        MemberCreate(user_id=3, role="superuser")  # type: ignore[arg-type]


def test_member_create_requires_user_id_and_role() -> None:
    with pytest.raises(ValidationError):
        MemberCreate(role="editor")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MemberCreate(user_id=3)  # type: ignore[call-arg]


def test_member_update_rejects_invalid_role() -> None:
    assert MemberUpdate(role="owner").role is MemberRole.OWNER
    with pytest.raises(ValidationError):
        MemberUpdate(role="ghost")  # type: ignore[arg-type]


# --- MemberRead: ORM 직렬화 규약 (6.1) ---


def test_member_read_inherits_ormreadmodel() -> None:
    assert issubclass(MemberRead, ORMReadModel)
    for field in ("id", "workspace_id", "user_id", "role"):
        assert field in MemberRead.model_fields


def test_member_read_serializes_from_orm_object() -> None:
    member = WorkspaceMember(id=11, workspace_id=7, user_id=3, role="viewer")

    read = MemberRead.model_validate(member)

    assert read.id == 11
    assert read.workspace_id == 7
    assert read.user_id == 3
    assert read.role is MemberRole.VIEWER


# --- OwnerChangeRequest (5.1) ---


def test_owner_change_request_requires_new_owner_user_id() -> None:
    assert OwnerChangeRequest(new_owner_user_id=9).new_owner_user_id == 9
    with pytest.raises(ValidationError):
        OwnerChangeRequest()  # type: ignore[call-arg]


# --- AssignableUserRead: narrow 직렬화(id/name/email 만, 계정 필드 비노출) (1.2·1.3) ---


def _make_orm_user(*, email: str | None = "user@example.com") -> User:
    """DB 미접근으로 구성한 User ORM 인스턴스(계정 필드 포함, 직렬화 대상)."""
    return User(
        id=42,
        login_id="alice",
        password_hash="hashed-secret",
        name="Alice",
        email=email,
        is_admin=True,
        is_active=False,
        is_deleted=True,
        created_at=datetime(2026, 7, 20, 0, 0, 0),
        updated_at=datetime(2026, 7, 21, 0, 0, 0),
    )


def test_assignable_user_read_inherits_ormreadmodel() -> None:
    assert issubclass(AssignableUserRead, ORMReadModel)
    assert set(AssignableUserRead.model_fields) == {"id", "name", "email"}


def test_assignable_user_read_serializes_only_id_name_email() -> None:
    user = _make_orm_user()

    read = AssignableUserRead.model_validate(user)
    dump = read.model_dump()

    assert set(dump) == {"id", "name", "email"}
    assert dump["id"] == 42
    assert dump["name"] == "Alice"
    assert dump["email"] == "user@example.com"


def test_assignable_user_read_excludes_account_fields() -> None:
    user = _make_orm_user()

    dump = AssignableUserRead.model_validate(user).model_dump()

    for leaked in (
        "login_id",
        "password_hash",
        "is_admin",
        "is_active",
        "is_deleted",
        "created_at",
        "updated_at",
    ):
        assert leaked not in dump


def test_assignable_user_read_allows_null_email() -> None:
    user = _make_orm_user(email=None)

    read = AssignableUserRead.model_validate(user)

    assert read.email is None
    assert read.model_dump()["email"] is None
