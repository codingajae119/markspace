"""인증 HTTP 라우터 (s02-auth design.md §auth/API #AuthRouter).

s01 엔드포인트 카탈로그 1~4번(`/auth/login`·`/auth/logout`·`/auth/me`·`/auth/password`)의
HTTP 결선을 소유한다. 요청 본문 파싱·상태코드·세션 I/O 만 담당하고, 자격 증명 검증·
상태 게이트·세션 write/clear 의 **동작**은 :class:`AuthService` 에 위임한다(Req 5.2).

인증 경계:
- `/auth/login` 은 공개(인증 의존성 없음). `request.session` 을 서비스에 전달하여
  성공 시에만 세션이 write 된다(Req 1.2).
- `/auth/logout`·`/auth/me`·`/auth/password` 는 s01 ``get_current_user`` 를 강제하여
  미인증·비활동·삭제 세션을 401 로 거부한다(Req 2.3, 3.2, 3.3, 4.6).

경계(design.md §Out of Boundary): self sign-up·비밀번호 분실 자가 재설정·계정
생명주기 mutation 엔드포인트는 제공하지 않는다(Req 5.3). 이 4개 엔드포인트만 소유한다.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.repository import AuthUserRepository
from app.auth.schemas import AuthUserRead, LoginRequest, PasswordChangeRequest
from app.auth.service import AuthService
from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db

__all__ = ["router", "get_auth_service"]

router = APIRouter()


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    """요청 스코프 세션으로 AuthService 를 조립하는 의존성 provider.

    s01 ``get_db`` 요청 스코프 세션 위에 저장소·서비스를 결선한다. 테스트는
    ``app.dependency_overrides[get_auth_service]`` 로 이 provider 를 대체하여
    DB 없이 라우터 결선만 검증할 수 있다.
    """
    return AuthService(AuthUserRepository(db))


@router.post("/auth/login", response_model=AuthUserRead)
def login(
    payload: LoginRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AuthUserRead:
    """자격 증명으로 로그인하고 세션을 발급한다 (Req 1.2, 공개).

    인증 의존성이 없는 공개 엔드포인트다. 성공 시 200 + :class:`AuthUserRead`,
    실패 시 서비스가 raise 하는 401(자격 증명) 또는 요청 검증 실패 422 로 응답한다.
    """
    return service.authenticate(payload.login_id, payload.password, request.session)


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    service: AuthService = Depends(get_auth_service),
    ctx: AuthContext = Depends(get_current_user),
) -> None:
    """현재 세션을 종료한다 (Req 2.2, 2.3).

    ``get_current_user`` 로 인증을 강제하므로 미인증 요청은 401 로 거부된다.
    성공 시 세션을 clear 하고 본문 없이 204 로 응답한다.
    """
    service.logout(request.session)


@router.get("/auth/me", response_model=AuthUserRead)
def me(
    service: AuthService = Depends(get_auth_service),
    ctx: AuthContext = Depends(get_current_user),
) -> AuthUserRead:
    """현재 인증된 사용자 정보를 조회한다 (Req 3.1, 3.2, 3.3).

    ``get_current_user`` 로 인증을 강제한다(미인증·비활동·삭제 세션은 401).
    성공 시 200 + :class:`AuthUserRead`.
    """
    return service.get_me(ctx)


@router.post("/auth/password", status_code=204)
def change_password(
    payload: PasswordChangeRequest,
    service: AuthService = Depends(get_auth_service),
    ctx: AuthContext = Depends(get_current_user),
) -> None:
    """본인 비밀번호를 변경한다 (Req 4.5, 4.6).

    대상은 항상 현재 인증 사용자(``ctx.user_id``)로 한정된다. ``get_current_user`` 로
    인증을 강제하며(미인증 401), 새 비밀번호 정책 위반은 스키마 계층에서 422 로
    거부된다. 성공 시 본문 없이 204 로 응답한다.
    """
    service.change_password(ctx, payload.current_password, payload.new_password)
