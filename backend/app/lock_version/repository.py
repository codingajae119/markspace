"""LockVersionRepository — lock 필드·`document_version` 단일 데이터 접근점
(design.md §Components and Interfaces #LockVersionRepository).

일반/행 잠금(`FOR UPDATE`) 문서 로드, lock 필드 r/w(acquire·clear), 버전 insert·current
갱신, 버전 목록 조회를 소유한다. 충돌·멱등·보유자 판정은 Service 소유이며 여기서는 질의·
쓰기만 수행한다. 문서·버전 물리 삭제 없음(INV-4), status 무검사·무변경(§4.3).

계약 주의(design.md §DocumentRepository/workspace/admin_account 리포지토리 정합): 세션(`db`)은
메서드마다 인자로 전달받는다(생성자 주입 아님). **커밋 경계는 Service 소유**다 — 저장(save)·
start_edit·cancel·force_unlock 의 원자성(단일 트랜잭션)을 Service 가 통제하므로, 이 리포지토리의
mutator(`acquire_lock`·`clear_lock`·`set_current_version`)는 ORM 객체만 변이하고 **커밋하지
않는다**. `insert_version` 은 nullable 순환 FK(`current_version_id`)에 채울 새 id 를 확보하기
위해 **flush 만** 한다(커밋은 여전히 Service). (이는 s07 `DocumentRepository` 가 내부 커밋하는
것과 다르며, 저장 flow 의 단일 트랜잭션 원자성을 위해 의도적으로 커밋을 Service 로 미룬다.)

경계: s01(`app.models.Document`·`app.models.DocumentVersion`, sqlalchemy, stdlib)만 import 하며
다른 feature 도메인을 import 하지 않는다. s01 `common`·`models` 를 수정하지 않는다. 문서·버전은
INV-4 대상이므로 어떤 메서드도 물리 DELETE 를 발행하지 않는다(`document_version` 은 append-only).
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion

__all__ = ["LockVersionRepository"]


class LockVersionRepository:
    """lock 필드·`document_version` 의 단일 데이터 접근점(행 잠금 포함)
    (Req 1.1, 1.3, 1.4, 2.1, 2.2, 2.3, 3.1, 4.1, 5.1, 6.4).

    세션은 메서드별 인자로 전달받는다. 커밋 경계는 Service 소유이며(원자적 저장 트랜잭션),
    여기서는 질의·ORM 변이·필요 시 flush 만 수행한다. 잠금 판정 근거는 `lock_user_id` 단일
    컬럼(INV-9)이며 충돌·멱등·보유자 규칙은 Service 가 결정한다. status 무검사·무변경(§4.3).
    """

    def get(self, db: Session, document_id: int) -> Document | None:
        """PK 로 문서를 로드한다. 없으면 None 을 반환한다(Req 1.6 대상 로드)."""
        return db.get(Document, document_id)

    def get_for_update(self, db: Session, document_id: int) -> Document | None:
        """문서 행을 `SELECT ... FOR UPDATE` 행 잠금으로 로드한다. 없으면 None(Req 1.4).

        획득·저장·해제가 `lock_user_id` 재확인 후 원자적으로 갱신할 수 있도록 행을 잠근 채
        로드한다(동시 획득 경합에서 INV-9(최대 1인) 보장, research Risk). 행 잠금은 현재
        트랜잭션이 끝날 때(커밋/롤백) 해제되며, 트랜잭션 경계는 Service 가 통제한다.
        """
        return db.scalars(
            select(Document).where(Document.id == document_id).with_for_update()
        ).one_or_none()

    def acquire_lock(
        self, db: Session, doc: Document, *, user_id: int, at: datetime
    ) -> Document:
        """미잠금 문서에 잠금 보유자·획득 시각을 기록한다(Req 1.1).

        `lock_user_id`·`lock_acquired_at` 만 세팅하고 문서 `status` 는 검사·변경하지 않는다
        (§4.3). NULL 재확인(경합 안전)·멱등/충돌 판정은 Service 소유다. **커밋하지 않는다** —
        저장/시작 트랜잭션의 커밋 경계는 Service 가 통제한다(ORM 객체만 변이).
        """
        doc.lock_user_id = user_id
        doc.lock_acquired_at = at
        return doc

    def clear_lock(self, db: Session, doc: Document) -> Document:
        """문서의 잠금 필드를 NULL 로 되돌린다(Req 2.3·3.1·4.1).

        저장 완료·편집 취소·강제 해제의 잠금 해제 지점이다. `lock_user_id`·`lock_acquired_at`
        을 NULL 로 세팅하며 문서 `status` 는 검사·변경하지 않는다(§4.3). 새 버전을 만들지
        않는다(변경분 폐기). **커밋하지 않는다** — 커밋 경계는 Service 소유(ORM 객체만 변이).
        """
        doc.lock_user_id = None
        doc.lock_acquired_at = None
        return doc

    def insert_version(
        self,
        db: Session,
        *,
        document_id: int,
        content: str,
        created_by: int,
        at: datetime,
    ) -> DocumentVersion:
        """새 `document_version` 행을 만들고 flush 로 `.id` 를 확보한다(Req 2.1).

        저장 시 버전 스냅샷을 append 한다(무한 보관, append-only — INV-4·REQ-5.2). 순환 FK
        (`document.current_version_id`)에 채울 새 버전 id 가 즉시 필요하므로 **flush** 한다.
        **커밋하지 않는다** — 저장은 버전 insert·current 갱신·잠금 해제를 단일 트랜잭션으로
        원자 처리하며(REQ-2.4) 커밋 경계는 Service 소유다.
        """
        version = DocumentVersion(
            document_id=document_id,
            content=content,
            created_by=created_by,
            created_at=at,
        )
        db.add(version)
        db.flush()  # current_version_id 갱신에 쓸 새 id 확보(커밋은 Service).
        return version

    def set_current_version(
        self, db: Session, doc: Document, version_id: int
    ) -> Document:
        """문서의 `current_version_id` 를 새 버전 id 로 갱신한다(Req 2.2).

        `insert_version` 이 flush 로 확보한 id 를 동일 트랜잭션에서 설정한다. **커밋하지
        않는다** — 저장 트랜잭션의 커밋 경계는 Service 소유(ORM 객체만 변이).
        """
        doc.current_version_id = version_id
        return doc

    def list_versions(
        self, db: Session, document_id: int, limit: int, offset: int
    ) -> tuple[list[DocumentVersion], int]:
        """문서의 버전을 최신 저장 순 (items, total) 로 반환한다(Req 5.1·5.4).

        `total` 은 해당 문서의 전체 버전 개수이며 `limit`/`offset` 은 items 에만 적용한다.
        items 는 **최신 저장 순**으로 정렬한다: `document_version.created_at` 은 MySQL DATETIME
        (초 정밀도)이라 같은 초에 저장된 버전은 `created_at` 만으로 순서가 비결정적이므로
        `(created_at DESC, id DESC)` 로 정렬해 안정적 최신순을 보장한다.
        `(document_id, created_at)` 인덱스가 필터를 지원한다. 물리 삭제·수정 없음(append-only).
        """
        total = (
            db.scalar(
                select(func.count())
                .select_from(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
            )
            or 0
        )
        items = list(
            db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(
                    DocumentVersion.created_at.desc(),
                    DocumentVersion.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        return items, total
