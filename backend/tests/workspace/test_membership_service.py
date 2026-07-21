"""MembershipService 단위 테스트 (Task 2.4 / Req 3.1~3.9, 5.1·5.2·5.3·5.5·5.6).

design.md §Components → MembershipService 계약과 §System Flows(권한 게이팅(멤버 추가)·
admin 소유권 변경 upsert-to-owner flowchart)을 검증한다. 세션(`db`)은 메서드별 인자로
전달받는 계약이므로 가짜 repo 는 각 메서드의 첫 인자로 `db` 를 받고 dummy 센티널을 통과시킨다.

핵심 불변식:
- add_member: 지정 role 로 신규 등록. 대상 user 미존재→404, 기존 멤버→409(생성 없음).
- change_role: role 갱신. 멤버십 미존재→404. 마지막/유일 owner 강등도 허용(하한 없음, 3.9).
- remove_member: 물리 삭제. 멤버십 미존재→404. 마지막 owner 제거도 허용(3.9).
- change_owner(admin): 워크스페이스 미존재→404, 대상 user 미존재→404, 멤버면 role=owner
  갱신·비멤버면 owner 신규 등록(upsert-to-owner), owner 부재 워크스페이스에도 새 owner 지정,
  기존 다른 owner 는 강등하지 않음(복수 owner 허용, 5.6·3.7).

DB 불필요: 가짜 in-memory repo 로 서비스의 도메인 판정만 검증한다.
"""

from datetime import datetime

import pytest

from app.common.errors import DomainError, ErrorCode
from app.models import User, Workspace, WorkspaceMember
from app.schemas.base import Page
from app.workspace.schemas import (
    AssignableUserRead,
    MemberCreate,
    MemberRead,
    MemberRosterRead,
    MemberRole,
    MemberUpdate,
    OwnerChangeRequest,
    WorkspaceRead,
)
from app.workspace.service import MembershipService

DB = object()  # db 센티널: 가짜 repo 로 그대로 통과되며 내용은 검증에 쓰이지 않는다.


def _make_workspace(
    *,
    workspace_id: int = 1,
    name: str = "WS",
    is_shareable: bool = False,
    trash_retention_days: int = 30,
) -> Workspace:
    return Workspace(
        id=workspace_id,
        name=name,
        is_shareable=is_shareable,
        trash_retention_days=trash_retention_days,
        created_at=datetime(2026, 1, 1),
        updated_at=None,
    )


def _make_member(
    *,
    member_id: int = 10,
    workspace_id: int = 1,
    user_id: int = 2,
    role: str = "member",
) -> WorkspaceMember:
    return WorkspaceMember(
        id=member_id, workspace_id=workspace_id, user_id=user_id, role=role
    )


def _make_user(*, user_id: int, name: str = "User", email: str | None = None) -> User:
    # narrow 스키마 검증에 필요한 필드 외 계정 필드도 채워 model_validate 가 선언 필드만
    # 골라내는지(누출 없음) 서비스 매핑 경로에서 함께 관찰한다.
    return User(
        id=user_id,
        login_id=f"login{user_id}",
        password_hash="hash",
        name=name,
        email=email,
        is_admin=False,
        is_active=True,
        is_deleted=False,
    )


class _FakeMemberRepo:
    """MembershipService 가 호출하는 MembershipRepository 계약의 최소 가짜 구현.

    모든 메서드는 첫 인자로 `db` 를 받는다(s05 계약). `set_role` 은 in-place 로 반영해
    후속 검증이 최종 상태를 관찰하도록 한다(실제 repo 의 영속 관찰과 정합).
    """

    def __init__(
        self,
        *,
        member: WorkspaceMember | None = None,
        user_exists: bool = True,
        assignable: tuple[list[User], int] | None = None,
        members: tuple[list[tuple[User, str]], int] | None = None,
    ) -> None:
        self._member = member
        self._user_exists = user_exists
        self._assignable = assignable if assignable is not None else ([], 0)
        self._members = members if members is not None else ([], 0)
        self.user_exists_calls: list[int] = []
        self.get_calls: list[tuple[int, int]] = []
        self.add_calls: list[dict] = []
        self.set_role_calls: list[tuple[WorkspaceMember, str]] = []
        self.remove_calls: list[WorkspaceMember] = []
        self.list_assignable_calls: list[tuple[int, int, int]] = []
        self.list_members_calls: list[tuple[int, int, int]] = []
        self._next_id = 100

    def list_assignable_users(
        self, db, workspace_id: int, limit: int, offset: int
    ) -> tuple[list[User], int]:
        assert db is DB
        self.list_assignable_calls.append((workspace_id, limit, offset))
        return self._assignable

    def list_members(
        self, db, workspace_id: int, limit: int, offset: int
    ) -> tuple[list[tuple[User, str]], int]:
        assert db is DB
        self.list_members_calls.append((workspace_id, limit, offset))
        return self._members

    def user_exists(self, db, user_id: int) -> bool:
        assert db is DB
        self.user_exists_calls.append(user_id)
        return self._user_exists

    def get(self, db, workspace_id: int, user_id: int) -> WorkspaceMember | None:
        assert db is DB
        self.get_calls.append((workspace_id, user_id))
        return self._member

    def add(self, db, *, workspace_id: int, user_id: int, role: str) -> WorkspaceMember:
        assert db is DB
        self.add_calls.append(
            {"workspace_id": workspace_id, "user_id": user_id, "role": role}
        )
        member = WorkspaceMember(
            id=self._next_id, workspace_id=workspace_id, user_id=user_id, role=role
        )
        self._next_id += 1
        return member

    def set_role(self, db, member: WorkspaceMember, role: str) -> WorkspaceMember:
        assert db is DB
        self.set_role_calls.append((member, role))
        member.role = role
        return member

    def remove(self, db, member: WorkspaceMember) -> None:
        assert db is DB
        self.remove_calls.append(member)


class _FakeWsRepo:
    """MembershipService.change_owner 가 호출하는 WorkspaceRepository 계약의 최소 가짜 구현."""

    def __init__(self, *, workspace: Workspace | None = None) -> None:
        self._workspace = workspace
        self.get_by_id_calls: list[int] = []

    def get_by_id(self, db, workspace_id: int) -> Workspace | None:
        assert db is DB
        self.get_by_id_calls.append(workspace_id)
        return self._workspace


# --- add_member ---------------------------------------------------------------


def test_add_member_registers_new_member_with_specified_role():
    member_repo = _FakeMemberRepo(member=None, user_exists=True)
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.add_member(
        DB, 1, MemberCreate(user_id=2, role=MemberRole.MEMBER)
    )

    # 대상 사용자 존재를 확인하고 중복 여부를 조회했다.
    assert member_repo.user_exists_calls == [2]
    assert member_repo.get_calls == [(1, 2)]
    # 정확히 한 번, 지정 role 의 원시 문자열로 등록했다.
    assert len(member_repo.add_calls) == 1
    assert member_repo.add_calls[0] == {
        "workspace_id": 1,
        "user_id": 2,
        "role": "member",
    }
    # 응답은 MemberRead 이며 등록한 값을 반영한다.
    assert isinstance(result, MemberRead)
    assert result.workspace_id == 1
    assert result.user_id == 2
    assert result.role == MemberRole.MEMBER


def test_add_member_owner_role_passes_raw_string_value():
    member_repo = _FakeMemberRepo(member=None, user_exists=True)
    service = MembershipService(member_repo, _FakeWsRepo())

    service.add_member(DB, 3, MemberCreate(user_id=7, role=MemberRole.OWNER))

    assert member_repo.add_calls[0]["role"] == "owner"


def test_add_member_duplicate_member_raises_409_and_does_not_add():
    existing = _make_member(workspace_id=1, user_id=2, role="member")
    member_repo = _FakeMemberRepo(member=existing, user_exists=True)
    service = MembershipService(member_repo, _FakeWsRepo())

    with pytest.raises(DomainError) as ei:
        service.add_member(DB, 1, MemberCreate(user_id=2, role=MemberRole.MEMBER))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert member_repo.add_calls == []


def test_add_member_nonexistent_user_raises_404_and_does_not_add():
    member_repo = _FakeMemberRepo(member=None, user_exists=False)
    service = MembershipService(member_repo, _FakeWsRepo())

    with pytest.raises(DomainError) as ei:
        service.add_member(DB, 1, MemberCreate(user_id=999, role=MemberRole.MEMBER))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert member_repo.add_calls == []


# --- change_role --------------------------------------------------------------


def test_change_role_updates_role_of_existing_member():
    member = _make_member(workspace_id=1, user_id=2, role="member")
    member_repo = _FakeMemberRepo(member=member)
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.change_role(DB, 1, 2, MemberUpdate(role=MemberRole.MEMBER))

    assert member_repo.get_calls == [(1, 2)]
    assert len(member_repo.set_role_calls) == 1
    updated_member, role_str = member_repo.set_role_calls[0]
    assert updated_member is member
    assert role_str == "member"
    assert isinstance(result, MemberRead)
    assert result.role == MemberRole.MEMBER


def test_change_role_missing_membership_raises_404():
    member_repo = _FakeMemberRepo(member=None)
    service = MembershipService(member_repo, _FakeWsRepo())

    with pytest.raises(DomainError) as ei:
        service.change_role(DB, 1, 2, MemberUpdate(role=MemberRole.MEMBER))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert member_repo.set_role_calls == []


def test_change_role_demoting_last_owner_is_allowed():
    # 유일 owner 를 member 로 강등해도 하한 가드 없이 허용된다(3.9).
    only_owner = _make_member(workspace_id=1, user_id=2, role="owner")
    member_repo = _FakeMemberRepo(member=only_owner)
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.change_role(DB, 1, 2, MemberUpdate(role=MemberRole.MEMBER))

    assert member_repo.set_role_calls[0][1] == "member"
    assert result.role == MemberRole.MEMBER


# --- remove_member ------------------------------------------------------------


def test_remove_member_removes_existing_membership_and_returns_none():
    member = _make_member(workspace_id=1, user_id=2, role="member")
    member_repo = _FakeMemberRepo(member=member)
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.remove_member(DB, 1, 2)

    assert result is None
    assert member_repo.get_calls == [(1, 2)]
    assert member_repo.remove_calls == [member]


def test_remove_member_missing_membership_raises_404():
    member_repo = _FakeMemberRepo(member=None)
    service = MembershipService(member_repo, _FakeWsRepo())

    with pytest.raises(DomainError) as ei:
        service.remove_member(DB, 1, 2)

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert member_repo.remove_calls == []


def test_remove_member_removing_last_owner_is_allowed():
    # 유일 owner 제거도 하한 가드 없이 허용된다(3.9).
    only_owner = _make_member(workspace_id=1, user_id=2, role="owner")
    member_repo = _FakeMemberRepo(member=only_owner)
    service = MembershipService(member_repo, _FakeWsRepo())

    service.remove_member(DB, 1, 2)

    assert member_repo.remove_calls == [only_owner]


# --- change_owner -------------------------------------------------------------


def test_change_owner_non_member_target_adds_new_owner_membership():
    # 비멤버 대상은 owner role 로 신규 등록된다(upsert-to-owner, 5.2).
    workspace = _make_workspace(workspace_id=1)
    member_repo = _FakeMemberRepo(member=None, user_exists=True)
    ws_repo = _FakeWsRepo(workspace=workspace)
    service = MembershipService(member_repo, ws_repo)

    result = service.change_owner(DB, 1, OwnerChangeRequest(new_owner_user_id=5))

    assert ws_repo.get_by_id_calls == [1]
    assert member_repo.user_exists_calls == [5]
    assert member_repo.get_calls == [(1, 5)]
    # 신규 owner 로 등록했고 role 갱신은 호출되지 않았다.
    assert len(member_repo.add_calls) == 1
    assert member_repo.add_calls[0] == {
        "workspace_id": 1,
        "user_id": 5,
        "role": "owner",
    }
    assert member_repo.set_role_calls == []
    assert isinstance(result, WorkspaceRead)
    assert result.id == 1


def test_change_owner_existing_member_target_updates_role_to_owner():
    # 이미 멤버인 대상은 role=owner 로 갱신된다(5.3).
    workspace = _make_workspace(workspace_id=1)
    existing = _make_member(workspace_id=1, user_id=5, role="member")
    member_repo = _FakeMemberRepo(member=existing, user_exists=True)
    ws_repo = _FakeWsRepo(workspace=workspace)
    service = MembershipService(member_repo, ws_repo)

    result = service.change_owner(DB, 1, OwnerChangeRequest(new_owner_user_id=5))

    # role 갱신 경로를 탔고 신규 등록은 없었다.
    assert len(member_repo.set_role_calls) == 1
    updated_member, role_str = member_repo.set_role_calls[0]
    assert updated_member is existing
    assert role_str == "owner"
    assert member_repo.add_calls == []
    assert isinstance(result, WorkspaceRead)
    assert result.id == 1


def test_change_owner_missing_workspace_raises_404():
    member_repo = _FakeMemberRepo(user_exists=True)
    ws_repo = _FakeWsRepo(workspace=None)
    service = MembershipService(member_repo, ws_repo)

    with pytest.raises(DomainError) as ei:
        service.change_owner(DB, 99, OwnerChangeRequest(new_owner_user_id=5))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    # 워크스페이스가 없으면 어떤 멤버십 변경도 하지 않는다.
    assert member_repo.add_calls == []
    assert member_repo.set_role_calls == []


def test_change_owner_missing_target_user_raises_404():
    workspace = _make_workspace(workspace_id=1)
    member_repo = _FakeMemberRepo(user_exists=False)
    ws_repo = _FakeWsRepo(workspace=workspace)
    service = MembershipService(member_repo, ws_repo)

    with pytest.raises(DomainError) as ei:
        service.change_owner(DB, 1, OwnerChangeRequest(new_owner_user_id=999))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert member_repo.add_calls == []
    assert member_repo.set_role_calls == []


def test_change_owner_owner_absent_workspace_still_gets_new_owner():
    # owner 가 하나도 없는 워크스페이스에도 새 owner 를 신규 등록할 수 있다(5.6).
    workspace = _make_workspace(workspace_id=1)
    member_repo = _FakeMemberRepo(member=None, user_exists=True)
    ws_repo = _FakeWsRepo(workspace=workspace)
    service = MembershipService(member_repo, ws_repo)

    result = service.change_owner(DB, 1, OwnerChangeRequest(new_owner_user_id=8))

    assert member_repo.add_calls[0]["role"] == "owner"
    assert isinstance(result, WorkspaceRead)


def test_change_owner_does_not_demote_existing_other_owners():
    # 대상 멤버만 owner 로 upsert 하며 다른 멤버(기존 owner)는 건드리지 않는다(복수 owner 허용).
    workspace = _make_workspace(workspace_id=1)
    target = _make_member(member_id=20, workspace_id=1, user_id=5, role="member")
    member_repo = _FakeMemberRepo(member=target, user_exists=True)
    ws_repo = _FakeWsRepo(workspace=workspace)
    service = MembershipService(member_repo, ws_repo)

    service.change_owner(DB, 1, OwnerChangeRequest(new_owner_user_id=5))

    # set_role 는 대상 멤버에 대해서만, owner 로만 호출된다(다른 owner 강등 없음).
    assert member_repo.set_role_calls == [(target, "owner")]
    assert member_repo.add_calls == []


# --- list_assignable_users ----------------------------------------------------


def test_list_assignable_users_maps_items_and_total_to_page(): # Req 1.1
    # repo 가 반환한 (users, total) 을 Page[AssignableUserRead] 로 매핑한다.
    users = [
        _make_user(user_id=2, name="Alice", email="alice@example.com"),
        _make_user(user_id=5, name="Bob", email=None),
    ]
    member_repo = _FakeMemberRepo(assignable=(users, 7))
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.list_assignable_users(DB, 1, 50, 0)

    # 저장소에 workspace_id·limit·offset 을 그대로 위임했다.
    assert member_repo.list_assignable_calls == [(1, 50, 0)]
    assert isinstance(result, Page)
    # total 은 items 페이지 길이가 아니라 repo 총수(배정 가능 전체)를 그대로 전달한다.
    assert result.total == 7
    assert len(result.items) == 2
    assert all(isinstance(item, AssignableUserRead) for item in result.items)
    # narrow 스키마: 선언 필드(id/name/email)만 노출되고 계정 필드는 없다.
    first = result.items[0]
    assert (first.id, first.name, first.email) == (2, "Alice", "alice@example.com")
    assert not hasattr(first, "login_id")
    assert not hasattr(first, "password_hash")
    assert not hasattr(first, "is_admin")
    # email null 인 사용자도 제외되지 않고 빈 값(None)으로 직렬화된다(Req 1.3 정합).
    assert result.items[1].email is None


def test_list_assignable_users_empty_result_returns_empty_page(): # Req 1.4
    # 배정 가능 사용자가 없으면 오류가 아니라 빈 Page 를 반환한다.
    member_repo = _FakeMemberRepo(assignable=([], 0))
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.list_assignable_users(DB, 3, 10, 20)

    assert member_repo.list_assignable_calls == [(3, 10, 20)]
    assert isinstance(result, Page)
    assert result.items == []
    assert result.total == 0


# --- list_members -------------------------------------------------------------


def test_list_members_maps_rows_and_passes_through_total():  # Req 1.1·1.2·1.4
    # repo 의 (User, role) 행을 명시 생성으로 MemberRosterRead 로 매핑하고 total 은 그대로 전달한다.
    rows = [
        (_make_user(user_id=2, name="Alice", email="alice@example.com"), "owner"),
        (_make_user(user_id=5, name="Bob", email="bob@example.com"), "member"),
    ]
    # total 을 items 길이(2)와 다른 값(7)으로 두어 len(items) 가 아니라 repo total 을 전달함을 관찰.
    member_repo = _FakeMemberRepo(members=(rows, 7))
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.list_members(DB, 1, 50, 0)

    # 저장소에 workspace_id·limit·offset 을 그대로 위임했다.
    assert member_repo.list_members_calls == [(1, 50, 0)]
    assert isinstance(result, Page)
    # total 은 items 페이지 길이가 아니라 repo 총수를 그대로 전달한다.
    assert result.total == 7
    assert len(result.items) == 2
    assert all(isinstance(item, MemberRosterRead) for item in result.items)
    # 명시 필드 매핑: user.id→user_id, user.name→name, user.email→email, role 문자열→MemberRole.
    first = result.items[0]
    assert (first.user_id, first.name, first.email, first.role) == (
        2,
        "Alice",
        "alice@example.com",
        MemberRole.OWNER,
    )
    second = result.items[1]
    assert (second.user_id, second.name, second.email, second.role) == (
        5,
        "Bob",
        "bob@example.com",
        MemberRole.MEMBER,
    )
    # narrow 스키마: 선언 필드만 노출되고 계정 필드는 원천 제외된다.
    assert not hasattr(first, "login_id")
    assert not hasattr(first, "password_hash")
    assert not hasattr(first, "is_admin")


def test_list_members_normalizes_all_role_strings():  # Req 1.2
    # owner/member 두 문자열이 각각 대응 MemberRole 로 정규화된다(s26 2값).
    rows = [
        (_make_user(user_id=1, name="O"), "owner"),
        (_make_user(user_id=2, name="M"), "member"),
    ]
    member_repo = _FakeMemberRepo(members=(rows, 2))
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.list_members(DB, 1, 50, 0)

    assert [item.role for item in result.items] == [
        MemberRole.OWNER,
        MemberRole.MEMBER,
    ]


def test_list_members_preserves_null_email():  # Req 1.2·1.5
    # 이메일이 없는(또는 비활성/삭제) 멤버도 email: None 으로 로스터에 포함된다.
    rows = [(_make_user(user_id=9, name="NoMail", email=None), "member")]
    member_repo = _FakeMemberRepo(members=(rows, 1))
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.list_members(DB, 1, 50, 0)

    assert len(result.items) == 1
    assert result.items[0].email is None
    assert result.items[0].role == MemberRole.MEMBER


def test_list_members_empty_result_returns_empty_page():  # Req 1.4
    # 멤버 0명(방어적)이라도 오류가 아니라 Page(items=[], total=…) 로 매핑된다.
    member_repo = _FakeMemberRepo(members=([], 0))
    service = MembershipService(member_repo, _FakeWsRepo())

    result = service.list_members(DB, 3, 10, 20)

    assert member_repo.list_members_calls == [(3, 10, 20)]
    assert isinstance(result, Page)
    assert result.items == []
    assert result.total == 0
