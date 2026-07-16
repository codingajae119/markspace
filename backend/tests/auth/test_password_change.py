"""AuthService.change_password 단위 테스트 (Task 2.3 / Req 4.1, 4.2, 4.4, 4.5, 5.4).

design.md §auth/Service #AuthService Contracts (`change_password(ctx, current_password,
new_password) -> None`) 와 System Flows 본인 비밀번호 변경 흐름을 검증한다.

핵심 불변식:
- 현재 비밀번호 일치: 새 해시로 update_password_hash 호출, 저장값은 old 해시가 아니며
  평문도 아니고 verify_password(new_password, new_hash) 가 True. 반환값 None(Req 4.1, 4.4).
- 현재 비밀번호 불일치: DomainError(code=unprocessable, http_status=422) — 401 아님 —
  이며 write(update_password_hash) 는 발생하지 않는다(Req 4.2, 도메인 규칙 위반).
- 대상은 항상 ctx.user_id: update_password_hash 에 전달되는 user 는 repo.get_by_id(
  ctx.user_id) 가 반환한 바로 그 객체이며, 다른 사용자를 지정할 인자가 없다(Req 4.5).

DB 불필요: 가짜 repo(단순 객체)와 실 s01 hash_password 로 seed 한 저장 해시로 충분하다.
"""

from datetime import datetime

import pytest

from app.auth.service import AuthService
from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.common.security import hash_password, verify_password
from app.models import User

CURRENT_PW = "current-pw"
WRONG_PW = "wrong-pw"
NEW_PW = "brand-new-password"


class _FakeRepo:
    """get_by_id / update_password_hash 만 노출하는 최소 가짜 저장소."""

    def __init__(self, user: User | None) -> None:
        self._user = user
        self.get_calls: list[int] = []
        self.update_calls: list[tuple[User, str]] = []

    def get_by_id(self, user_id: int) -> User | None:
        self.get_calls.append(user_id)
        return self._user

    def update_password_hash(self, user: User, password_hash: str) -> None:
        self.update_calls.append((user, password_hash))
        # 실제 repo 처럼 in-place 로 반영해 후속 검증이 최종 상태를 관찰하도록 한다.
        user.password_hash = password_hash


def _make_user(*, user_id: int = 7) -> User:
    return User(
        id=user_id,
        login_id="alice",
        password_hash=hash_password(CURRENT_PW),
        name="Alice",
        email="alice@example.com",
        is_admin=False,
        is_active=True,
        is_deleted=False,
        created_at=datetime(2026, 1, 1),
    )


# --- 성공 경로 -----------------------------------------------------------------


def test_change_password_success_persists_new_hash_and_returns_none():
    user = _make_user(user_id=7)
    old_hash = user.password_hash
    repo = _FakeRepo(user)
    service = AuthService(repo)

    result = service.change_password(
        AuthContext(user_id=7, is_admin=False), CURRENT_PW, NEW_PW
    )

    assert result is None
    # 현재 사용자를 ctx.user_id 로 로드했다.
    assert repo.get_calls == [7]
    # 정확히 한 번, 로드한 바로 그 user 로 write 했다.
    assert len(repo.update_calls) == 1
    written_user, written_hash = repo.update_calls[0]
    assert written_user is user
    # 저장값은 old 해시가 아니다.
    assert written_hash != old_hash
    # 저장값은 평문이 아니다(해시).
    assert written_hash != NEW_PW
    # 저장값은 new_password 의 해시다(verify 통과).
    assert verify_password(NEW_PW, written_hash) is True
    # old 비밀번호로는 더 이상 통과하지 않는다.
    assert verify_password(CURRENT_PW, written_hash) is False


def test_change_password_target_is_ctx_user_id():
    user = _make_user(user_id=42)
    repo = _FakeRepo(user)
    service = AuthService(repo)

    service.change_password(AuthContext(user_id=42, is_admin=False), CURRENT_PW, NEW_PW)

    assert repo.get_calls == [42]
    written_user, _ = repo.update_calls[0]
    # write 대상은 get_by_id(ctx.user_id) 가 반환한 바로 그 객체다(다른 사용자 불가).
    assert written_user is user
    assert written_user.id == 42


# --- 실패 경로: 현재 비밀번호 불일치 -> 422 unprocessable, write 없음 ---------------


def test_change_password_wrong_current_raises_422_unprocessable_and_no_write():
    user = _make_user(user_id=7)
    old_hash = user.password_hash
    repo = _FakeRepo(user)
    service = AuthService(repo)

    with pytest.raises(DomainError) as ei:
        service.change_password(
            AuthContext(user_id=7, is_admin=False), WRONG_PW, NEW_PW
        )

    assert ei.value.code == ErrorCode.UNPROCESSABLE
    assert ei.value.http_status == 422
    # 도메인 규칙 위반이지 인증 실패(401)가 아니다.
    assert ei.value.code != ErrorCode.UNAUTHENTICATED
    # write 는 발생하지 않았고 저장 해시는 그대로다.
    assert repo.update_calls == []
    assert user.password_hash == old_hash


def test_change_password_missing_user_raises_uniform_401():
    # 방어적 처리: ctx.user_id 로 로드했으나 없으면 로그인과 동일한 401.
    repo = _FakeRepo(None)
    service = AuthService(repo)

    with pytest.raises(DomainError) as ei:
        service.change_password(
            AuthContext(user_id=999, is_admin=False), CURRENT_PW, NEW_PW
        )

    assert ei.value.code == ErrorCode.UNAUTHENTICATED
    assert ei.value.http_status == 401
    assert repo.update_calls == []
