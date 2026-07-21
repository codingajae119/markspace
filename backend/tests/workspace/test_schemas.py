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
from pydantic import BaseModel, ValidationError

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.base import ORMReadModel, TimestampedRead
from app.workspace.schemas import (
    AssignableUserRead,
    MemberCreate,
    MemberRead,
    MemberRosterRead,
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


# --- WorkspaceRead: role 가산 필드 (s24 Req 1.1·1.5) ---


def test_workspace_read_role_defaults_to_none_on_orm_without_role() -> None:
    """role 속성이 없는 ORM Workspace 를 model_validate 해도 role=None 으로 통과(1.5)."""
    ws = _make_orm_workspace()
    assert not hasattr(ws, "role")

    read = WorkspaceRead.model_validate(ws)

    assert read.role is None
    assert read.model_dump()["role"] is None


def test_workspace_read_serializes_explicit_role() -> None:
    """명시 주입한 role 은 그대로 직렬화된다(1.1)."""
    read = WorkspaceRead(
        id=7,
        name="Team Space",
        is_shareable=True,
        trash_retention_days=45,
        created_at=datetime(2026, 7, 16, 0, 0, 0),
        updated_at=None,
        role=MemberRole.OWNER,
    )

    assert read.role is MemberRole.OWNER
    assert read.model_dump()["role"] is MemberRole.OWNER


def test_workspace_read_role_is_optional_member_role() -> None:
    """role 은 가산 optional 필드로 존재하며 기존 필드는 무변경 유지(1.5)."""
    assert "role" in WorkspaceRead.model_fields
    for field in ("name", "is_shareable", "trash_retention_days"):
        assert field in WorkspaceRead.model_fields


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


# --- MemberRole: owner/member 2값 직렬화 (s26 Req 1.3·5.5) ---


def test_member_role_is_str_enum() -> None:
    assert issubclass(MemberRole, str)
    assert issubclass(MemberRole, Enum)


def test_member_role_is_exactly_owner_member_two_values() -> None:
    """MemberRole 직렬화 enum 은 owner/member 2값으로만 정의된다(s26 Req 1.3, D6).

    editor·viewer 값은 제거된다. s01 `workspace_member.role` 모델 ENUM 과의 정합은
    migration 0004(task 2.1)에서 owner/member 로 축소되며 함께 맞춰지므로, 이 스키마
    task 는 직렬화 enum 의 값 집합만 owner/member 로 확정한다.
    """
    assert {r.value for r in MemberRole} == {"owner", "member"}
    assert MemberRole.OWNER.value == "owner"
    assert MemberRole.MEMBER.value == "member"
    assert not hasattr(MemberRole, "EDITOR")
    assert not hasattr(MemberRole, "VIEWER")


# --- MemberCreate / MemberUpdate: 잘못된 role 거부 (Req 1.4·5.5) ---


def test_member_create_accepts_valid_role() -> None:
    payload = MemberCreate(user_id=3, role="member")
    assert payload.user_id == 3
    assert payload.role is MemberRole.MEMBER


def test_member_create_accepts_owner_role() -> None:
    assert MemberCreate(user_id=3, role="owner").role is MemberRole.OWNER


def test_member_create_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        MemberCreate(user_id=3, role="superuser")  # type: ignore[arg-type]


@pytest.mark.parametrize("legacy", ["editor", "viewer"])
def test_member_create_rejects_legacy_editor_viewer_role(legacy: str) -> None:
    """editor/viewer 는 값 집합 축소로 pydantic 이 자동 422 거부한다(Req 1.4, D6)."""
    with pytest.raises(ValidationError):
        MemberCreate(user_id=3, role=legacy)  # type: ignore[arg-type]


def test_member_create_requires_user_id_and_role() -> None:
    with pytest.raises(ValidationError):
        MemberCreate(role="member")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MemberCreate(user_id=3)  # type: ignore[call-arg]


def test_member_update_rejects_invalid_role() -> None:
    assert MemberUpdate(role="owner").role is MemberRole.OWNER
    assert MemberUpdate(role="member").role is MemberRole.MEMBER
    with pytest.raises(ValidationError):
        MemberUpdate(role="ghost")  # type: ignore[arg-type]


@pytest.mark.parametrize("legacy", ["editor", "viewer"])
def test_member_update_rejects_legacy_editor_viewer_role(legacy: str) -> None:
    """role 변경 요청의 editor/viewer 문자열도 자동 422 거부(Req 1.4)."""
    with pytest.raises(ValidationError):
        MemberUpdate(role=legacy)  # type: ignore[arg-type]


# --- MemberRead: ORM 직렬화 규약 (6.1) ---


def test_member_read_inherits_ormreadmodel() -> None:
    assert issubclass(MemberRead, ORMReadModel)
    for field in ("id", "workspace_id", "user_id", "role"):
        assert field in MemberRead.model_fields


def test_member_read_serializes_from_orm_object() -> None:
    member = WorkspaceMember(id=11, workspace_id=7, user_id=3, role="member")

    read = MemberRead.model_validate(member)

    assert read.id == 11
    assert read.workspace_id == 7
    assert read.user_id == 3
    assert read.role is MemberRole.MEMBER


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


# --- MemberRosterRead: narrow 직렬화(user_id/name/email/role 만, 계정 필드 비노출) (1.2·2.6) ---


def test_member_roster_read_is_plain_base_model_not_orm() -> None:
    """join 프로젝션이므로 BaseModel 상속(ORMReadModel from_attributes 미사용)."""
    assert issubclass(MemberRosterRead, BaseModel)
    assert not issubclass(MemberRosterRead, ORMReadModel)
    assert set(MemberRosterRead.model_fields) == {"user_id", "name", "email", "role"}


def test_member_roster_read_serializes_exactly_four_fields() -> None:
    read = MemberRosterRead(user_id=3, name="Alice", email="alice@example.com", role="owner")
    dump = read.model_dump()

    assert set(dump) == {"user_id", "name", "email", "role"}
    assert dump["user_id"] == 3
    assert dump["name"] == "Alice"
    assert dump["email"] == "alice@example.com"
    assert read.role is MemberRole.OWNER


def test_member_roster_read_excludes_injected_user_account_fields() -> None:
    """임의 User 유사 dict 의 민감 필드를 주입해도 응답에 누출되지 않는다(2.6)."""
    user_like = {
        "user_id": 42,
        "name": "Alice",
        "email": "alice@example.com",
        "role": "member",
        # 아래는 로스터에 노출되면 안 되는 계정/상태/타임스탬프 필드
        "login_id": "alice",
        "password_hash": "hashed-secret",
        "is_admin": True,
        "is_active": False,
        "is_deleted": True,
        "created_at": datetime(2026, 7, 20, 0, 0, 0),
        "updated_at": datetime(2026, 7, 21, 0, 0, 0),
    }

    read = MemberRosterRead(**user_like)
    dump = read.model_dump()

    assert set(dump) == {"user_id", "name", "email", "role"}
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
        assert leaked not in MemberRosterRead.model_fields


def test_member_roster_read_preserves_null_email() -> None:
    """이메일 없는(또는 비활성) 멤버도 email=null 로 보존된다(1.2·1.5)."""
    read = MemberRosterRead(user_id=3, name="Bob", email=None, role="member")

    assert read.email is None
    assert read.model_dump()["email"] is None


def test_member_roster_read_email_defaults_to_none_when_absent() -> None:
    read = MemberRosterRead(user_id=3, name="Bob", role="member")

    assert read.email is None
    assert read.model_dump()["email"] is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("owner", MemberRole.OWNER),
        ("member", MemberRole.MEMBER),
    ],
)
def test_member_roster_read_normalizes_role_values(raw: str, expected: MemberRole) -> None:
    read = MemberRosterRead(user_id=1, name="X", role=raw)

    assert read.role is expected


@pytest.mark.parametrize("legacy", ["editor", "viewer"])
def test_member_roster_read_rejects_legacy_editor_viewer_role(legacy: str) -> None:
    with pytest.raises(ValidationError):
        MemberRosterRead(user_id=1, name="X", role=legacy)  # type: ignore[arg-type]


def test_member_roster_read_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        MemberRosterRead(user_id=1, name="X", role="superuser")  # type: ignore[arg-type]
