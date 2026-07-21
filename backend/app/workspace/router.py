"""워크스페이스·멤버십 라우터 (design.md §Components → WorkspaceRouter).

워크스페이스·멤버십 8개 엔드포인트(s01 카탈로그 행 10~17)의 HTTP 결선을 소유한다. 요청
본문·쿼리 검증·성공 상태코드 매핑·게이트 부착·서비스 위임만 담당하고, 생성(owner화)·목록·
상세·설정·삭제 및 멤버 추가·role 변경·제거 **동작**은 :class:`WorkspaceService`·
:class:`MembershipService` 에 위임한다(design.md §Dependency Direction).

게이트(design.md §WorkspaceRouter 게이트):
- 생성·목록은 인증만(`Depends(get_current_user)`), 상세는 `require_ws_role(VIEWER)`,
  수정·삭제·멤버 관리는 `require_ws_role(OWNER)` 를 **부착만** 한다. 위계 비교·admin bypass·
  403 판정은 전부 s01 resolver 소유이며(s05 재구현 없음), 미인증(세션 없음·무효)은
  `get_current_user` 가 401 을 산출한다.
- 경로 파라미터: 워크스페이스 id 는 `{id}`(s05 어댑터가 workspace_id 로 브리징), 멤버 대상
  user 는 `{uid}` 로 선언한다.

경계(design.md §File Structure): 이 모듈은 s01 `common`·`schemas.base` 와 s05 `service`·
`schemas`·`dependencies` 만 import 하며 다른 feature·main 을 import 하지 않는다. admin 소유권
라우터(`admin_router.py`)·조립(`include_router`)은 각각 task 3.2·3.3 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.schemas.base import Page
from app.workspace.dependencies import Role, require_ws_role
from app.workspace.repository import MembershipRepository, WorkspaceRepository
from app.workspace.schemas import (
    AssignableUserRead,
    MemberCreate,
    MemberRead,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.workspace.service import MembershipService, WorkspaceService

__all__ = ["router", "get_workspace_service", "get_membership_service"]

router = APIRouter()


def get_workspace_service() -> WorkspaceService:
    """WorkspaceService 를 조립하는 의존성 provider.

    s05 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는
    세션 없이 저장소·서비스만 결선한다. 생성자 순서는 `(ws_repo, member_repo)` 다. 테스트는
    ``app.dependency_overrides[get_workspace_service]`` 로 이 provider 를 대체해 DB 없이
    라우터 결선만 검증할 수 있다.
    """
    return WorkspaceService(WorkspaceRepository(), MembershipRepository())


def get_membership_service() -> MembershipService:
    """MembershipService 를 조립하는 의존성 provider.

    생성자 순서는 `(member_repo, ws_repo)` 로 WorkspaceService 와 반대다(service.py 계약).
    provider 는 세션 없이 저장소만 주입한다.
    """
    return MembershipService(MembershipRepository(), WorkspaceRepository())


@router.post("/workspaces", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceRead:
    """워크스페이스를 생성하고 요청자를 owner 멤버로 등록한다 (Req 1.1·6.2, 인증 전용).

    인증만 요구한다(`get_current_user`, 미인증 401). 스키마 검증 실패는 pydantic 이 422 로
    처리한다. 성공 시 201 + :class:`WorkspaceRead`.
    """
    return service.create_workspace(db, ctx, payload)


@router.get("/workspaces", response_model=Page[WorkspaceRead])
def list_workspaces(
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> Page[WorkspaceRead]:
    """요청자 스코프의 워크스페이스 목록을 페이지네이션하여 조회한다 (Req 1.3·6.2, 인증 전용).

    인증만 요구한다(미인증 401). `limit`(기본 50)·`offset`(기본 0) 쿼리 파라미터와 컨텍스트를
    서비스로 전달한다(admin 전체·비-admin 멤버 스코프 분기는 서비스 소유). 성공 시 200 +
    ``Page[WorkspaceRead]``.
    """
    return service.list_workspaces(db, ctx, limit, offset)


@router.get("/workspaces/{id}", response_model=WorkspaceRead)
def get_workspace(
    id: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.VIEWER)),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceRead:
    """워크스페이스 상세를 조회한다 (Req 1.5·4.3, viewer 이상).

    `require_ws_role(VIEWER)` 로 게이트를 강제한다(위계 미달·비멤버 403, admin bypass, 미인증
    401 — 판정은 s01 소유). 대상 미존재는 서비스가 404 로 처리한다. 성공 시 200 +
    :class:`WorkspaceRead`.
    """
    return service.get_workspace(db, id)


@router.patch("/workspaces/{id}", response_model=WorkspaceRead)
def update_workspace(
    id: int,
    changes: WorkspaceUpdate,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.OWNER)),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceRead:
    """워크스페이스 설정을 부분 갱신한다 (Req 2.1·4.4, owner 전용).

    `require_ws_role(OWNER)` 로 게이트를 강제한다(위계 미달·비멤버 403, admin bypass, 미인증
    401). 대상 미존재는 서비스가 404, `trash_retention_days`≤0 은 422 로 처리하며 스키마 검증
    실패는 pydantic 이 422 로 처리한다. 성공 시 200 + :class:`WorkspaceRead`.
    """
    return service.update_workspace(db, id, changes)


@router.delete("/workspaces/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    id: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.OWNER)),
    service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """워크스페이스를 삭제한다 — 빈 워크스페이스만 (Req 2.5·4.4, owner 전용).

    `require_ws_role(OWNER)` 로 게이트를 강제한다(403/401 판정은 s01 소유). 대상 미존재는
    서비스가 404, 비-empty 삭제는 409 로 처리한다. 성공 시 본문 없이 204 로 응답한다.
    """
    service.delete_workspace(db, id)


@router.get(
    "/workspaces/{id}/assignable-users",
    response_model=Page[AssignableUserRead],
)
def list_assignable_users(
    id: int,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.OWNER)),
    service: MembershipService = Depends(get_membership_service),
) -> Page[AssignableUserRead]:
    """대상 워크스페이스에 배정 가능한 사용자를 페이지네이션 조회한다 (Req 1.1·1.4·1.5·2.1~2.4, owner 전용).

    `require_ws_role(OWNER)` 로 게이트를 강제한다(위계 미달·비멤버 403, admin bypass, 미인증
    401 — 판정은 s01 소유). 존재하지 않는 워크스페이스도 게이트 단계에서 비-멤버 → 403 이며
    404 로 존재를 노출하지 않는다(anti-enumeration, 별도 존재 검사 없음). `limit`(기본 50)·
    `offset`(기본 0) 범위 위반은 FastAPI 가 422 로 처리한다. 성공 시 200 +
    ``Page[AssignableUserRead]``(빈 목록도 오류 아님, R1.4).
    """
    return service.list_assignable_users(db, id, limit, offset)


@router.post(
    "/workspaces/{id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    id: int,
    payload: MemberCreate,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.OWNER)),
    service: MembershipService = Depends(get_membership_service),
) -> MemberRead:
    """대상 사용자를 지정 role 의 멤버로 등록한다 (Req 3.1·4.4, owner 전용).

    `require_ws_role(OWNER)` 로 게이트를 강제한다(403/401 판정은 s01 소유). 대상 user 미존재는
    서비스가 404, 이미 멤버이면 409, 잘못된 role 문자열은 pydantic 이 422 로 처리한다. 성공 시
    201 + :class:`MemberRead`.
    """
    return service.add_member(db, id, payload)


@router.patch("/workspaces/{id}/members/{uid}", response_model=MemberRead)
def change_role(
    id: int,
    uid: int,
    changes: MemberUpdate,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.OWNER)),
    service: MembershipService = Depends(get_membership_service),
) -> MemberRead:
    """멤버의 role 을 갱신한다 (Req 3.5·4.4, owner 전용).

    `require_ws_role(OWNER)` 로 게이트를 강제한다(403/401 판정은 s01 소유). 대상 멤버십 미존재는
    서비스가 404, 잘못된 role 문자열은 pydantic 이 422 로 처리한다. 성공 시 200 +
    :class:`MemberRead`.
    """
    return service.change_role(db, id, uid, changes)


@router.delete(
    "/workspaces/{id}/members/{uid}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_member(
    id: int,
    uid: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.OWNER)),
    service: MembershipService = Depends(get_membership_service),
) -> None:
    """멤버십을 제거한다 (Req 3.4·4.4, owner 전용).

    `require_ws_role(OWNER)` 로 게이트를 강제한다(403/401 판정은 s01 소유). 대상 멤버십 미존재는
    서비스가 404 로 처리한다. 성공 시 본문 없이 204 로 응답한다.
    """
    service.remove_member(db, id, uid)
