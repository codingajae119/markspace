"""AdminAccountService 단위 테스트 (Task 2.2 / Req 2.1~2.4, 4.1~4.5, 5.1~5.5, 6.1~6.3, 7.1~7.4, 8.2).

design.md §Components and Interfaces #AdminAccountService 계약과 §System Flows(생성 흐름·
상태 전이 판정 PATCH flowchart)을 검증한다. 세션(`db`)은 메서드별 인자로 전달받는 계약이므로
가짜 repo 는 각 메서드의 첫 인자로 `db` 를 받고 dummy 센티널을 통과시킨다.

핵심 불변식:
- create_user: 정상 생성 시 활동·비삭제·비관리자, 비밀번호는 해시로 저장(평문 아님).
  login_id 중복 → DomainError(CONFLICT, 409), 생성 없음(Req 2.1·2.2·2.3·2.4).
- update_user: 미존재 → DomainError(NOT_FOUND, 404). admin 대상 비활동/삭제 방향 전환
  (is_active=False·is_deleted=True) → DomainError(CONFLICT, 409), 영속 없음. admin 재활성화
  (is_deleted=False)·이름 편집은 허용. is_active·is_deleted 독립 갱신(Req 4.1·4.4·4.5·5.1·5.5·6.1·6.2).
- reset_password: 미존재 → 404. 정상 경로는 새 비밀번호의 해시로 저장(평문 아님)(Req 7.1·7.2·7.4).

DB 불필요: 가짜 in-memory repo 와 실 s01 hash_password/verify_password 로 해싱을 증명한다.
"""

from datetime import datetime

import pytest

from app.admin_account.schemas import (
    AdminPasswordResetRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.admin_account.service import AdminAccountService
from app.common.errors import DomainError, ErrorCode
from app.common.security import hash_password, verify_password
from app.models import User
from app.schemas.base import Page

DB = object()  # db 센티널: 가짜 repo 로 그대로 통과되며 내용은 검증에 쓰이지 않는다.

INITIAL_PW = "initial-pw"
NEW_PW = "brand-new-password"


def _make_user(
    *,
    user_id: int = 1,
    login_id: str = "alice",
    name: str = "Alice",
    email: str | None = "alice@example.com",
    is_admin: bool = False,
    is_active: bool = True,
    is_deleted: bool = False,
) -> User:
    return User(
        id=user_id,
        login_id=login_id,
        password_hash=hash_password(INITIAL_PW),
        name=name,
        email=email,
        is_admin=is_admin,
        is_active=is_active,
        is_deleted=is_deleted,
        created_at=datetime(2026, 1, 1),
    )


class _FakeRepo:
    """AdminAccountService 가 호출하는 UserRepository 계약의 최소 가짜 구현.

    모든 메서드는 첫 인자로 `db` 를 받는다(s03 계약). apply_updates·set_password_hash 는
    in-place 로 반영해 후속 검증이 최종 상태를 관찰하도록 한다(실제 repo 의 영속 관찰과 정합).
    """

    def __init__(
        self,
        *,
        by_id: User | None = None,
        by_login_id: User | None = None,
    ) -> None:
        self._by_id = by_id
        self._by_login_id = by_login_id
        self.get_by_id_calls: list[int] = []
        self.get_by_login_id_calls: list[str] = []
        self.list_calls: list[tuple[int, int]] = []
        self.create_calls: list[dict] = []
        self.apply_updates_calls: list[tuple[User, dict]] = []
        self.set_password_hash_calls: list[tuple[User, str]] = []
        self.list_result: tuple[list[User], int] = ([], 0)

    def get_by_id(self, db, user_id: int) -> User | None:
        assert db is DB
        self.get_by_id_calls.append(user_id)
        return self._by_id

    def get_by_login_id(self, db, login_id: str) -> User | None:
        assert db is DB
        self.get_by_login_id_calls.append(login_id)
        return self._by_login_id

    def list_paginated(self, db, limit: int, offset: int) -> tuple[list[User], int]:
        assert db is DB
        self.list_calls.append((limit, offset))
        return self.list_result

    def create(self, db, *, login_id, password_hash, name, email) -> User:
        assert db is DB
        self.create_calls.append(
            {
                "login_id": login_id,
                "password_hash": password_hash,
                "name": name,
                "email": email,
            }
        )
        # 실제 repo 처럼 기본 상태로 생성한 행을 반환한다.
        return User(
            id=100,
            login_id=login_id,
            password_hash=password_hash,
            name=name,
            email=email,
            is_admin=False,
            is_active=True,
            is_deleted=False,
            created_at=datetime(2026, 1, 1),
        )

    def apply_updates(self, db, user: User, changes: dict) -> User:
        assert db is DB
        self.apply_updates_calls.append((user, changes))
        for key, value in changes.items():
            setattr(user, key, value)
        return user

    def set_password_hash(self, db, user: User, password_hash: str) -> User:
        assert db is DB
        self.set_password_hash_calls.append((user, password_hash))
        user.password_hash = password_hash
        return user


# --- create_user --------------------------------------------------------------


def test_create_user_defaults_active_not_deleted_not_admin_and_hashes_password():
    repo = _FakeRepo(by_login_id=None)  # login_id 미존재
    service = AdminAccountService(repo)
    payload = UserCreate(
        login_id="bob", password="plaintext-pw", name="Bob", email="bob@example.com"
    )

    result = service.create_user(DB, payload)

    # 중복 검사에 login_id 를 사용했다.
    assert repo.get_by_login_id_calls == ["bob"]
    # 정확히 한 번 생성했다.
    assert len(repo.create_calls) == 1
    created = repo.create_calls[0]
    # 평문이 아니라 해시로 저장했다.
    assert created["password_hash"] != "plaintext-pw"
    assert verify_password("plaintext-pw", created["password_hash"]) is True
    assert created["login_id"] == "bob"
    assert created["name"] == "Bob"
    assert created["email"] == "bob@example.com"

    # 응답은 UserRead 이며 기본 상태(활동·비삭제·비관리자)다.
    assert isinstance(result, UserRead)
    assert result.is_active is True
    assert result.is_deleted is False
    assert result.is_admin is False
    # 응답에 password 필드가 없다(민감 필드 미노출).
    assert not hasattr(result, "password_hash")


def test_create_user_duplicate_login_id_raises_409_and_does_not_create():
    existing = _make_user(login_id="dup")
    repo = _FakeRepo(by_login_id=existing)
    service = AdminAccountService(repo)
    payload = UserCreate(login_id="dup", password="pw", name="Dup")

    with pytest.raises(DomainError) as ei:
        service.create_user(DB, payload)

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    # 생성은 발생하지 않았다.
    assert repo.create_calls == []


# --- list_users ---------------------------------------------------------------


def test_list_users_returns_page_with_items_and_total():
    u1 = _make_user(user_id=1, login_id="a")
    u2 = _make_user(user_id=2, login_id="b", is_deleted=True)
    u3 = _make_user(user_id=3, login_id="c", is_active=False)
    repo = _FakeRepo()
    repo.list_result = ([u1, u2, u3], 42)  # total 은 삭제·비활동 포함 전체 개수
    service = AdminAccountService(repo)

    page = service.list_users(DB, limit=10, offset=0)

    assert repo.list_calls == [(10, 0)]
    assert isinstance(page, Page)
    assert page.total == 42
    assert len(page.items) == 3
    # 삭제·비활동 계정도 제외되지 않는다.
    assert all(isinstance(item, UserRead) for item in page.items)
    assert [i.id for i in page.items] == [1, 2, 3]


# --- update_user --------------------------------------------------------------


def test_update_user_missing_target_raises_404():
    repo = _FakeRepo(by_id=None)
    service = AdminAccountService(repo)

    with pytest.raises(DomainError) as ei:
        service.update_user(DB, 999, UserUpdate(name="new"))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert repo.apply_updates_calls == []


def test_update_user_admin_target_deactivate_raises_409_no_persist():
    admin = _make_user(user_id=1, login_id="admin", is_admin=True)
    repo = _FakeRepo(by_id=admin)
    service = AdminAccountService(repo)

    with pytest.raises(DomainError) as ei:
        service.update_user(DB, 1, UserUpdate(is_active=False))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    # 영속 없음, 상태 그대로.
    assert repo.apply_updates_calls == []
    assert admin.is_active is True


def test_update_user_admin_target_delete_raises_409_no_persist():
    admin = _make_user(user_id=1, login_id="admin", is_admin=True)
    repo = _FakeRepo(by_id=admin)
    service = AdminAccountService(repo)

    with pytest.raises(DomainError) as ei:
        service.update_user(DB, 1, UserUpdate(is_deleted=True))

    assert ei.value.code == ErrorCode.CONFLICT
    assert ei.value.http_status == 409
    assert repo.apply_updates_calls == []
    assert admin.is_deleted is False


def test_update_user_admin_reactivation_allowed_and_preserves_is_active():
    # admin 이지만 삭제 flag 되돌림(비활성 방향 아님)은 허용되고 is_active 는 그대로다.
    admin = _make_user(
        user_id=1, login_id="admin", is_admin=True, is_active=True, is_deleted=True
    )
    repo = _FakeRepo(by_id=admin)
    service = AdminAccountService(repo)

    result = service.update_user(DB, 1, UserUpdate(is_deleted=False))

    assert isinstance(result, UserRead)
    assert result.is_deleted is False
    # is_active 는 건드리지 않는다(독립성).
    assert result.is_active is True
    # apply_updates 에 넘긴 dict 는 명시된 필드만 담는다(exclude_unset).
    assert len(repo.apply_updates_calls) == 1
    _, changes = repo.apply_updates_calls[0]
    assert changes == {"is_deleted": False}


def test_update_user_admin_name_email_edit_allowed():
    admin = _make_user(user_id=1, login_id="admin", is_admin=True)
    repo = _FakeRepo(by_id=admin)
    service = AdminAccountService(repo)

    result = service.update_user(DB, 1, UserUpdate(name="New Name"))

    assert isinstance(result, UserRead)
    assert result.name == "New Name"
    _, changes = repo.apply_updates_calls[0]
    assert changes == {"name": "New Name"}


def test_update_user_reactivate_normal_user_keeps_is_active_independent():
    # 삭제된 일반 사용자의 재활성화는 is_deleted=False 만 바꾸고 is_active 를 건드리지 않는다.
    user = _make_user(user_id=5, is_active=False, is_deleted=True)
    repo = _FakeRepo(by_id=user)
    service = AdminAccountService(repo)

    result = service.update_user(DB, 5, UserUpdate(is_deleted=False))

    assert result.is_deleted is False
    # is_active 는 자동 변경되지 않는다(독립성).
    assert result.is_active is False
    _, changes = repo.apply_updates_calls[0]
    assert changes == {"is_deleted": False}


def test_update_user_deactivate_normal_user_keeps_is_deleted_independent():
    user = _make_user(user_id=6, is_active=True, is_deleted=False)
    repo = _FakeRepo(by_id=user)
    service = AdminAccountService(repo)

    result = service.update_user(DB, 6, UserUpdate(is_active=False))

    assert result.is_active is False
    assert result.is_deleted is False
    _, changes = repo.apply_updates_calls[0]
    assert changes == {"is_active": False}


def test_update_user_uses_exclude_unset_for_none_explicit_vs_unset():
    # email 을 명시적으로 None 으로 설정하면 변경으로 취급되고, 미설정 필드는 제외된다.
    user = _make_user(user_id=7, email="old@example.com")
    repo = _FakeRepo(by_id=user)
    service = AdminAccountService(repo)

    service.update_user(DB, 7, UserUpdate(email=None))

    _, changes = repo.apply_updates_calls[0]
    # 명시적으로 준 email 만 담긴다(다른 미설정 필드는 없다).
    assert changes == {"email": None}


# --- reset_password -----------------------------------------------------------


def test_reset_password_missing_target_raises_404():
    repo = _FakeRepo(by_id=None)
    service = AdminAccountService(repo)

    with pytest.raises(DomainError) as ei:
        service.reset_password(DB, 999, AdminPasswordResetRequest(new_password=NEW_PW))

    assert ei.value.code == ErrorCode.NOT_FOUND
    assert ei.value.http_status == 404
    assert repo.set_password_hash_calls == []


def test_reset_password_stores_hash_not_plaintext_and_returns_none():
    user = _make_user(user_id=3)
    old_hash = user.password_hash
    repo = _FakeRepo(by_id=user)
    service = AdminAccountService(repo)

    result = service.reset_password(
        DB, 3, AdminPasswordResetRequest(new_password=NEW_PW)
    )

    assert result is None
    assert repo.get_by_id_calls == [3]
    assert len(repo.set_password_hash_calls) == 1
    written_user, written_hash = repo.set_password_hash_calls[0]
    assert written_user is user
    # 저장값은 old 해시도, 평문도 아니고 new_password 의 해시다.
    assert written_hash != old_hash
    assert written_hash != NEW_PW
    assert verify_password(NEW_PW, written_hash) is True
