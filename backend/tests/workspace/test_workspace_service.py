"""WorkspaceService 단위 테스트 (Task 2.3 / Req 1.1~1.6, 2.1~2.5, 2.7, 6.6).

design.md §Components → WorkspaceService 계약과 §System Flows(생성 흐름), §Error Handling
error table 을 검증한다. 세션(`db`)은 메서드별 인자로 전달받는 계약이므로 가짜 repo 는 각
메서드의 첫 인자로 `db` 를 받는다(s03/s05 UserRepository·WorkspaceRepository 정합).

핵심 불변식:
- create_workspace: 생성 워크스페이스는 is_shareable=False·trash_retention_days=Settings 기본값
  이고 요청자가 owner 멤버로 등록된다(Req 1.1·1.2·6.6).
- list_workspaces: admin → list_all(전체), 비-admin → list_for_user(멤버 스코프),
  Page[WorkspaceRead] 반환(Req 1.3·1.4).
- get_workspace: 미존재 → DomainError(NOT_FOUND, 404), 존재 → WorkspaceRead(Req 1.5·1.6).
- update_workspace: is_shareable·trash_retention_days 부분 갱신, trash_retention_days≤0 → 422
  (영속 없음), 미존재 → 404(Req 2.1·2.2·2.3·2.4·1.6).
- delete_workspace: 빈 워크스페이스는 멤버십 전체 제거 후 물리 삭제, 미존재 → 404, FK RESTRICT
  위반(비-empty, mock IntegrityError) → 409 로 변환·아무것도 제거되지 않음(rollback)(Req 2.5·2.7·1.6).

DB 불필요: 가짜 in-memory repo 로 서비스 로직만 검증한다. delete 의 "아무것도 제거되지 않음"
검증을 유의미하게 만들기 위해 가짜 db.rollback() 이 멤버십 제거를 되돌리는 트랜잭션형 가짜를 쓴다.
"""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.config import get_settings
from app.models import Workspace
from app.schemas.base import Page
from app.workspace.schemas import (
    MemberRole,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.workspace.service import WorkspaceService


def _make_ws(
    *,
    ws_id: int = 1,
    name: str = "WS",
    is_shareable: bool = False,
    trash_retention_days: int = 30,
) -> Workspace:
    return Workspace(
        id=ws_id,
        name=name,
        is_shareable=is_shareable,
        trash_retention_days=trash_retention_days,
        created_at=datetime(2026, 1, 1),
        updated_at=None,
    )


ADMIN_CTX = AuthContext(user_id=7, is_admin=True)
USER_CTX = AuthContext(user_id=42, is_admin=False)


class _FakeDb:
    """멤버십 제거를 되돌릴 수 있는 트랜잭션형 가짜 세션.

    멤버 저장소를 보유하며, 첫 변경 시 스냅샷을 떠 rollback() 이 그 이전 상태로 복원한다.
    commit() 은 스냅샷을 폐기(promote)해 이후 rollback 대상에서 제외한다. 이는 delete 의
    단일 논리 트랜잭션을 이상화한 모델로, 서비스가 IntegrityError 를 409 로 변환하며 rollback
    으로 멤버십 제거를 되돌리는 제어 흐름을 유의미하게 검증하기 위한 것이다.
    """

    def __init__(self) -> None:
        # 멤버 저장소: (workspace_id, user_id, role) dict 리스트(작업 상태).
        self.members: list[dict] = []
        self._snapshot: list[dict] | None = None
        self.rollback_calls = 0

    def _ensure_snapshot(self) -> None:
        if self._snapshot is None:
            self._snapshot = [dict(m) for m in self.members]

    def commit(self) -> None:
        # 영속 확정: 되돌림 지점 폐기.
        self._snapshot = None

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self._snapshot is not None:
            self.members = self._snapshot
            self._snapshot = None


class _FakeWorkspaceRepo:
    """WorkspaceService 가 호출하는 WorkspaceRepository 계약의 최소 가짜 구현.

    모든 메서드는 첫 인자로 `db` 를 받는다. delete 는 `raise_on_delete` 로 IntegrityError
    를 모사할 수 있다(FK RESTRICT 위반 시뮬레이션). apply_updates 는 in-place 반영한다.
    """

    def __init__(
        self,
        *,
        by_id: Workspace | None = None,
        raise_on_delete: bool = False,
    ) -> None:
        self._by_id = by_id
        self._raise_on_delete = raise_on_delete
        self.create_calls: list[dict] = []
        self.get_by_id_calls: list[int] = []
        # list_all 은 이제 호출자 user_id 를 받는다(admin LEFT JOIN 상관 조건, s24).
        self.list_all_calls: list[tuple[int, int, int]] = []
        self.list_for_user_calls: list[tuple[int, int, int]] = []
        self.apply_updates_calls: list[tuple[Workspace, dict]] = []
        self.delete_calls: list[Workspace] = []
        # list_all/list_for_user 는 이제 (Workspace, role) 튜플 목록을 반환한다(s24).
        # list_all 의 role 은 str|None(비멤버 WS 는 None), list_for_user 는 str.
        self.list_all_result: tuple[list[tuple[Workspace, str | None]], int] = ([], 0)
        self.list_for_user_result: tuple[list[tuple[Workspace, str]], int] = ([], 0)
        # create 가 반환할 워크스페이스(서비스가 요청한 trash_retention_days 를 반영).
        self._next_id = 100

    def get_by_id(self, db, workspace_id: int) -> Workspace | None:
        assert isinstance(db, _FakeDb)
        self.get_by_id_calls.append(workspace_id)
        return self._by_id

    def list_all(
        self, db, user_id: int, limit: int, offset: int
    ) -> tuple[list[tuple[Workspace, str | None]], int]:
        assert isinstance(db, _FakeDb)
        self.list_all_calls.append((user_id, limit, offset))
        return self.list_all_result

    def list_for_user(
        self, db, user_id: int, limit: int, offset: int
    ) -> tuple[list[tuple[Workspace, str]], int]:
        assert isinstance(db, _FakeDb)
        self.list_for_user_calls.append((user_id, limit, offset))
        return self.list_for_user_result

    def create(self, db, *, name: str, trash_retention_days: int) -> Workspace:
        assert isinstance(db, _FakeDb)
        self.create_calls.append(
            {"name": name, "trash_retention_days": trash_retention_days}
        )
        # 실제 repo 처럼 is_shareable=False 로 강제된 행을 반환한다.
        ws = _make_ws(
            ws_id=self._next_id,
            name=name,
            is_shareable=False,
            trash_retention_days=trash_retention_days,
        )
        self._next_id += 1
        return ws

    def apply_updates(self, db, ws: Workspace, changes: dict) -> Workspace:
        assert isinstance(db, _FakeDb)
        self.apply_updates_calls.append((ws, changes))
        for key, value in changes.items():
            setattr(ws, key, value)
        return ws

    def delete(self, db, ws: Workspace, commit: bool = True) -> None:
        assert isinstance(db, _FakeDb)
        self.delete_calls.append(ws)
        if self._raise_on_delete:
            # FK ON DELETE RESTRICT 위반(비-empty 워크스페이스)을 모사한다.
            raise IntegrityError("DELETE", {}, Exception("FK RESTRICT"))
        # 서비스는 단일 트랜잭션을 위해 commit=False 로 호출하고 자신이 commit 한다.
        # commit=True(직접 호출 계약 기본값)일 때만 여기서 commit 한다.
        if commit:
            db.commit()


class _FakeMembershipRepo:
    """WorkspaceService 가 호출하는 MembershipRepository 계약의 최소 가짜 구현.

    add·remove_all_for_workspace 는 db.members 저장소를 변경한다. remove_all_for_workspace
    는 되돌림 스냅샷을 확보한 뒤 변경한다(트랜잭션형 가짜).
    """

    def __init__(self, db: _FakeDb) -> None:
        self._db = db
        self.add_calls: list[dict] = []
        self.remove_all_calls: list[int] = []
        # get_workspace 가 호출자 role 주입에 쓰는 조회(비멤버 None). 테스트가 설정한다.
        self.get_role_result: str | None = None
        self.get_role_calls: list[tuple[int, int]] = []

    def get_role(self, db, workspace_id: int, user_id: int) -> str | None:
        assert isinstance(db, _FakeDb)
        self.get_role_calls.append((workspace_id, user_id))
        return self.get_role_result

    def add(self, db, *, workspace_id: int, user_id: int, role: str):
        assert isinstance(db, _FakeDb)
        self.add_calls.append(
            {"workspace_id": workspace_id, "user_id": user_id, "role": role}
        )
        db.members.append(
            {"workspace_id": workspace_id, "user_id": user_id, "role": role}
        )
        return object()

    def remove_all_for_workspace(
        self, db, workspace_id: int, commit: bool = True
    ) -> None:
        assert isinstance(db, _FakeDb)
        self.remove_all_calls.append(workspace_id)
        db._ensure_snapshot()
        db.members = [m for m in db.members if m["workspace_id"] != workspace_id]
        # 서비스는 단일 트랜잭션을 위해 commit=False 로 호출한다(스냅샷은 유지되어
        # 이후 rollback 이 멤버십 제거를 되돌린다). commit=True 일 때만 promote 한다.
        if commit:
            db.commit()


# --- create_workspace ---------------------------------------------------------


def test_create_workspace_defaults_shareable_false_default_retention_and_owner():
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo()
    member_repo = _FakeMembershipRepo(db)
    service = WorkspaceService(ws_repo, member_repo)

    result = service.create_workspace(db, USER_CTX, WorkspaceCreate(name="My WS"))

    # 정확히 한 번 생성했고 기본 보관일은 Settings 기본값을 사용했다.
    assert len(ws_repo.create_calls) == 1
    assert ws_repo.create_calls[0]["name"] == "My WS"
    assert (
        ws_repo.create_calls[0]["trash_retention_days"]
        == get_settings().default_trash_retention_days
    )

    # 응답은 WorkspaceRead 이며 is_shareable=False·기본 보관일이다.
    assert isinstance(result, WorkspaceRead)
    assert result.is_shareable is False
    assert result.trash_retention_days == get_settings().default_trash_retention_days

    # 요청자가 owner 멤버로 등록되었다.
    assert len(member_repo.add_calls) == 1
    add = member_repo.add_calls[0]
    assert add["user_id"] == USER_CTX.user_id
    assert add["role"] == "owner"
    assert add["workspace_id"] == result.id


# --- list_workspaces ----------------------------------------------------------


def test_list_workspaces_admin_uses_list_all():
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo()
    # admin 은 (Workspace, role|None) 튜플 목록을 받는다: 멤버 WS 는 role, 비멤버 WS 는 None.
    ws_repo.list_all_result = (
        [(_make_ws(ws_id=1), "owner"), (_make_ws(ws_id=2), None)],
        5,
    )
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    page = service.list_workspaces(db, ADMIN_CTX, limit=10, offset=0)

    # list_all 은 호출자 user_id 를 함께 전달받는다(admin LEFT JOIN 상관 조건).
    assert ws_repo.list_all_calls == [(ADMIN_CTX.user_id, 10, 0)]
    assert ws_repo.list_for_user_calls == []
    assert isinstance(page, Page)
    assert page.total == 5
    assert [i.id for i in page.items] == [1, 2]
    assert all(isinstance(i, WorkspaceRead) for i in page.items)
    # role 은 리포지토리가 산출한 멤버십 role/None 을 그대로 반영한다(admin 상승 없음, INV-3).
    assert page.items[0].role == MemberRole.OWNER
    assert page.items[1].role is None


def test_list_workspaces_non_admin_uses_list_for_user():
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo()
    ws_repo.list_for_user_result = ([(_make_ws(ws_id=3), "member")], 1)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    page = service.list_workspaces(db, USER_CTX, limit=20, offset=5)

    assert ws_repo.list_for_user_calls == [(USER_CTX.user_id, 20, 5)]
    assert ws_repo.list_all_calls == []
    assert page.total == 1
    assert [i.id for i in page.items] == [3]
    # 비-admin 목록의 각 항목 role 은 호출자 멤버십 role 을 반영한다(Req 1.1).
    assert page.items[0].role == MemberRole.MEMBER


def test_list_workspaces_non_admin_injects_each_membership_role():
    """비-admin 목록: 각 항목 role 이 해당 워크스페이스에서의 호출자 멤버십 role 을 반영한다."""
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo()
    ws_repo.list_for_user_result = (
        [
            (_make_ws(ws_id=1), "owner"),
            (_make_ws(ws_id=2), "member"),
        ],
        2,
    )
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    page = service.list_workspaces(db, USER_CTX, limit=10, offset=0)

    assert [(i.id, i.role) for i in page.items] == [
        (1, MemberRole.OWNER),
        (2, MemberRole.MEMBER),
    ]


def test_list_workspaces_admin_no_role_elevation():
    """admin 이 어떤 WS 의 member 여도 role 은 'member' 로 노출되고 owner 로 상승되지 않는다(INV-3)."""
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo()
    # admin(user_id=7)이 WS1 의 member, WS2 의 비멤버(None)인 상황을 모사한다.
    ws_repo.list_all_result = (
        [(_make_ws(ws_id=1), "member"), (_make_ws(ws_id=2), None)],
        2,
    )
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    page = service.list_workspaces(db, ADMIN_CTX, limit=10, offset=0)

    # 멤버십 role 그대로: member 는 owner 로 상승하지 않고, 비멤버는 None 이다.
    assert page.items[0].role == MemberRole.MEMBER
    assert page.items[0].role != MemberRole.OWNER
    assert page.items[1].role is None


def test_list_workspaces_preserves_existing_fields_with_role_added():
    """role 주입은 기존 응답 필드(id·name·is_shareable·trash_retention_days·타임스탬프)를 무변경 유지한다(Req 1.5)."""
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo()
    ws = _make_ws(
        ws_id=42, name="Docs", is_shareable=True, trash_retention_days=15
    )
    ws_repo.list_for_user_result = ([(ws, "owner")], 1)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    page = service.list_workspaces(db, USER_CTX, limit=10, offset=0)

    item = page.items[0]
    assert item.id == 42
    assert item.name == "Docs"
    assert item.is_shareable is True
    assert item.trash_retention_days == 15
    assert item.created_at == datetime(2026, 1, 1)
    assert item.updated_at is None
    # 가산 필드 role 만 추가된다.
    assert item.role == MemberRole.OWNER


# --- get_workspace ------------------------------------------------------------


def test_get_workspace_missing_raises_404():
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo(by_id=None)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    with pytest.raises(DomainError) as ei:
        service.get_workspace(db, 999, USER_CTX)

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert ws_repo.get_by_id_calls == [999]


def test_get_workspace_present_returns_read_with_caller_role():
    """WS 상세는 이름·설정을 반환하고 호출자 멤버십 role(owner/member)을 주입한다 (Req 3.5)."""
    db = _FakeDb()
    ws = _make_ws(ws_id=8, name="Found", is_shareable=True, trash_retention_days=15)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    member_repo = _FakeMembershipRepo(db)
    member_repo.get_role_result = "member"
    service = WorkspaceService(ws_repo, member_repo)

    result = service.get_workspace(db, 8, USER_CTX)

    assert isinstance(result, WorkspaceRead)
    assert result.id == 8
    assert result.name == "Found"
    assert result.is_shareable is True
    assert result.trash_retention_days == 15
    # 호출자 관점 role 주입: member 멤버 → MemberRole.MEMBER.
    assert result.role == MemberRole.MEMBER
    assert member_repo.get_role_calls == [(8, USER_CTX.user_id)]


def test_get_workspace_injects_owner_role():
    """owner 호출자의 WS 상세 role 은 owner 다 (Req 3.5·5.5)."""
    db = _FakeDb()
    ws = _make_ws(ws_id=8)
    member_repo = _FakeMembershipRepo(db)
    member_repo.get_role_result = "owner"
    service = WorkspaceService(_FakeWorkspaceRepo(by_id=ws), member_repo)

    result = service.get_workspace(db, 8, USER_CTX)

    assert result.role == MemberRole.OWNER


def test_get_workspace_non_member_gets_none_role_still_reads():
    """비멤버 활성 사용자도 WS 상세를 받으며 role 은 None 이다 (Req 3.5·3.8, 읽기 개방)."""
    db = _FakeDb()
    ws = _make_ws(ws_id=8, name="Open", is_shareable=True)
    member_repo = _FakeMembershipRepo(db)
    member_repo.get_role_result = None  # 비멤버.
    service = WorkspaceService(_FakeWorkspaceRepo(by_id=ws), member_repo)

    result = service.get_workspace(db, 8, USER_CTX)

    assert result.id == 8
    assert result.name == "Open"
    assert result.role is None


def test_get_workspace_admin_no_role_elevation():
    """admin 이어도 실제 멤버십 role 만 노출되고 상승되지 않는다 (Req 3.5, INV-3)."""
    db = _FakeDb()
    ws = _make_ws(ws_id=8)
    member_repo = _FakeMembershipRepo(db)
    member_repo.get_role_result = None  # admin 이지만 비멤버.
    service = WorkspaceService(_FakeWorkspaceRepo(by_id=ws), member_repo)

    result = service.get_workspace(db, 8, ADMIN_CTX)

    # admin 비멤버는 role=None(owner 로 상승 없음).
    assert result.role is None


# --- update_workspace ---------------------------------------------------------


def test_update_workspace_missing_raises_404_no_persist():
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo(by_id=None)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    with pytest.raises(DomainError) as ei:
        service.update_workspace(db, 999, WorkspaceUpdate(is_shareable=True))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert ws_repo.apply_updates_calls == []


def test_update_workspace_updates_shareable_and_retention():
    db = _FakeDb()
    ws = _make_ws(ws_id=5, is_shareable=False, trash_retention_days=30)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    result = service.update_workspace(
        db, 5, WorkspaceUpdate(is_shareable=True, trash_retention_days=60)
    )

    assert isinstance(result, WorkspaceRead)
    assert result.is_shareable is True
    assert result.trash_retention_days == 60
    # exclude_unset: 제공된 필드만 갱신 dict 에 담긴다.
    assert len(ws_repo.apply_updates_calls) == 1
    _, changes = ws_repo.apply_updates_calls[0]
    assert changes == {"is_shareable": True, "trash_retention_days": 60}


def test_update_workspace_partial_only_name():
    db = _FakeDb()
    ws = _make_ws(ws_id=5, name="Old")
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    result = service.update_workspace(db, 5, WorkspaceUpdate(name="New"))

    assert result.name == "New"
    _, changes = ws_repo.apply_updates_calls[0]
    assert changes == {"name": "New"}


def test_update_workspace_zero_retention_raises_422_no_persist():
    db = _FakeDb()
    ws = _make_ws(ws_id=5, trash_retention_days=30)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    with pytest.raises(DomainError) as ei:
        service.update_workspace(db, 5, WorkspaceUpdate(trash_retention_days=0))

    assert ei.value.code == ErrorCode.VALIDATION_ERROR
    assert ei.value.http_status == 422
    # 필드 오류가 trash_retention_days 를 가리킨다.
    assert ei.value.field_errors is not None
    assert ei.value.field_errors[0].field == "trash_retention_days"
    # 영속 없음, 값 그대로.
    assert ws_repo.apply_updates_calls == []
    assert ws.trash_retention_days == 30


def test_update_workspace_negative_retention_raises_422_no_persist():
    db = _FakeDb()
    ws = _make_ws(ws_id=5, trash_retention_days=30)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    with pytest.raises(DomainError) as ei:
        service.update_workspace(db, 5, WorkspaceUpdate(trash_retention_days=-1))

    assert ei.value.code == ErrorCode.VALIDATION_ERROR
    assert ei.value.http_status == 422
    assert ws_repo.apply_updates_calls == []
    assert ws.trash_retention_days == 30


def test_update_workspace_explicit_null_retention_raises_422_no_persist():
    """명시적 null 은 NOT NULL 컬럼에 부적합하므로 500 이 아니라 422 로 거부한다(≤0 과 동일).

    `exclude_unset` 이 명시적 None 을 보존하므로 `None <= 0` TypeError(→500)가 나지 않도록
    None 을 먼저 단락 평가해 거부해야 한다.
    """
    db = _FakeDb()
    ws = _make_ws(ws_id=5, trash_retention_days=30)
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    service = WorkspaceService(ws_repo, _FakeMembershipRepo(db))

    with pytest.raises(DomainError) as ei:
        service.update_workspace(db, 5, WorkspaceUpdate(trash_retention_days=None))

    assert ei.value.code == ErrorCode.VALIDATION_ERROR
    assert ei.value.http_status == 422
    assert ws_repo.apply_updates_calls == []
    assert ws.trash_retention_days == 30


# --- delete_workspace ---------------------------------------------------------


def test_delete_workspace_missing_raises_404():
    db = _FakeDb()
    ws_repo = _FakeWorkspaceRepo(by_id=None)
    member_repo = _FakeMembershipRepo(db)
    service = WorkspaceService(ws_repo, member_repo)

    with pytest.raises(DomainError) as ei:
        service.delete_workspace(db, 999)

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert member_repo.remove_all_calls == []
    assert ws_repo.delete_calls == []


def test_delete_workspace_empty_removes_members_and_workspace():
    db = _FakeDb()
    ws = _make_ws(ws_id=5)
    # 워크스페이스 5 에 멤버 둘 + 다른 워크스페이스 멤버 하나.
    db.members = [
        {"workspace_id": 5, "user_id": 1, "role": "owner"},
        {"workspace_id": 5, "user_id": 2, "role": "member"},
        {"workspace_id": 9, "user_id": 3, "role": "owner"},
    ]
    ws_repo = _FakeWorkspaceRepo(by_id=ws)
    member_repo = _FakeMembershipRepo(db)
    service = WorkspaceService(ws_repo, member_repo)

    result = service.delete_workspace(db, 5)

    assert result is None
    # 멤버십·워크스페이스 모두 제거되었다(멤버십 선삭제 후 워크스페이스 삭제).
    assert member_repo.remove_all_calls == [5]
    assert ws_repo.delete_calls == [ws]
    # 워크스페이스 5 의 멤버는 사라지고 다른 워크스페이스 멤버는 유지된다.
    assert [m["workspace_id"] for m in db.members] == [9]


def test_delete_workspace_non_empty_fk_restrict_converts_to_409_nothing_removed():
    db = _FakeDb()
    ws = _make_ws(ws_id=5)
    db.members = [
        {"workspace_id": 5, "user_id": 1, "role": "owner"},
        {"workspace_id": 5, "user_id": 2, "role": "member"},
    ]
    # 물리 DELETE 가 FK RESTRICT 위반(비-empty)으로 IntegrityError 를 던지도록 설정.
    ws_repo = _FakeWorkspaceRepo(by_id=ws, raise_on_delete=True)
    member_repo = _FakeMembershipRepo(db)
    service = WorkspaceService(ws_repo, member_repo)

    with pytest.raises(DomainError) as ei:
        service.delete_workspace(db, 5)

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    # rollback 이 호출되어 멤버십 제거가 되돌려졌다(아무것도 제거되지 않음).
    assert db.rollback_calls == 1
    assert [m["user_id"] for m in db.members] == [1, 2]
