"""인증 동작 오케스트레이션 (s02-auth design.md §auth/Service #AuthService).

s01 계약(비밀번호 해싱·공통 에러·user 스키마·세션 인증)을 재사용하며, 로그인
자격 증명 검증·상태 게이트·세션 write 의 **동작**만 소유한다(Req 5.1).

이 모듈이 소유하는 첫 동작은 로그인(:meth:`AuthService.authenticate`)이다:
`find_by_login_id` → `verify_password`(s01) → `is_active`/`is_deleted` 게이트를
거쳐, 성공 시에만 세션에 사용자 식별자를 기록하고 :class:`AuthUserRead` 를 반환한다.

계정 열거 방지(Req 1.3): 미존재·비밀번호 불일치·비활동·삭제의 **모든** 실패는
동일한 401 :class:`DomainError` 로 통일한다. 단일 생성 지점(:func:`_unauthenticated`)
을 사용해 코드·메시지·status 가 드리프트하지 않도록 한다.
"""

from collections.abc import MutableMapping

from app.auth.repository import AuthUserRepository
from app.auth.schemas import AuthUserRead
from app.common.errors import DomainError, ErrorCode
from app.common.security import verify_password

__all__ = ["AuthService", "SESSION_USER_KEY"]

# 세션 payload 키. s01 `app/common/auth.py` 의 `get_current_user` 가 읽는 키
# (`session.get("user_id")`, line 64)와 반드시 동일해야 우리가 write 한 세션을
# s01 이 인증 컨텍스트로 확정할 수 있다. s01 은 이 값을 상수로 export 하지 않고
# bare literal 로 사용하며, `app/common/*` 는 수정 금지이므로 여기서 상수를 정의한다.
# 값이 바뀌면 s01 세션 인증이 깨지므로 항상 `"user_id"` 로 유지한다.
SESSION_USER_KEY = "user_id"


def _unauthenticated() -> DomainError:
    """로그인 실패 401 의 단일 생성 지점 (Req 1.3, 계정 열거 방지).

    미존재·비밀번호 불일치·비활동·삭제의 실패 원인을 구분하지 않고 동일한
    코드·메시지·status 로 거부하여 계정 존재 여부가 새어나가지 않게 한다.
    """
    return DomainError(
        code=ErrorCode.UNAUTHENTICATED,
        message="Invalid credentials",
        http_status=401,
    )


class AuthService:
    """로그인·로그아웃·me·비밀번호 변경 동작 오케스트레이션 (Req 1.1, 1.3~1.6)."""

    def __init__(self, repo: AuthUserRepository) -> None:
        self._repo = repo

    def authenticate(
        self, login_id: str, password: str, session: MutableMapping
    ) -> AuthUserRead:
        """자격 증명을 검증하고 세션을 발급한다 (Req 1.1, 1.3, 1.4, 1.5, 1.6).

        성공 조건: `login_id` 에 해당하는 사용자가 존재하고, `password` 가 저장된
        해시와 일치하며, 계정이 활동 중(`is_active is True`)이고 삭제되지 않았을
        (`is_deleted is False`) 것. 성공 시 세션에 사용자 식별자만 기록하고
        (`session[SESSION_USER_KEY] = user.id`) :class:`AuthUserRead` 를 반환한다.

        실패 시: 원인(미존재·비밀번호 불일치·비활동·삭제) 불문 동일한 401
        :class:`DomainError` 를 raise 하며, 세션은 절대 write 하지 않는다.
        """
        user = self._repo.find_by_login_id(login_id)

        # 미존재·비밀번호 불일치를 구분하지 않고 동일 401 로 거부한다(Req 1.3).
        # verify_password 는 사용자가 있을 때만 호출하되, 어느 경로든 같은 예외로 통일한다.
        if user is None or not verify_password(password, user.password_hash):
            raise _unauthenticated()

        # 자격 증명이 올바르더라도 비활동·삭제 계정은 동일 401 로 거부한다(Req 1.4, 1.5).
        if user.is_active is False or user.is_deleted is True:
            raise _unauthenticated()

        # 성공 시에만 세션에 사용자 식별자만 기록한다(Req 1.6, 세션 고정 완화 위해 재설정).
        session[SESSION_USER_KEY] = user.id
        return AuthUserRead.model_validate(user)
