"""AdminUserRouter: 계정관리 4개 엔드포인트 (design.md §Components and Interfaces #AdminUserRouter).

s01 카탈로그 행 5~8(`POST/GET /admin/users`·`PATCH /admin/users/{id}`·
`POST /admin/users/{id}/password`)의 HTTP 결선을 소유한다. 요청 본문·쿼리 검증·성공
상태코드 매핑·서비스 위임만 담당하고, 계정 생명주기 **동작**(생성·목록·상태 전이·비밀번호
재설정)은 :class:`AdminAccountService` 에 위임한다(design.md §Dependency Direction).

인증·권한 경계(design.md §AdminGate):
- 전 라우트에 s01 common `require_admin` 을 `Depends(require_admin)` 로 **부착만** 한다
  (게이트 정의는 s01 소유, 재정의 금지). admin 이 아니면 403, 미인증(세션 없음·무효)은
  `require_admin` 이 의존하는 s01 `get_current_user` 가 401 을 산출한다.
- admin 판정 근거는 `AuthContext.is_admin` 단일 출처이며 라우터는 게이트를 통과한
  컨텍스트만 소비한다(비즈니스 로직 없음).

경계(design.md §File Structure): 이 모듈은 s01 `common`·`schemas.base` 와 s03 `service`·
`schemas` 만 import 하며 다른 feature·main 을 import 하지 않는다. 조립(`include_router`)은
task 3.2 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.admin_account.repository import UserRepository
from app.admin_account.schemas import (
    AdminPasswordResetRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.admin_account.service import AdminAccountService
from app.common.auth import AuthContext
from app.common.db import get_db
from app.common.permissions import require_admin
from app.schemas.base import Page

__all__ = ["router", "get_admin_account_service"]

router = APIRouter()


def get_admin_account_service() -> AdminAccountService:
    """AdminAccountService 를 조립하는 의존성 provider.

    s03 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는
    세션 없이 저장소·서비스만 결선한다. 테스트는 ``app.dependency_overrides``
    ``[get_admin_account_service]`` 로 이 provider 를 대체하여 DB 없이 라우터 결선만
    검증할 수 있다.
    """
    return AdminAccountService(UserRepository())


@router.post("/admin/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    service: AdminAccountService = Depends(get_admin_account_service),
    ctx: AuthContext = Depends(require_admin),
) -> UserRead:
    """신규 계정을 생성한다 (Req 2.1·2.2·2.4, admin 전용).

    `require_admin` 으로 admin 게이트를 강제한다(비-admin 403·미인증 401). 스키마 검증
    실패는 pydantic 이 422 로, login_id 중복은 서비스가 409 로 처리한다. 성공 시
    201 + :class:`UserRead`.
    """
    return service.create_user(db, payload)


@router.get("/admin/users", response_model=Page[UserRead])
def list_users(
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    service: AdminAccountService = Depends(get_admin_account_service),
    ctx: AuthContext = Depends(require_admin),
) -> Page[UserRead]:
    """계정 목록을 페이지네이션하여 조회한다 (Req 3.1·3.3·3.4, admin 전용).

    `require_admin` 으로 admin 게이트를 강제한다(비-admin 403·미인증 401). `limit`
    (기본 50)·`offset`(기본 0) 쿼리 파라미터를 서비스로 전달한다. 삭제·비활동 계정도
    제외하지 않으며(관리 대상 노출) 성공 시 200 + ``Page[UserRead]``.
    """
    return service.list_users(db, limit, offset)


@router.patch("/admin/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    changes: UserUpdate,
    db: Session = Depends(get_db),
    service: AdminAccountService = Depends(get_admin_account_service),
    ctx: AuthContext = Depends(require_admin),
) -> UserRead:
    """계정 상태·필드를 부분 갱신한다 (Req 4.1·5.1·6.1, admin 전용).

    `require_admin` 으로 admin 게이트를 강제한다(비-admin 403·미인증 401). 대상 미존재는
    서비스가 404, admin 계정 비활동/삭제 시도는 409(단일 admin 잠금 방지)로 처리하며,
    스키마 검증 실패는 pydantic 이 422 로 처리한다. 성공 시 200 + :class:`UserRead`.
    """
    return service.update_user(db, user_id, changes)


@router.post("/admin/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    req: AdminPasswordResetRequest,
    db: Session = Depends(get_db),
    service: AdminAccountService = Depends(get_admin_account_service),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    """대상 사용자의 비밀번호를 재설정한다 (Req 7.1·7.4, admin 전용).

    `require_admin` 으로 admin 게이트를 강제한다(비-admin 403·미인증 401). 대상 미존재는
    서비스가 404, 새 비밀번호 누락은 pydantic 이 422 로 처리한다. 사용자 self-reset 경로는
    없으며(admin 전용, Req 7.3) 성공 시 본문 없이 204 로 응답한다.
    """
    service.reset_password(db, user_id, req)
