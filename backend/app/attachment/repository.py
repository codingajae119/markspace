"""첨부 데이터 접근 계층 — `AttachmentRepository`
(design.md §Components and Interfaces #AttachmentRepository, Feature/Data).

attachment r/w 와 보관 조정에 필요한 문서 status·현재 버전 관측 질의의 단일 데이터 접근점이다.
s01 attachment·document·document_version 모델과 `get_db`/`SessionLocal` 세션을 사용하며, 첨부는
INV-4 대상이라 물리 삭제 없이 보관 표시(`is_archived`)와 보관 경로 갱신만 수행한다. 첨부 삽입·
단건 조회·보관 표시와 두 조정 스코프 질의(8.6 완전삭제 반응·8.7 참조 소멸)를 제공한다.

계약 주의(design.md §DocumentRepository/TrashRepository 리포지토리 정합): 세션(`db`)은 메서드마다
인자로 전달받는다(생성자 주입 아님). 쓰기 메서드(`insert`·`mark_archived`)는 commit 하여 별도
세션 재조회가 변경을 관찰하도록 내구 영속화한다(`SessionLocal` 은 `expire_on_commit=False`).
무엇을 언제 보관 이동할지·붙여넣기 보호 판정은 `ArchivalSweepService` 의 책임이며 여기서는
질의·쓰기만 담당한다(Boundary). **상태 전이·버전 생성은 하지 않는다(관측만).** 조정 스코프는
항상 `is_archived == False` 만 대상으로 하여 멱등하다.

경계: s01(`app.models.Attachment`·`Document`·`DocumentVersion`, sqlalchemy, stdlib)만 import 하며
s07/s09/s10/s14 를 import 하지 않는다. s01 `common`·`models` 를 수정하지 않는다. 첨부는 INV-4
대상이므로 어떤 메서드도 물리 DELETE 를 발행하지 않는다(보관 표시만).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attachment, Document, DocumentVersion

__all__ = ["AttachmentRepository"]

# 문서의 "완전삭제" 종착 상태(s01 document.status ENUM). 8.6 스코프 필터가 소비한다.
_DELETED = "deleted"

# 8.7 스코프 대상 문서 상태(완전삭제 전 살아있는 상태). deleted 는 8.6 소관이라 제외한다.
_LIVE_STATUSES = ("active", "trashed")

# 참조 소멸 아카이브(8.7)의 대상 첨부 종류(s01 attachment.kind ENUM). 일반 파일은 8.6 으로만
# 처리하므로 image 에 한정한다(REQ-5.6).
_IMAGE = "image"


class AttachmentRepository:
    """attachment r/w 와 조정 스코프 관측 질의의 단일 데이터 접근점
    (Req 1.3, 3.2, 4.1, 4.4, 4.5, 5.1, 5.5).

    세션은 메서드별 인자로 전달받는다. 쓰기 메서드는 commit 으로 영속화한다. 첨부는 INV-4
    대상이므로 물리 삭제 없이 보관 표시만 수행한다. 상태 전이·버전 생성은 하지 않는다(관측만).
    """

    def insert(
        self,
        db: Session,
        *,
        workspace_id: int,
        document_id: int,
        file_path: str,
        original_name: str,
        kind: str,
    ) -> Attachment:
        """신규 첨부를 `is_archived=False` 로 생성하고 commit 하여 영속화한다(Req 1.3·3.2).

        소속 `workspace_id` 는 대상 문서에서 확정된 값을 그대로 저장하며(클라이언트 입력 아님,
        8.3), `created_at` 을 명시 설정한다(Attachment 모델에 created_at 서버 기본값 없음).
        원본 파일명은 `original_name` 에 보존하고 디스크 파일명(`file_path`)과 분리한다. flush 로
        id 를 확정한 뒤 commit 하여 호출자가 커밋 후에도 `att.id` 를 사용할 수 있게 한다.
        """
        att = Attachment(
            workspace_id=workspace_id,
            document_id=document_id,
            file_path=file_path,
            original_name=original_name,
            kind=kind,
            is_archived=False,
            created_at=datetime.utcnow(),
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        return att

    def get(self, db: Session, attachment_id: int) -> Attachment | None:
        """PK 로 첨부를 로드한다. 없으면 None 을 반환한다(서빙·권한 어댑터용)."""
        return db.get(Attachment, attachment_id)

    def mark_archived(
        self, db: Session, att: Attachment, *, archived_path: str
    ) -> Attachment:
        """첨부의 `file_path` 를 보관 경로로 갱신하고 `is_archived=True` 로 표시한다(Req 4.1).

        보관 이동의 DB 상태 표시 지점이다. 물리 삭제는 하지 않으며(INV-4) 상태 전이·버전 생성도
        하지 않는다(관측만). 파일 이동 자체는 `AttachmentStorage.move_to_archive` 소관이고,
        여기서는 그 결과 보관 경로를 반영하고 보관 플래그만 뒤집는다. commit 하여 영속화한다.
        """
        att.file_path = archived_path
        att.is_archived = True
        db.commit()
        db.refresh(att)
        return att

    def list_unarchived_on_deleted_documents(
        self, db: Session
    ) -> list[Attachment]:
        """미보관이며 소속 문서가 deleted 인 첨부를 열거한다(8.6 스코프, Req 4.1·4.4·4.5).

        완전삭제 반응 보관 이동의 대상 열거다. `is_archived == False` 이고 소속 `document.status
        == 'deleted'` 인 첨부만 반환한다. 이미 보관된 첨부는 제외되어 멱등하다(재적용 무해). 문서
        상태 판정·전이는 하지 않고 s10/s07 이 만든 deleted 상태를 관측만 한다.
        """
        return list(
            db.scalars(
                select(Attachment)
                .join(Document, Attachment.document_id == Document.id)
                .where(
                    Attachment.is_archived.is_(False),
                    Document.status == _DELETED,
                )
                .order_by(Attachment.id)
            )
        )

    def list_unarchived_images_with_current_version(
        self, db: Session
    ) -> list[tuple[Attachment, int, datetime]]:
        """미보관 image·현재버전 존재 첨부와 그 현재 버전 메타를 열거한다(8.7 스코프, Req 5.1·5.5).

        참조 소멸 아카이브의 후보 열거다. `is_archived == False`, `kind == 'image'`, 소속 문서가
        active/trashed 이며 `current_version_id IS NOT NULL` 인 첨부와, 그 문서 현재 버전의
        `(id, created_at)` 를 `(att, current_version_id, current_version_created_at)` 튜플로
        반환한다. 현재 버전 본문은 여기서 로드하지 않으며(붙여넣기 보호·참조 판정은
        `ArchivalSweepService`·`ReferenceScanner` 소관), 현재 버전 메타만 관측 제공한다. deleted
        문서는 8.6 소관이므로 제외하고, 일반 파일(kind='file')과 보관된 첨부도 제외한다.
        """
        rows = db.execute(
            select(
                Attachment,
                DocumentVersion.id,
                DocumentVersion.created_at,
            )
            .join(Document, Attachment.document_id == Document.id)
            .join(
                DocumentVersion,
                Document.current_version_id == DocumentVersion.id,
            )
            .where(
                Attachment.is_archived.is_(False),
                Attachment.kind == _IMAGE,
                Document.status.in_(_LIVE_STATUSES),
                Document.current_version_id.is_not(None),
            )
            .order_by(Attachment.id)
        ).all()
        return [(att, ver_id, ver_created_at) for att, ver_id, ver_created_at in rows]
