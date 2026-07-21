"""TrashRouter — 휴지통 3개 엔드포인트 (카탈로그 행 29~31)
(design.md §Components and Interfaces #TrashRouter).

`GET /workspaces/{id}/trash`·`POST /trash/{bundleId}/restore`·`DELETE /trash/{bundleId}`
를 노출한다. 세 경로 모두 member 이상으로 게이팅되며 판정은 s01 resolver(`require_ws_role`)
가 담당한다. 라우터는 스키마 검증·게이트·서비스 위임·상태코드 매핑만 한다(로직은 서비스,
상태 전이는 엔진, 판정은 s01 resolver).

게이트 결선(design.md §TrashRouter 게이트):
- `/workspaces/{id}/trash`(목록)는 경로 `{id}` 를 그대로 workspace_id 로 사용하므로 s05
  `{id}`→workspace_id 브리지(`app.workspace.dependencies.require_ws_role`)로 게이팅한다.
  핸들러의 경로 파라미터 이름은 `id` 여야 브리지가 바인딩하며, 그 `id` 를 그대로 서비스
  `list_trash` 의 workspace_id 로 넘긴다.
- `/trash/{bundleId}/*`(복구·완전삭제)는 s10 묶음→WS 어댑터
  (`app.trash.dependencies.ws_role_for_bundle`)로 묶음 루트 문서 id → workspace_id 를 매핑해
  s01 판정에 위임한다. 경로 파라미터 이름은 `bundleId` 여야 어댑터가 바인딩한다. 묶음 문서
  부재 시 어댑터가 판정에 앞서 404 를 낸다.
- 세 경로 모두 MEMBER 최소 role. 비멤버→403(INV-2), admin→bypass(INV-3).

위계 비교·admin bypass·403 판정은 전부 s01 resolver 소유이며(재구현 없음) 미인증(세션 없음·
무효)은 `get_current_user` 가 401 을 산출한다. 스키마 형식 검증 실패(페이지네이션)는 pydantic
이 422 로 처리하며 s01 전역 핸들러가 공통 `ErrorResponse` 로 직렬화한다. 유효하지 않은 묶음
루트(존재하지 않거나 trashed 묶음 루트 아님)는 서비스/엔진의 `DomainError(NOT_FOUND)` 가 404
로 표면화하고 전역 핸들러가 직렬화한다.

경계(design.md §File Structure): 이 모듈은 s01 `common`·`schemas.base` 와 s10 `service`·
`schemas`·`dependencies`·`repository`, s07 `app.document.engine`·`app.document.repository`,
s05 `app.workspace.dependencies` 만 import 하며 다른 feature·main 을 import 하지 않는다.
라우터는 status/trashed_at 을 직접 쓰지 않고 게이팅을 재구현하지 않는다(어댑터·resolver
재사용). s01 조립 지점 등록(`include_router`)은 task 3.3 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.db import get_db
from app.document.engine import DocumentStateEngine
from app.document.repository import DocumentRepository
from app.schemas.base import Page
from app.trash.dependencies import Role, ws_role_for_bundle
from app.trash.repository import TrashRepository
from app.trash.schemas import TrashBundleRead
from app.trash.service import TrashService
from app.workspace.dependencies import require_ws_role

__all__ = [
    "router",
    "get_trash_service",
]

router = APIRouter()

_PURGE_DESCRIPTION = (
    "휴지통 묶음을 즉시 완전삭제한다 — 묶음 전체를 deleted(종착)로 전환한다. "
    "이 조작은 **되돌릴 수 없는** 파괴적 조작이며 deleted 는 복원 경로가 없는 종착 "
    "상태다(Req 3.3·INV-7). 삭제 전 사용자 확인 절차는 프론트엔드 UX 계약이며(Req 3.4) "
    "백엔드는 요청 본문 없이 이 비가역성만 표기한다. member 이상만 허용된다."
)


def get_trash_service() -> TrashService:
    """TrashService 를 조립하는 의존성 provider.

    s10 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는
    세션 없이 엔진·저장소만 결선한다. 엔진은 s07 `DocumentStateEngine(DocumentRepository())`,
    저장소는 s10 `TrashRepository()` 이며 생성자 순서는 `(engine, repository)` 다. 테스트는
    ``app.dependency_overrides[get_trash_service]`` 로 이 provider 를 대체해 DB 없이 라우터
    결선만 검증할 수 있다.
    """
    return TrashService(
        DocumentStateEngine(DocumentRepository()), TrashRepository()
    )


@router.get("/workspaces/{id}/trash", response_model=Page[TrashBundleRead])
def list_trash(
    id: int,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_ws_role(Role.MEMBER)),
    service: TrashService = Depends(get_trash_service),
) -> Page[TrashBundleRead]:
    """워크스페이스 휴지통의 trashed 묶음 목록을 페이지로 조회한다 (Req 1.1·1.7, member 이상).

    s05 `{id}`→workspace_id 브리지(`require_ws_role(MEMBER)`)로 게이트를 강제한다(viewer/
    비멤버→403, admin→bypass, 미인증→401 판정은 s01 소유). 경로 `{id}` 를 그대로 서비스
    `list_trash` 의 workspace_id 로 넘기고 `limit`(기본 50)·`offset`(기본 0) 쿼리 파라미터를
    전달한다. 이 조회는 요청자 컨텍스트를 쓰지 않으므로 게이트 값은 `_ctx` 로 바인딩만 한다.
    성공 시 200 + ``Page[TrashBundleRead]``(각 묶음 루트·구성원 요약·trashed_at·만료 예정).
    """
    return service.list_trash(db, workspace_id=id, limit=limit, offset=offset)


@router.post(
    "/trash/{bundleId}/restore", status_code=status.HTTP_204_NO_CONTENT
)
def restore_bundle(
    bundleId: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(ws_role_for_bundle(Role.MEMBER)),
    service: TrashService = Depends(get_trash_service),
) -> None:
    """휴지통 묶음을 복구해 묶음 전체를 active 로 되돌린다 (Req 2.1·2.5, member 이상).

    s10 묶음→WS 어댑터(`ws_role_for_bundle(MEMBER)`)로 묶음 루트 문서 id → workspace_id 를
    매핑해 게이트를 강제한다(묶음 문서 부재→404, 비멤버→403, admin→bypass 판정은 s01
    소유). 복구 위치·순서 규칙은 엔진이 결정하며 라우터는 묶음 루트(`bundleId`)를 서비스에
    위임만 한다. 유효하지 않은 묶음 루트→404 는 서비스/엔진이 표면화한다. 이 조작은 요청자
    컨텍스트를 쓰지 않으므로 게이트 값은 `_ctx` 로 바인딩만 한다. 성공 시 본문 없이 204.
    """
    service.restore(db, bundleId)


@router.delete(
    "/trash/{bundleId}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=_PURGE_DESCRIPTION,
)
def purge_bundle(
    bundleId: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(ws_role_for_bundle(Role.MEMBER)),
    service: TrashService = Depends(get_trash_service),
) -> None:
    """휴지통 묶음을 즉시 완전삭제해 묶음 전체를 deleted(종착)로 전환한다 (Req 3.1·3.6, member 이상).

    s10 묶음→WS 어댑터(`ws_role_for_bundle(MEMBER)`)로 게이트를 강제한다(묶음 문서 부재→404,
    비멤버→403, admin→bypass 판정은 s01 소유). 물리 삭제 없이 상태 전환만 수행하며
    상태 전이는 엔진 소관이므로 라우터는 묶음 루트(`bundleId`)를 서비스에 위임만 한다.
    유효하지 않은 묶음 루트→404 는 서비스/엔진이 표면화한다. **되돌릴 수 없는** 파괴적
    조작이며 사용자 확인 절차는 프론트엔드 UX 계약이다(OpenAPI 설명에 비가역성 표기, Req 3.4).
    이 조작은 요청자 컨텍스트를 쓰지 않으므로 게이트 값은 `_ctx` 로 바인딩만 한다. 성공 시
    본문 없이 204.
    """
    service.purge(db, bundleId)
