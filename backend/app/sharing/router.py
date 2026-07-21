"""공유 라우터 — `SharingRouter` (design.md §Components and Interfaces #SharingRouter).

공유 4개 엔드포인트(s01 카탈로그 행 34~37)를 노출한다: `POST /documents/{id}/share`
(발급/재발급), `PATCH /documents/{id}/share`(토글), `GET /public/{token}`(공개 렌더),
`GET /public/{token}/attachments/{aid}`(링크 경유 첨부 서빙). 발급·토글은 member 이상으로
게이팅하고, 공개 렌더·첨부 서빙은 인증·권한 게이트 없이(공개) 노출한다. 라우터는 게이트 결선·
서비스 위임·상태코드/스트리밍 매핑만 담당한다 — 상태 전이·게이트 설정·첨부 저장은 서비스,
판정은 s01 resolver, 문서 → WS 매핑은 s07 어댑터에 위임한다(재구현 없음).

게이트 결선(design.md §SharingRouter 게이트):
- `POST /documents/{id}/share`(행 34)·`PATCH /documents/{id}/share`(행 35): s07 문서→WS 어댑터
  `ws_role_for_document(MEMBER)` 로 경로 문서 id → workspace_id 를 매핑해 s01 판정에 위임한다.
  경로 파라미터 이름이 `id`(문서 id)여야 어댑터가 바인딩하며, 문서 부재 시 어댑터가 판정에
  앞서 404 를 낸다(비멤버 403, admin bypass, 미인증 401). 게이트 off·비active 는
  서비스가 409 로 표면화한다(발급 불가/활성화 불가).
- `GET /public/{token}`(행 36)·`GET /public/{token}/attachments/{aid}`(행 37): **인증·권한
  게이트가 없다(공개)**. 접근 범위는 `PublicShareService` 가 토큰·게이트·문서 status·워크스페이스
  격리로만 제한하며 모든 무효/범위 밖/보관/부재를 404 로 통일한다(존재 추정 차단). 공개 렌더는
  읽기 전용 트리를, 첨부 서빙은 바이너리 스트림을 반환한다.

위계 비교·admin bypass·403 판정은 전부 s01 resolver 소유이며(재구현 없음) 미인증(세션 없음·
무효)은 `get_current_user` 가 401 을 산출한다. 문서 부재(404)·게이트 off/비active(409)·공개
경로 무효(404)는 서비스·어댑터가 `DomainError` 로 표면화하고 s01 전역 핸들러가 공통
`ErrorResponse` 로 직렬화한다. 라우터는 오류를 매핑하지 않는다.

경계(design.md §File Structure): 이 모듈은 s01 `common`(auth·db) 과 s14 `service`·
`public_service`·`schemas`, s07 `dependencies`(문서→WS 어댑터), s12 `AttachmentBinary`(스트림
응답 구성용 타입)만 import 하며 main 을 import 하지 않는다. s01 조립 지점 등록(`include_router`)
은 task 3.3 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.db import get_db
from app.document.dependencies import Role, ws_role_for_document
from app.sharing.public_service import PublicShareService
from app.sharing.schemas import (
    PublicDocumentRead,
    ShareLinkRead,
    ShareLinkUpdate,
)
from app.sharing.service import ShareLinkService

__all__ = [
    "router",
    "get_share_link_service",
    "get_public_share_service",
]

router = APIRouter()


def get_share_link_service() -> ShareLinkService:
    """ShareLinkService 를 조립하는 의존성 provider.

    s14 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는
    세션 없이 서비스를 생성한다(리포지토리·s07 문서 리포지토리는 서비스가 기본 조립한다).
    테스트는 ``app.dependency_overrides[get_share_link_service]`` 로 이 provider 를 대체해
    DB 없이 라우터 결선만 검증할 수 있다.
    """
    return ShareLinkService()


def get_public_share_service() -> PublicShareService:
    """PublicShareService 를 조립하는 의존성 provider.

    공개 렌더·링크 경유 첨부 서빙에 쓰이며, 세션 없이 서비스를 생성한다(리포지토리·s07
    primitive·s12 협력자는 서비스가 기본 조립한다). 테스트는
    ``app.dependency_overrides[get_public_share_service]`` 로 대체할 수 있다.
    """
    return PublicShareService()


@router.post("/documents/{id}/share", response_model=ShareLinkRead)
def issue_share_link(
    id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: ShareLinkService = Depends(get_share_link_service),
) -> ShareLinkRead:
    """문서 공유 링크를 발급/재발급한다 (Req 2.1·2.2·7.2·7.3, member 이상).

    s07 문서→WS 어댑터(`ws_role_for_document(MEMBER)`)로 경로 문서 id → workspace_id 를 매핑해
    게이트를 강제한다(문서 부재→404, 비멤버→403, admin bypass, 미인증→401 — 판정은 s01
    소유). 게이트 통과 후 `ShareLinkService.issue_link` 에 위임한다: 게이트 off·비active 문서는
    서비스가 409 로 거부하고, 통과 시 항상 **새 토큰의 활성 링크**를 발급/재발급한다(INV-8).
    문서당 링크는 최대 1개이므로 발급/재발급을 upsert 로 통일하기 위해 200 OK 를 쓴다(순수
    create 가 아님). 성공 시 :class:`ShareLinkRead`(share_url=`/public/{token}`).
    """
    return service.issue_link(db, ctx, document_id=id)


@router.patch("/documents/{id}/share", response_model=ShareLinkRead)
def toggle_share_link(
    id: int,
    payload: ShareLinkUpdate,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: ShareLinkService = Depends(get_share_link_service),
) -> ShareLinkRead:
    """문서 공유 링크 상태를 토글한다 — 토큰 유지 (Req 4.1·7.2·7.3, member 이상).

    발급과 동일한 s07 문서→WS 어댑터(`ws_role_for_document(MEMBER)`) 게이트를 강제한다(문서
    부재→404, 비멤버→403, admin bypass, 미인증→401). 게이트 통과 후 `ShareLinkService.
    toggle_link` 에 위임한다: 비활성화는 항상 허용, 활성화는 게이트 on·문서 active 일 때만
    허용하며(아니면 409) **토큰을 유지**한다(재발급 통일 원칙의 유일한 상태 기반 예외, INV-8).
    링크 부재는 서비스가 404 로 거부한다. 성공 시 :class:`ShareLinkRead`(200).
    """
    return service.toggle_link(db, document_id=id, payload=payload)


@router.get("/public/{token}", response_model=PublicDocumentRead)
def render_public_document(
    token: str,
    db: Session = Depends(get_db),
    service: PublicShareService = Depends(get_public_share_service),
) -> PublicDocumentRead:
    """공유 토큰으로 문서 + 현재 active 하위 트리를 공개 렌더한다 (Req 3.1·3.6·7.2·7.3, 공개).

    **인증·권한 게이트가 없다(공개)**. `PublicShareService.render_public_document` 에 위임하며,
    서비스가 토큰·게이트·문서 status·워크스페이스 격리로 접근 범위를 제한한다(실시간 공개
    유효성 관측 + lazy retire). 무효·미존재 토큰·문서 trashed·게이트 off 는 서비스가 사유를
    구분하지 않고 모두 404 로 통일한다(존재 추정 차단, Req 3.6). 성공 시 읽기 전용 중첩 트리
    :class:`PublicDocumentRead`(200).
    """
    return service.render_public_document(db, token)


@router.get(
    "/public/{token}/attachments/{aid}", response_class=StreamingResponse
)
def serve_public_attachment(
    token: str,
    aid: int,
    db: Session = Depends(get_db),
    service: PublicShareService = Depends(get_public_share_service),
) -> StreamingResponse:
    """공유 링크 경유로 첨부 바이너리를 공개 서빙한다 (Req 6.1·6.2·6.3·6.4·7.2·7.3, 공개).

    **인증·권한 게이트가 없다(공개)**. `PublicShareService.serve_public_attachment` 에 위임하며,
    서비스가 공개 렌더와 **동일한** 유효성 게이트(토큰·게이트·문서 status·워크스페이스 격리)로
    접근 범위를 제한하고 범위 밖·다른 WS·보관·부재 첨부를 모두 404 로 통일한다(존재 추정 차단).
    서비스가 돌려준 바이너리 값 객체로 `StreamingResponse` 를 구성해 스트리밍한다(원본명 기반
    content-type, inline Content-Disposition — s12 `serve_attachment` 응답 구성과 동일). 성공
    시 200 + 바이너리 스트림.
    """
    binary = service.serve_public_attachment(db, token, attachment_id=aid)
    return StreamingResponse(
        binary.stream,
        media_type=binary.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{binary.filename}"',
        },
    )
