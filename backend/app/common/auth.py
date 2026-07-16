"""세션 인증 의존성 (Requirement 4.1~4.5, design.md §Common/Auth #SessionAuth).

서명 쿠키 세션(Starlette ``SessionMiddleware``)의 ``user_id`` 로 현재 사용자를
로드하고 ``is_active``·``is_deleted`` 를 검사하여 :class:`AuthContext` 를 확정한다.
admin 여부를 컨텍스트에 노출하여 권한 resolver 의 admin bypass 판정 근거를 제공한다.

세션 없음/무효/비활동/삭제 사용자는 모두 ``DomainError(UNAUTHENTICATED, 401)`` 로
거부한다(세션 인증 판정 흐름).

Boundary: 이 모듈은 세션에서 현재 사용자를 **읽어 확정**하기만 한다. 세션 저장은
``SessionMiddleware``(서명 쿠키)가 담당하며, 로그인 자격증명 검증·세션 write/clear
(로그인/로그아웃)는 s02 소유로 이 spec 범위 밖이다(Req 4.5).

의존 방향: db·errors·models(공통/좌측) + fastapi/pydantic/sqlalchemy 만 import 한다.
permissions·routers·main·feature 도메인은 import 하지 않는다.
"""

from fastapi import Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode
from app.models import User


class AuthContext(BaseModel):
    """인증된 현재 사용자 컨텍스트.

    ``is_admin`` 은 권한 resolver 가 admin bypass(INV-3)를 판정하도록 노출한다.
    """

    user_id: int
    is_admin: bool


def _unauthenticated() -> DomainError:
    return DomainError(
        code=ErrorCode.UNAUTHENTICATED,
        message="Authentication required",
        http_status=401,
    )


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> AuthContext:
    """서명 세션의 ``user_id`` 로 현재 사용자를 확정한다 (Req 4.1~4.4).

    사용법: ``current: AuthContext = Depends(get_current_user)``.

    - 세션 미접근(미들웨어 미등록)·``user_id`` 없음 → 401 (Req 4.2).
    - ``user_id`` 가 존재하지 않는 사용자를 가리킴 → 401 (Req 4.2).
    - ``is_active is False`` 또는 ``is_deleted is True`` → 401 (Req 4.3).
    - 그 외 → ``AuthContext(user_id, is_admin)`` (Req 4.1, 4.4).
    """
    # SessionMiddleware 미등록 시 request.session 접근은 AssertionError 를 던진다.
    # 미인증으로 간주한다(Req 4.2).
    try:
        session = request.session
    except (AssertionError, AttributeError, KeyError) as exc:
        raise _unauthenticated() from exc

    user_id = session.get("user_id")
    if user_id is None:
        raise _unauthenticated()

    user = db.get(User, user_id)
    if user is None:
        raise _unauthenticated()

    if user.is_active is False or user.is_deleted is True:
        raise _unauthenticated()

    return AuthContext(user_id=user.id, is_admin=user.is_admin)
