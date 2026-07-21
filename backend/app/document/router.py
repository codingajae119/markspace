"""문서 라우터 — `DocumentRouter` (design.md §Components and Interfaces #DocumentRouter).

문서 6개 엔드포인트(s01 카탈로그 행 18~23)를 노출한다: `POST/GET /workspaces/{id}/documents`,
`GET/PATCH/DELETE /documents/{id}`, `POST /documents/{id}/move`. 읽기(트리 목록·상세)는 role
위임 없는 활성 사용자 게이트로 **전역 개방**하고, 생성·수정·이동·삭제는 `require_ws_role(MEMBER)`
로 게이팅한다(admin bypass). `/workspaces/{id}/*` 는 경로 id=workspace_id, `/documents/{id}` 는
문서→WS 매핑으로 workspace_id 를 확정한다. DELETE 는 `DocumentStateEngine.trash_document` 를
호출한다. 라우터는 스키마 검증·게이트·서비스/엔진 위임만 담당한다.

게이트 결선(s26 읽기 개방 / design.md §읽기 게이트):
- `/workspaces/{workspace_id}/documents`(행 18·19): 경로 파라미터 이름을 `workspace_id` 로
  두어 게이트의 내부 의존성(경로 `workspace_id: int` 요구)이 직접 바인딩되게 한다("경로
  id=workspace_id"). 생성은 `require_ws_role(MEMBER)`, 목록은 공통 `require_active_workspace`
  (활성+WS 존재→404, role 없음 → 비멤버 200).
- `/documents/{id}`(행 20·21·22·23): 문서 id → workspace_id 매핑. 조회는 신규
  `active_user_for_document`(매핑 후 role 없이 활성 사용자만 요구, 부재 404 → 비멤버 200),
  수정·이동·삭제는 `ws_role_for_document(MEMBER)` 어댑터로 s01 판정에 위임한다.

위계 비교·admin bypass·403 판정은 전부 s01 resolver 소유이며(재구현 없음) 미인증(세션 없음·
무효)은 `get_current_user` 가 401 을 산출한다. 스키마 형식 검증 실패는 pydantic 이 422 로 처리
하며 s01 전역 핸들러가 공통 `ErrorResponse` 로 직렬화한다.

DELETE 오케스트레이션: 서비스가 아니라 엔진에 위임한다. 저장소 provider 로 대상 `Document`
ORM 객체를 로드하고(없으면 404), `DocumentStateEngine.trash_document`(비active→409) 를 호출한다.
Repository 는 의존 방향상 Router 좌측이라 라우터가 직접 조립·소비할 수 있다.

경계(design.md §File Structure): 이 모듈은 s01 `common`·`schemas.base` 와 s07 `service`·
`engine`·`repository`·`renderer`·`dependencies`·`schemas` 만 import 하며 다른 feature·main 을
import 하지 않는다. s01 조립 지점 등록(`include_router`)은 task 4.2 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode
from app.common.permissions import require_active_workspace, require_ws_role
from app.document.dependencies import Role, active_user_for_document, ws_role_for_document
from app.document.engine import DocumentStateEngine
from app.document.renderer import MarkdownRenderer
from app.document.repository import DocumentRepository
from app.document.schemas import (
    DocumentCreate,
    DocumentMoveRequest,
    DocumentRead,
    DocumentUpdate,
)
from app.document.service import DocumentService
from app.schemas.base import Page

__all__ = [
    "router",
    "get_document_service",
    "get_state_engine",
    "get_document_repository",
]

router = APIRouter()


def get_document_service() -> DocumentService:
    """DocumentService 를 조립하는 의존성 provider.

    s07 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는
    세션 없이 저장소·렌더러만 결선한다. 생성자 순서는 `(repository, renderer)` 다. 테스트는
    ``app.dependency_overrides[get_document_service]`` 로 이 provider 를 대체해 DB 없이
    라우터 결선만 검증할 수 있다.
    """
    return DocumentService(DocumentRepository(), MarkdownRenderer())


def get_state_engine() -> DocumentStateEngine:
    """DocumentStateEngine 를 조립하는 의존성 provider (DELETE 오케스트레이션용).

    엔진은 저장소를 생성자 주입받아 상태 전이(삭제 캐스케이드 등)를 수행한다. DELETE
    핸들러가 이 엔진의 `trash_document` 를 호출한다(서비스에 삭제 메서드를 두지 않음).
    """
    return DocumentStateEngine(DocumentRepository())


def get_document_repository() -> DocumentRepository:
    """DocumentRepository 를 조립하는 의존성 provider (DELETE 대상 로드용).

    DELETE 핸들러가 엔진 호출에 앞서 대상 `Document` ORM 객체를 로드하는 데 쓴다. Repository
    는 의존 방향상 Router 좌측이므로 라우터가 직접 소비하는 것이 허용된다.
    """
    return DocumentRepository()


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    workspace_id: int,
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_ws_role(Role.MEMBER)),
    service: DocumentService = Depends(get_document_service),
) -> DocumentRead:
    """루트/하위 문서를 생성한다 (Req 1.1·1.6·1.7·10.2, member 이상).

    `require_ws_role(MEMBER)` 로 게이트를 강제한다(위계 미달·비멤버 403, admin bypass, 미인증
    401 — 판정은 s01 소유). 경로 `workspace_id` 가 곧 대상 워크스페이스이며 게이트에 그대로
    바인딩된다. 게이트가 돌려준 컨텍스트(요청자)를 서비스에 넘겨 `created_by` 를 확정한다.
    부모 미존재→404·타 WS/비active 부모→409 는 서비스가, `title` 공백 등 스키마 검증 실패는
    pydantic 이 422 로 처리한다. 성공 시 201 + :class:`DocumentRead`.
    """
    return service.create_document(db, ctx, workspace_id, payload)


@router.get(
    "/workspaces/{workspace_id}/documents",
    response_model=Page[DocumentRead],
)
def list_documents(
    workspace_id: int,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(require_active_workspace),
    service: DocumentService = Depends(get_document_service),
) -> Page[DocumentRead]:
    """워크스페이스의 active 문서를 페이지네이션하여 조회한다 (Req 3.1·3.2·3.6·3.7·3.8·7.2, 활성 사용자 전역 개방).

    `require_active_workspace` 로 게이트를 강제한다: 활성 사용자(미인증·비활성 401)와 WS 존재
    (부재 404)만 요구하고 role 을 판정하지 않는다 — 비멤버 활성 사용자도 존재하는 WS 트리에
    403 없이 200 을 받는다(읽기 완화). 경로 `workspace_id` 가 게이트에 그대로 바인딩된다.
    `limit`(기본 50)·`offset`(기본 0) 쿼리 파라미터와 workspace_id 를 서비스로 전달한다.
    성공 시 200 + ``Page[DocumentRead]``.
    """
    return service.list_documents(db, workspace_id, limit, offset)


@router.get("/documents/{id}", response_model=DocumentRead)
def get_document(
    id: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(active_user_for_document),
    service: DocumentService = Depends(get_document_service),
) -> DocumentRead:
    """문서 상세를 조회한다 — content·content_html 포함 (Req 3.1·3.6·3.7·3.8·7.2, 활성 사용자 전역 개방).

    `active_user_for_document` 게이트로 문서 id → workspace_id 를 매핑한 뒤(문서 부재 404) role
    판정 없이 활성 사용자만 요구한다 — 비멤버 활성 사용자도 존재하는 문서에 403 없이 200 을
    받는다(읽기 완화). 미인증·비활성은 401. 성공 시 200 + :class:`DocumentRead`.
    """
    return service.get_document(db, id)


@router.patch("/documents/{id}", response_model=DocumentRead)
def update_document(
    id: int,
    changes: DocumentUpdate,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: DocumentService = Depends(get_document_service),
) -> DocumentRead:
    """문서 제목을 부분 갱신한다 (Req 3.1·3.2·10.3, member 이상).

    `ws_role_for_document(MEMBER)` 어댑터로 게이트를 강제한다(문서 부재→404, 403/401 판정은
    s01 소유). 본문·버전 저장은 s09 에 위임하며 여기서는 title 메타데이터만 다룬다. `title`
    공백 등 스키마 검증 실패는 pydantic 이 422 로 처리한다. 성공 시 200 + :class:`DocumentRead`.
    """
    return service.update_document(db, id, changes)


@router.post("/documents/{id}/move", response_model=DocumentRead)
def move_document(
    id: int,
    payload: DocumentMoveRequest,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: DocumentService = Depends(get_document_service),
) -> DocumentRead:
    """문서를 새 부모 밑으로 옮기거나 형제 사이 순서를 재정렬한다 (Req 4.1·4.6·10.3, member 이상).

    `ws_role_for_document(MEMBER)` 어댑터로 게이트를 강제한다(문서 부재→404, 403/401 판정은
    s01 소유). 비active 대상·순환·타 WS 부모→409, 잘못된 형제 참조→422 는 서비스가 처리한다.
    성공 시 200 + :class:`DocumentRead`.
    """
    return service.move_document(db, id, payload)


@router.delete("/documents/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    id: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    engine: DocumentStateEngine = Depends(get_state_engine),
    repository: DocumentRepository = Depends(get_document_repository),
) -> None:
    """문서를 그 시점 active 하위와 함께 trashed 로 캐스케이드한다 (Req 5.1·5.2·5.6·10.3·10.5, member 이상).

    `ws_role_for_document(MEMBER)` 어댑터로 게이트를 강제한다(문서 부재→404, 403/401 판정은
    s01 소유). 삭제는 서비스가 아니라 **엔진**에 위임한다: 저장소로 대상 `Document` 를 로드해
    (방어적으로 없으면 404) `DocumentStateEngine.trash_document` 를 호출한다 — 대상이 active 가
    아니면 엔진이 409 를 raise 한다(비active 삭제 금지). 성공 시 본문 없이 204 로 응답한다.
    """
    document = repository.get(db, id)
    if document is None:
        raise DomainError(
            code=ErrorCode.NOT_FOUND,
            message="Document not found",
            http_status=404,
        )
    engine.trash_document(db, document)
