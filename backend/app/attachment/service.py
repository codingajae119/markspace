"""첨부 유스케이스 오케스트레이션 — `AttachmentService`
(design.md §Components and Interfaces #AttachmentService, Feature/Service).

첨부 업로드(이미지 붙여넣기·파일 첨부)와 조회 서빙(보관 시 404)을 저장 어댑터·리포지토리·
s07 문서→WS 조회 위임으로 오케스트레이션하는 얇은 서비스다. 상태 전이·버전 생성·아카이브
판정은 소유하지 않으며(각각 s07/s09, 조정은 `ArchivalSweepService`), 첨부의 저장·기록·응답
구성만 담당한다.

이 태스크(2.1)는 **업로드**(`upload_attachment`)만 구현한다. 서빙(`serve_attachment`)은 후속
태스크(2.2)가 같은 클래스에 추가한다.

경계(design.md §Dependency Direction): 저장 어댑터(`AttachmentStorage`)·리포지토리
(`AttachmentRepository`)·s07 `DocumentRepository` 는 생성자 주입하고 DB 세션은 메서드별 인자로
전달받는다(`app/trash/service.py`·`app/document/service.py` 주입 규약과 정합). s09/s10/s14 를
import 하지 않으며 라우터를 import 하지 않는다. 소속 `workspace_id` 는 클라이언트 입력이 아니라
대상 문서에서 확정한다(8.3·Req 3.2). 첨부 물리 삭제 없음(INV-4).

설정 접근은 s01 단일 Settings(`get_settings`) 경유이며, 테스트가 크기 한도를 격리할 수 있도록
`get_settings` 를 모듈 속성으로 참조한다(`app/trash/scheduler.py` 패턴).
"""

from __future__ import annotations

from typing import BinaryIO

from sqlalchemy.orm import Session

from app.attachment.repository import AttachmentRepository
from app.attachment.schemas import AttachmentKind, AttachmentRead
from app.attachment.storage import AttachmentStorage
from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.config import get_settings
from app.document.repository import DocumentRepository

__all__ = ["AttachmentService"]


class AttachmentService:
    """첨부 업로드·서빙 유스케이스 오케스트레이션(Req 1.1~1.5, 2.1·2.2·2.5, 3.2·3.3, 6.2).

    저장 어댑터·리포지토리·s07 문서 리포지토리를 생성자 주입하고 DB 세션은 메서드별 인자로
    전달받는다. 소속 `workspace_id` 는 대상 문서에서 확정하며(클라이언트 입력 아님, 8.3), 상태
    전이·버전 생성·아카이브 판정은 하지 않는다. 이 태스크는 `upload_attachment` 만 소유하고
    서빙은 후속 태스크가 추가한다.
    """

    def __init__(
        self,
        *,
        storage: AttachmentStorage | None = None,
        repository: AttachmentRepository | None = None,
        document_repository: DocumentRepository | None = None,
    ) -> None:
        self._storage = storage or AttachmentStorage()
        self._repository = repository or AttachmentRepository()
        self._documents = document_repository or DocumentRepository()

    def upload_attachment(
        self,
        db: Session,
        ctx: AuthContext,
        document_id: int,
        *,
        kind: AttachmentKind | None,
        upload_filename: str,
        stream: BinaryIO,
        size: int,
    ) -> AttachmentRead:
        """업로드 스트림을 파일로 저장하고 첨부 레코드를 생성해 참조 응답을 반환한다
        (design.md §System Flows 첨부 생성, Req 1.1~1.3·1.5·2.1·2.2·2.5·3.2).

        판정 순서는 flowchart 를 그대로 따른다:

        1. **문서 존재 확인 + WS 확정**: 소속 `workspace_id` 를 클라이언트 입력이 아니라 대상
           문서에서 확정한다(8.3·Req 3.2). s07 `DocumentRepository.get_workspace_id` 로 조회하며
           문서가 없으면(스칼라 None) 404 로 거부한다(Req 1.5).
        2. **크기 한도**: 업로드 크기가 `attachment_max_bytes` 를 초과하면 도메인 규칙 위반으로
           422 거부한다(Req 2.5). 저장 이전에 판정해 초과분을 디스크에 쓰지 않는다.
        3. **kind 확정**: 전달된 `kind` 를 그대로 기록하되, 미지정(None)이면 방어적 기본값 FILE
           로 둔다. content-type 기반 image/file 추론은 라우터(상위 태스크) 소관이며 여기서는
           주어진 종류를 충실히 기록만 한다.
        4. **파일 저장**: `AttachmentStorage.save` 로 WS 격리 위치에 파일로 저장한다(붙여넣기
           이미지도 base64 인라인이 아닌 파일, Req 1.2·2.1). 저장 파일명은 어댑터가 서버 생성하고
           원본명은 DB 에만 보존된다.
        5. **레코드 생성**: `AttachmentRepository.insert` 로 `workspace_id`·`document_id`·
           `file_path`·원본명(`original_name`)·kind 를 `is_archived=False` 로 기록한다
           (Req 1.3·2.2·3.2).
        6. **응답 구성**: `AttachmentRead.from_attachment` 로 `url`(`/attachments/{id}`) 을 산정한
           응답을 반환한다(Req 1.4, 단일 read-model 생성 경로).

        상태 전이·버전 생성·아카이브 판정은 하지 않으며 물리 삭제도 하지 않는다(INV-4). `ctx`
        는 라우터 권한 게이트 이후 전달되는 인증 컨텍스트로, attachment 스키마에 작성자 컬럼이
        없어 본 메서드에서 저장에 사용하지 않는다(계약 시그니처 정합용).
        """
        # 1. 문서에서 workspace_id 확정(클라이언트 입력 아님). 미존재 → 404.
        workspace_id = self._documents.get_workspace_id(db, document_id)
        if workspace_id is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="첨부 대상 문서를 찾을 수 없습니다",
                http_status=404,
            )

        # 2. 크기 한도 초과 → 422(도메인 규칙 위반). 저장 이전에 거부.
        if size > get_settings().attachment_max_bytes:
            raise DomainError(
                code=ErrorCode.UNPROCESSABLE,
                message="업로드 크기가 허용 한도를 초과했습니다",
                http_status=422,
            )

        # 3. kind 확정(미지정 시 방어적 기본값 FILE). content-type 추론은 라우터 소관.
        kind_value = kind if kind is not None else AttachmentKind.FILE

        # 4. WS 격리 위치에 파일로 저장(붙여넣기 이미지도 파일). 저장 상대 경로를 얻는다.
        file_path = self._storage.save(
            workspace_id=workspace_id,
            upload_filename=upload_filename,
            stream=stream,
        )

        # 5. 첨부 레코드 생성(is_archived=False, 원본명 보존, WS/문서 연결).
        att = self._repository.insert(
            db,
            workspace_id=workspace_id,
            document_id=document_id,
            file_path=file_path,
            original_name=upload_filename,
            kind=kind_value.value,
        )

        # 6. url(/attachments/{id}) 을 산정한 응답 구성(단일 생성 경로).
        return AttachmentRead.from_attachment(att)
