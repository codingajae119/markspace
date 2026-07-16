"""AdminOwnerRouter: admin 소유권 변경 1개 엔드포인트 (design.md §Feature/API #AdminOwnerRouter).

s01 카탈로그 행 9(`POST /admin/workspaces/{id}/owner`, admin 소유권 변경)의 HTTP 결선을
소유한다. 요청 본문 검증·게이트 부착·서비스 위임만 담당하고, 대상 사용자를 owner 로 지정하는
upsert **동작**은 :meth:`MembershipService.change_owner` 에 위임한다(design.md §Dependency
Direction).

인증·권한 경계(design.md §require_admin (s01 공통 게이트 소비)):
- s01 common `require_admin` 을 `Depends(require_admin)` 로 **부착만** 한다(게이트 정의는 s01
  소유, 재정의 금지). 행 9 는 owner 가 아니라 admin 전용이므로 `require_ws_role(OWNER)` 로
  표현할 수 없다. admin 이 아니면 403, 미인증(세션 없음·무효)은 `require_admin` 이 의존하는 s01
  `get_current_user` 가 401 을 산출한다.

경계(design.md §File Structure): 이 모듈은 s01 `common`·s05 `service`·`schemas` 만 import 하며
다른 feature·main 을 import 하지 않는다. 서비스 provider 는 이 모듈에 자족적으로 정의해
`router.py` 와 독립이다. 조립(`include_router`)은 task 3.3 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.db import get_db
from app.common.permissions import require_admin
from app.workspace.repository import MembershipRepository, WorkspaceRepository
from app.workspace.schemas import OwnerChangeRequest, WorkspaceRead
from app.workspace.service import MembershipService

__all__ = ["router", "get_membership_service"]

router = APIRouter()


def get_membership_service() -> MembershipService:
    """MembershipService 를 조립하는 의존성 provider.

    s05 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는 세션
    없이 저장소·서비스만 결선한다. 생성자 순서는 `(member_repo, ws_repo)` 다(service.py 계약).
    이 모듈은 `router.py` 의 동명 provider 를 import 하지 않고 자족적으로 정의해 경계를 유지한다.
    테스트는 ``app.dependency_overrides[get_membership_service]`` 로 이 provider 를 대체하여
    DB 없이 라우터 결선만 검증할 수 있다.
    """
    return MembershipService(MembershipRepository(), WorkspaceRepository())


@router.post("/admin/workspaces/{id}/owner", response_model=WorkspaceRead)
def change_owner(
    id: int,
    payload: OwnerChangeRequest,
    db: Session = Depends(get_db),
    service: MembershipService = Depends(get_membership_service),
    ctx: AuthContext = Depends(require_admin),
) -> WorkspaceRead:
    """지정 사용자를 워크스페이스 owner 로 설정한다 (Req 5.1·5.4·6.2·6.4, admin 전용).

    `require_admin` 으로 admin 게이트를 강제한다(비-admin 403·미인증 401). 대상 워크스페이스
    또는 사용자 미존재는 서비스가 404, `new_owner_user_id` 누락은 pydantic 이 422 로 처리한다.
    upsert-to-owner 로직은 서비스가 소유하며 라우터는 위임만 한다. 성공 시 200 +
    :class:`WorkspaceRead`.
    """
    return service.change_owner(db, id, payload)
