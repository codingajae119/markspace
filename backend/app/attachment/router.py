"""첨부 라우터 — `AttachmentRouter` (design.md §Components and Interfaces #AttachmentRouter).

첨부 2개 엔드포인트(s01 카탈로그 행 32~33)를 노출한다: `POST /documents/{id}/attachments`
(업로드), `GET /attachments/{id}`(조회 서빙). 업로드는 member 이상, 조회는 활성 사용자 전역
개방(role 위임 없음, s26)으로 게이팅한다. 라우터는 multipart 수신·content-type 기반 kind 추론·게이트 결선·서비스 위임·
상태코드/스트리밍 매핑만 담당한다 — 로직은 서비스, 파일 I/O 는 스토리지, 판정은 s01 resolver,
문서/첨부 → WS 매핑은 어댑터에 위임한다(상태 전이·버전 생성·권한 위계 재구현 없음).

게이트 결선(design.md §AttachmentRouter 게이트, 두 System Flows):
- `POST /documents/{id}/attachments`(행 32): s07 문서→WS 어댑터
  `ws_role_for_document(MEMBER)` 로 경로 문서 id → workspace_id 를 매핑해 s01 판정에 위임한다.
  경로 파라미터 이름이 `id`(문서 id)여야 어댑터가 바인딩하며, 문서 부재 시 어댑터가 판정에
  앞서 404 를 낸다(비멤버 403, admin bypass). kind 미지정 시 업로드 content-type 으로
  image/file 을 추론한다(붙여넣기=image 경로 포함, task 2.1 에서 이연된 추론이 여기 산다).
- `GET /attachments/{id}`(행 33): s26 첨부 읽기 개방 게이트 `active_user_for_attachment` 로
  경로 첨부 id → workspace_id 를 매핑해 존재만 확인하고 활성 사용자면 통과시킨다(첨부
  부재→404, 미인증→401, role 위임 없음·403 부재 → 비멤버 활성 사용자도 200). 보관 첨부의
  role 무관 404 는 여전히 서비스가 권한 판정 이전에 처리하므로(8.10, 게이트 전환이 이
  불변식을 바꾸지 않음) 라우터는 별도 보관 처리를 두지 않는다. 성공 시 `StreamingResponse`(바이너리).

업로드 게이트의 위계 비교·admin bypass·403 판정은 전부 s01 resolver 소유이며(재구현 없음) 미인증(세션 없음·
무효)은 `get_current_user` 가 401 을 산출한다. 크기 초과(422)·대상 문서 부재(404)·첨부 부재/
보관(404)은 서비스·어댑터가 `DomainError` 로 표면화하고 s01 전역 핸들러가 공통 `ErrorResponse`
로 직렬화한다. 라우터는 오류를 매핑하지 않는다.

경계(design.md §File Structure): 이 모듈은 s01 `common`(auth·db) 과 s12 `service`·`schemas`·
`dependencies`, s07 `dependencies`(문서→WS 어댑터)만 import 하며 s09/s10/s14·main 을 import
하지 않는다. s01 조립 지점 등록(`include_router`)은 task 3.3 소유로 이 파일 범위 밖이다.
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.attachment.dependencies import Role, active_user_for_attachment
from app.attachment.schemas import AttachmentKind, AttachmentRead
from app.attachment.service import AttachmentService
from app.common.auth import AuthContext
from app.common.db import get_db
from app.common.http import content_disposition_inline
from app.document.dependencies import ws_role_for_document

__all__ = ["router", "get_attachment_service"]

router = APIRouter()


def get_attachment_service() -> AttachmentService:
    """AttachmentService 를 조립하는 의존성 provider.

    s12 계약상 DB 세션은 서비스 메서드별 인자로 전달되므로(생성자 주입 아님) provider 는
    세션 없이 서비스를 생성한다(저장 어댑터·리포지토리·s07 문서 리포지토리는 서비스가 기본
    조립한다). 테스트는 ``app.dependency_overrides[get_attachment_service]`` 로 이 provider 를
    대체해 DB 없이 라우터 결선만 검증할 수 있다.
    """
    return AttachmentService()


def _resolve_kind(kind: AttachmentKind | None, content_type: str | None) -> AttachmentKind:
    """kind 를 확정한다 — 명시 값이 있으면 그대로, 없으면 content-type 으로 추론한다.

    task 2.1 에서 이연된 content-type → kind 추론이 사는 지점이다(design.md #AttachmentSchemas
    kind 추론 노트). 명시 Form `kind` 가 있으면 추론보다 우선한다. 미지정 시 업로드
    content-type 이 `image/` 로 시작하면 IMAGE(붙여넣기 이미지 경로 포함), 그 외에는 FILE 로
    확정해 서비스에 넘긴다(서비스는 주어진 종류를 충실히 기록만 한다).
    """
    if kind is not None:
        return kind
    if content_type is not None and content_type.startswith("image/"):
        return AttachmentKind.IMAGE
    return AttachmentKind.FILE


def _measure_size(file: UploadFile) -> int:
    """업로드 크기를 산정한다 — `file.size` 를 우선하고, 없으면 스트림 길이로 폴백한다.

    Starlette 는 multipart 업로드에 대해 보통 `file.size` 를 채운다. None 인 예외적 경우에만
    저장용 스트림을 끝까지 이동해 길이를 재고 원위치로 되돌린다(디스크 저장 이전 측정).
    """
    if file.size is not None:
        return file.size
    stream = file.file
    stream.seek(0, 2)  # SEEK_END
    size = stream.tell()
    stream.seek(0)
    return size


@router.post(
    "/documents/{id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_attachment(
    id: int,
    file: UploadFile = File(...),
    kind: AttachmentKind | None = Form(None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentRead:
    """문서에 이미지(붙여넣기)·파일 첨부를 업로드한다 (Req 1.1·1.5·2.1·2.3·2.4·3.5, member 이상).

    s07 문서→WS 어댑터(`ws_role_for_document(MEMBER)`)로 경로 문서 id → workspace_id 를 매핑해
    게이트를 강제한다(문서 부재→404, 비멤버→403, admin bypass, 미인증→401 — 판정은 s01
    소유). multipart 로 파일 바이너리(`file`)와 선택 `kind` 를 수신하고, `kind` 미지정 시
    업로드 content-type 으로 image/file 을 추론한다(`_resolve_kind`, task 2.1 이연분). 소속
    workspace_id 확정·크기 한도(초과→422)·파일 저장·레코드 생성·url 산정은 서비스에 위임한다.
    성공 시 201 + :class:`AttachmentRead`(url=`/attachments/{id}`).
    """
    resolved_kind = _resolve_kind(kind, file.content_type)
    return service.upload_attachment(
        db,
        ctx,
        document_id=id,
        kind=resolved_kind,
        upload_filename=file.filename,
        stream=file.file,
        size=_measure_size(file),
    )


@router.get("/attachments/{id}", response_class=StreamingResponse)
def serve_attachment(
    id: int,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(active_user_for_attachment),
    service: AttachmentService = Depends(get_attachment_service),
) -> StreamingResponse:
    """첨부 바이너리를 스트리밍한다 — 보관 첨부는 role 무관 404 (Req 3.4·3.6·3.7·3.8·7.2, 활성 사용자 전역 개방).

    s26 첨부 읽기 개방 게이트(`active_user_for_attachment`)로 경로 첨부 id → workspace_id 를
    매핑해 존재만 확인하고 활성 사용자면 통과시킨다(첨부 부재→404, 미인증→401 — role 위임
    없음, 403 부재). 비멤버 활성 사용자도 존재하는 첨부를 200 으로 조회·다운로드한다(R3.4·
    R3.8). 보관(`is_archived`) 첨부는 **서비스가** 권한 판정 이전에 role 무관 404 로 차단하므로
    (admin 포함, 8.10) 게이트 전환은 이 불변식을 바꾸지 않으며 라우터도 별도 보관 처리를 두지
    않는다. 서비스가 돌려준 바이너리 값 객체로
    `StreamingResponse` 를 구성해 스트리밍한다(원본명 기반 content-type, 선택적 Content-Disposition).
    성공 시 200 + 바이너리 스트림.
    """
    binary = service.serve_attachment(db, attachment_id=id)
    return StreamingResponse(
        binary.stream,
        media_type=binary.content_type,
        headers={
            # 원본명이 한글 등 비-ASCII 여도 헤더 인코딩(latin-1)에서 500 이 나지 않도록
            # RFC 5987 로 안전 인코딩한다(app.common.http 단일 소유 헬퍼).
            "Content-Disposition": content_disposition_inline(binary.filename),
        },
    )
