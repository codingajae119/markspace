"""문서 데이터 접근 계층 — `DocumentRepository`
(design.md §Components and Interfaces #DocumentRepository).

document·document_version 질의와 계층/상태 조회의 단일 데이터 접근점이다. s01 document·
document_version 모델과 `get_db` 세션을 사용하며 문서는 INV-4 대상이라 물리 삭제 없이 상태
전환만 수행한다. 계층 질의(자식·active 하위·형제·부모), 상태 질의(WS active 목록·trashed
열거), 현재 버전 본문 로드, 삽입·부분 갱신·묶음 상태 일괄 전이·부모/정렬 갱신을 제공한다.

계약 주의(design.md §DocumentRepository, workspace/admin_account 리포지토리 정합): 세션(`db`)은
메서드마다 인자로 전달받는다(생성자 주입 아님). 쓰기 메서드(`insert`·`apply_updates`·
`set_status_bulk`·`set_parent_and_order`)는 commit 하여 별도 세션 재조회가 변경을 관찰하도록
내구 영속화한다. 상태 규칙(무엇을 묶음으로 볼지·복구 위치)은 엔진이 결정하고 여기서는 질의·
쓰기만 담당한다(Boundary). 버전은 **읽기만** 하며 생성하지 않는다(s09 소유).

경계: s01(`app.models.Document`·`app.models.DocumentVersion`, sqlalchemy, stdlib)만 import 하며
다른 feature 도메인을 import 하지 않는다. s01 `common`·`models` 를 수정하지 않는다. 문서는
INV-4 대상이므로 어떤 메서드도 물리 DELETE 를 발행하지 않는다(상태 전환만).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion

__all__ = ["DocumentRepository"]

# apply_updates 가 부분 갱신할 수 있는 필드 화이트리스트.
# 제목 등 메타데이터만 허용하며, 상태·계층·정렬은 전용 메서드(set_status_bulk·
# set_parent_and_order)로만 전환하여 예기치 않은 컬럼 변경을 차단한다.
_WRITABLE_FIELDS = frozenset({"title"})

# 문서의 "살아있는" 상태 값(s01 document.status ENUM). collect_active_descendants·계층
# 질의가 소비한다.
_ACTIVE = "active"


class DocumentRepository:
    """document·document_version 질의와 계층/상태 조회의 단일 데이터 접근점
    (Req 1.1, 1.2, 2.1, 2.4, 3.1, 4.1, 5.2, 5.3, 6.1, 6.5, 7.1, 8.1, 9.3).

    세션은 메서드별 인자로 전달받는다. 쓰기 메서드는 commit 으로 영속화한다. 문서는
    INV-4 대상이므로 물리 삭제 없이 상태 전환만 수행한다.
    """

    def get(self, db: Session, document_id: int) -> Document | None:
        """PK 로 문서를 로드한다. 없으면 None 을 반환한다(Req 2.1)."""
        return db.get(Document, document_id)

    def get_workspace_id(self, db: Session, document_id: int) -> int | None:
        """문서의 workspace_id 만 스칼라로 반환한다. 미존재 시 None(어댑터용, Req 4.1).

        DocumentWsAdapter 가 문서 id → workspace_id 로 매핑해 `require_ws_role` 에 주입하는
        경량 조회 지점이다(전체 행 로드 없이 컬럼만 질의).
        """
        return db.scalar(
            select(Document.workspace_id).where(Document.id == document_id)
        )

    def list_active_by_workspace(
        self, db: Session, workspace_id: int, limit: int, offset: int
    ) -> tuple[list[Document], int]:
        """워크스페이스의 active 문서를 (items, total) 로 반환한다(Req 3.1).

        `total` 은 active 전체 개수이며 `limit`/`offset` 은 items 에만 적용한다. items 는
        `sort_order` 오름차순(동률 시 `id`)으로 정렬한다. `(workspace_id, status, parent_id)`
        인덱스가 상태 필터를 지원한다.
        """
        conditions = (
            Document.workspace_id == workspace_id,
            Document.status == _ACTIVE,
        )
        total = (
            db.scalar(
                select(func.count()).select_from(Document).where(*conditions)
            )
            or 0
        )
        items = list(
            db.scalars(
                select(Document)
                .where(*conditions)
                .order_by(Document.sort_order, Document.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return items, total

    def list_children(
        self, db: Session, parent_id: int, status: str
    ) -> list[Document]:
        """주어진 status 의 직계 자식을 sort_order 순으로 반환한다(Req 1.2·2.4).

        `sort_order` 오름차순(동률 시 `id`)으로 정렬해 결정적 순서를 보장한다.
        """
        return list(
            db.scalars(
                select(Document)
                .where(Document.parent_id == parent_id, Document.status == status)
                .order_by(Document.sort_order, Document.id)
            )
        )

    def list_siblings(
        self,
        db: Session,
        workspace_id: int,
        parent_id: int | None,
        status: str,
    ) -> list[Document]:
        """같은 부모(루트면 parent_id IS NULL)의 형제를 정렬 순으로 반환한다(Req 4.1).

        이동/재정렬이 인접 형제의 `sort_order` 중간값을 계산하는 데 쓰는 정렬된 형제
        목록이다. `parent_id=None` 은 루트 레벨(`parent_id IS NULL`)을 뜻한다.
        """
        conditions = [
            Document.workspace_id == workspace_id,
            Document.status == status,
        ]
        if parent_id is None:
            conditions.append(Document.parent_id.is_(None))
        else:
            conditions.append(Document.parent_id == parent_id)
        return list(
            db.scalars(
                select(Document)
                .where(*conditions)
                .order_by(Document.sort_order, Document.id)
            )
        )

    def collect_active_descendants(
        self, db: Session, root: Document
    ) -> list[Document]:
        """root 포함, 재귀적으로 active 하위만 수집해 반환한다(Req 6.1·9.3).

        비흡수 삭제 캐스케이드가 그대로 소비하는 질의다. root 를 항상 포함하고, 각 노드의
        직계 자식 중 status=active 인 것만 계속 내려간다. trashed/deleted 자식은 그 서브트리
        째 제외한다(부모가 active여도 자식이 trashed면 그 자식·후손 전부 제외). 반복 BFS 로
        결정적 순서(레벨별 sort_order)를 보장한다.
        """
        result: list[Document] = [root]
        queue: list[Document] = [root]
        while queue:
            node = queue.pop(0)
            children = list(
                db.scalars(
                    select(Document)
                    .where(
                        Document.parent_id == node.id,
                        Document.status == _ACTIVE,
                    )
                    .order_by(Document.sort_order, Document.id)
                )
            )
            result.extend(children)
            queue.extend(children)
        return result

    def list_trashed_by_workspace(
        self, db: Session, workspace_id: int
    ) -> list[Document]:
        """워크스페이스의 trashed 문서를 열거한다(묶음 재구성용, Req 7.1·8.1).

        `(workspace_id, status, trashed_at)` 인덱스를 활용해 trashed 문서를 `trashed_at`
        (동률 시 `id`) 순으로 반환한다. 엔진이 공통 `trashed_at` 으로 묶음을 재구성한다.
        """
        return list(
            db.scalars(
                select(Document)
                .where(
                    Document.workspace_id == workspace_id,
                    Document.status == "trashed",
                )
                .order_by(Document.trashed_at, Document.id)
            )
        )

    def load_current_content(self, db: Session, doc: Document) -> str:
        """현재 버전 본문(markdown)을 반환한다. 없으면 빈 문자열(Req 2.1·2.4).

        `current_version_id` 가 None 이면 질의 없이 즉시 "" 를 반환한다. 있으면 해당
        document_version 의 content 를 로드하되, 방어적으로 행이 없거나 content 가 None 이면
        "" 를 반환한다. 버전은 읽기만 하며 생성하지 않는다(s09 소유).
        """
        if doc.current_version_id is None:
            return ""
        content = db.scalar(
            select(DocumentVersion.content).where(
                DocumentVersion.id == doc.current_version_id
            )
        )
        return content if content is not None else ""

    def insert(
        self,
        db: Session,
        *,
        workspace_id: int,
        parent_id: int | None,
        title: str,
        sort_order: Decimal,
        created_by: int,
    ) -> Document:
        """신규 active 문서를 생성하고 commit 하여 영속화한다(Req 1.1).

        status=active 로 강제하고 `created_at` 을 명시 설정한다(Document 모델에 created_at
        서버 기본값 없음). 초기 버전을 만들지 않으므로 `current_version_id` 는 NULL 로 남긴다
        (본문·버전 저장은 s09 소유). 부모 존재·active·동일 WS 검증과 sort_order 계산은
        서비스의 책임이며 리포지토리는 전달된 값을 그대로 저장한다.
        """
        doc = Document(
            workspace_id=workspace_id,
            parent_id=parent_id,
            title=title,
            status=_ACTIVE,
            sort_order=sort_order,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    def apply_updates(
        self, db: Session, doc: Document, changes: dict
    ) -> Document:
        """제공된 키만 부분 갱신하고 commit 하여 영속화한다(Req 3.1).

        갱신 가능 필드는 `title` 로 한정한다(메타데이터 부분 갱신). 화이트리스트 밖 키는
        무시하여 예기치 않은 컬럼 변경을 차단한다(상태·계층·정렬은 전용 메서드로만 전환).
        `updated_at` 을 설정한다. 본문·버전 갱신은 s09 에 위임한다.
        """
        for key, value in changes.items():
            if key in _WRITABLE_FIELDS:
                setattr(doc, key, value)
        doc.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(doc)
        return doc

    def set_status_bulk(
        self,
        db: Session,
        docs: list[Document],
        *,
        status: str,
        trashed_at: datetime | None,
    ) -> None:
        """전달된 docs 전체의 status·trashed_at 을 한 번에 세팅하고 단일 commit 한다(Req 5.2·6.1).

        묶음 상태 전이의 **원자적 적용 지점**이다(단일 트랜잭션/커밋 내에서 묶음 전체를
        전환). `trashed_at=None` 도 명시 세팅하므로 복구 시 NULL 복원에 그대로 쓴다. 무엇을
        묶음으로 볼지·복구 위치 결정은 엔진의 책임이며 여기서는 전달된 집합을 원자적으로
        전환만 한다. 물리 삭제는 발행하지 않는다(INV-4).
        """
        for doc in docs:
            doc.status = status
            doc.trashed_at = trashed_at
        db.commit()

    def set_parent_and_order(
        self,
        db: Session,
        doc: Document,
        *,
        parent_id: int | None,
        sort_order: Decimal,
    ) -> Document:
        """문서의 parent_id·sort_order 를 갱신하고 commit 하여 영속화한다(Req 4.1).

        이동/재정렬의 영속화 지점이다. 순환 방지(INV-5)·동일 WS(INV-6)·새 부모 존재·active
        검증과 중간값 sort_order 계산은 서비스의 책임이며 리포지토리는 전달된 값을 저장한다.
        `updated_at` 을 설정한다.
        """
        doc.parent_id = parent_id
        doc.sort_order = sort_order
        doc.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(doc)
        return doc
