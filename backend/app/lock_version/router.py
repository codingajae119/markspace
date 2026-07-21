"""LockVersionRouter — 잠금·버전 5개 엔드포인트 (카탈로그 행 24~28)
(design.md §Components and Interfaces #LockVersionRouter).

`POST /documents/{id}/lock`·`/save`·`/cancel`·`/force-unlock`·`GET /documents/{id}/versions`
를 노출한다. 모든 경로는 s07 문서→WS 어댑터(`ws_role_for_document`)로 게이팅되고 판정은
s01 resolver(`require_ws_role`)가 담당한다. 라우터는 스키마 검증·게이트·서비스 위임만 한다.

게이트 결선(design.md §LockVersionRouter 게이트):
- 모든 경로가 `/documents/{id}/*` 이므로 s07 어댑터 `ws_role_for_document(minimum)` 를
  통해 문서 id → workspace_id 를 매핑하고 s01 판정에 위임한다. 경로 파라미터 이름은 `id`
  (어댑터 내부 의존성이 경로 `id: int` 를 읽음)로 s07 `/documents/{id}` 라우트와 정확히
  맞춘다. 어댑터가 문서 부재 시 판정에 앞서 404 를 낸다.
- lock/save/cancel → MEMBER, force-unlock → OWNER.
- versions → 읽기 전역 개방(`active_user_for_document`): 문서 부재 404 매핑만 유지하고 role
  위임 없이 활성 사용자면 통과(비멤버 200). 미인증 401 은 `get_current_user` 소유.

위계 비교·admin bypass·403 판정은 전부 s01 resolver 소유이며(재구현 없음) 미인증(세션 없음·
무효)은 `get_current_user` 가 401 을 산출한다. 스키마 형식 검증 실패는 pydantic 이 422 로 처리
하며 s01 전역 핸들러가 공통 `ErrorResponse` 로 직렬화한다. 충돌(409)·서비스 not_found(404)는
서비스의 `DomainError` 가 산출하고 전역 핸들러가 직렬화한다.

경계(design.md §File Structure): 이 모듈은 s01 `common`·`schemas.base` 와 s09 `service`·
`schemas`·`repository`, 그리고 s07 `app.document.dependencies`(`ws_role_for_document`·`Role`)
만 import 하며 다른 feature·main 을 import 하지 않는다. s01 조립 지점 등록(`include_router`)은
task 3.2 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.db import get_db
from app.document.dependencies import (
    Role,
    active_user_for_document,
    ws_role_for_document,
)
from app.lock_version.repository import LockVersionRepository
from app.lock_version.schemas import (
    DocumentLockRead,
    DocumentSaveRequest,
    DocumentVersionRead,
)
from app.lock_version.service import LockVersionService
from app.schemas.base import Page

__all__ = [
    "router",
    "get_lock_version_service",
]

router = APIRouter()


def get_lock_version_service() -> LockVersionService:
    """LockVersionService 를 조립하는 의존성 provider.

    s09 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는
    세션 없이 저장소만 결선한다. 생성자 순서는 `(repository,)` 다. 테스트는
    ``app.dependency_overrides[get_lock_version_service]`` 로 이 provider 를 대체해 DB 없이
    라우터 결선만 검증할 수 있다.
    """
    return LockVersionService(LockVersionRepository())


@router.post("/documents/{id}/lock", response_model=DocumentLockRead)
def lock_document(
    id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: LockVersionService = Depends(get_lock_version_service),
) -> DocumentLockRead:
    """문서 편집 잠금을 획득하거나 멱등/충돌을 판정한다 (Req 1.1·1.5·1.6, member 이상).

    `ws_role_for_document(MEMBER)` 어댑터로 문서 id → workspace_id 를 매핑해 s01 판정에 위임
    한다(문서 부재→404, 403/401 판정은 s01 소유). 게이트가 돌려준 컨텍스트(요청자)를 서비스에
    넘겨 잠금 보유자를 확정한다. 타인 잠금→409 는 서비스가 처리한다. 성공 시 200 +
    :class:`DocumentLockRead`.
    """
    return service.start_edit(db, ctx, id)


@router.post("/documents/{id}/save", response_model=DocumentVersionRead)
def save_document(
    id: int,
    payload: DocumentSaveRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: LockVersionService = Depends(get_lock_version_service),
) -> DocumentVersionRead:
    """잠금 보유자의 본문을 저장한다 — 버전 생성·current 갱신·잠금 해제 (Req 2.1·2.5, member 이상).

    `ws_role_for_document(MEMBER)` 어댑터로 게이트를 강제한다(문서 부재→404, 403/401 판정은
    s01 소유). 게이트 컨텍스트와 요청 본문(`content`, 빈 문자열 허용)을 서비스에 넘긴다.
    비보유자·타인 잠금→409 는 서비스가, `content` 누락/형식 오류 등 스키마 검증 실패는 pydantic
    이 422 로 처리한다. 성공 시 200 + :class:`DocumentVersionRead`(본문 없는 버전 메타데이터).
    """
    return service.save(db, ctx, id, payload)


@router.post("/documents/{id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_edit(
    id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: LockVersionService = Depends(get_lock_version_service),
) -> None:
    """잠금 보유자의 편집을 취소한다 — 잠금 해제, 변경분 폐기 (Req 3.1·3.5, member 이상).

    `ws_role_for_document(MEMBER)` 어댑터로 게이트를 강제한다(문서 부재→404, 403/401 판정은
    s01 소유). 게이트 컨텍스트를 서비스에 넘긴다 — 미잠금은 멱등 no-op, 타인 잠금→409 는
    서비스가 처리한다. 버전을 만들지 않는다. 성공 시 본문 없이 204 로 응답한다.
    """
    service.cancel_edit(db, ctx, id)


@router.post("/documents/{id}/force-unlock", status_code=status.HTTP_204_NO_CONTENT)
def force_unlock(
    id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(ws_role_for_document(Role.OWNER)),
    service: LockVersionService = Depends(get_lock_version_service),
) -> None:
    """방치된 잠금을 보유자와 무관하게 강제 해제한다 (Req 4.1·4.2, owner 이상).

    `ws_role_for_document(OWNER)` 어댑터로 게이트를 강제한다(문서 부재→404, 403/401 판정은
    s01 소유). cancel 과 달리 OWNER 권한을 요구하며 서비스는 현재 보유자와 무관하게 잠금을
    해제한다(미잠금은 멱등 성공). 버전을 만들지 않는다. 성공 시 본문 없이 204 로 응답한다.
    """
    service.force_unlock(db, ctx, id)


@router.get("/documents/{id}/versions", response_model=Page[DocumentVersionRead])
def list_versions(
    id: int,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(active_user_for_document),
    service: LockVersionService = Depends(get_lock_version_service),
) -> Page[DocumentVersionRead]:
    """문서의 저장 버전 이력을 최신 저장 순 메타데이터 페이지로 조회한다 (Req 3.3·3.6·3.7·3.8·5.1·5.5).

    읽기 전역 개방: 멤버 게이트 대신 신규 문서 읽기 게이트 `active_user_for_document` 를
    부착한다(문서 상세 라우트와 공유, 신규 교차 import 없이 기존 document dependencies 재사용).
    이 게이트는 문서 id → workspace_id 매핑(부재→404)만 유지하고 role 위임을 제거하므로,
    활성 사용자면 멤버십과 무관하게 통과한다 — 비멤버 활성 사용자도 존재하는 문서에 200 을 받고
    (R3.8·R7.2), 미인증은 `get_current_user` 가 401 을 낸다. `limit`(기본 50)·`offset`(기본 0)
    쿼리 파라미터와 문서 id 를 서비스로 전달한다. 이 조회는 요청자 컨텍스트를 쓰지 않으므로
    게이트 값은 `_ctx` 로 바인딩만 한다. 성공 시 200 + ``Page[DocumentVersionRead]``(본문·
    rollback 미제공).
    """
    return service.list_versions(db, id, limit, offset)
