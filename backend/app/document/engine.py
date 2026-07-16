"""문서 상태 전이 엔진 — `DocumentStateEngine`·`Bundle`
(design.md §Components and Interfaces #DocumentStateEngine).

삭제·복구·완전삭제·묶음 식별을 담는 **상태 전이 단일 구현**이다. active → trashed 삭제
캐스케이드(그 시점 active 하위만 포착·공통 trashed_at·이미 trashed 하위 제외, 비흡수),
trashed → active 복구 primitive(부모 상태 기준 복귀 위치·sort_order 원위치 복원·자동 재중첩
없음), trashed → deleted 완전삭제 primitive(묶음 단위 원자적 전이), 묶음 식별·열거(묶음 =
루트 문서 id), active 하위 집합 질의를 소유한다. 잠금과 무관하게 전이하며 lock 값은 설정하지
않는다(상태·잠금 독립).

이 모듈(task 3.1)은 묶음 식별·열거·active 하위 질의를 구현한다: `Bundle` DTO 와
`active_descendants`·`identify_bundles`·`get_bundle`. 삭제/복구/완전삭제 전이(trash·restore·
purge)는 후속 task 3.2~3.4 의 소유다. 엔진은 생성자로 `DocumentRepository` 를 주입받아 계층·
상태 질의를 위임하며, 상태 전이·묶음 규칙의 유일 소유자로서 s10/s14 가 이 primitive 를 호출만
하고 규칙을 재구현하지 않는다.

경계: `DocumentRepository`·s01 `common`(errors)·`models`·stdlib 만 import 하며 다른 feature
도메인(s09/s10/s14)을 import 하지 않는다. repository 를 수정하지 않고 기존 메서드
(`get`·`list_children`·`list_trashed_by_workspace`·`collect_active_descendants`)만 소비한다.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.errors import DomainError, ErrorCode
from app.document.repository import DocumentRepository
from app.models import Document

__all__ = ["Bundle", "DocumentStateEngine"]

# 문서 "휴지통" 상태 값(s01 document.status ENUM). 묶음 식별·재구성이 소비한다.
_TRASHED = "trashed"

# 문서 "살아있는" 상태 값. 삭제 캐스케이드의 대상 자격(비active 거부) 판정이 소비한다.
_ACTIVE = "active"


@dataclass(frozen=True)
class Bundle:
    """휴지통 묶음(bundle) — 한 번의 삭제가 포착한 서브트리(design.md §DocumentStateEngine).

    묶음은 별도 테이블/컬럼이 아니라 도메인 개념이며, **루트 문서 id** 로 식별하고
    `status=trashed` + 동일 `trashed_at` + `parent_id` 연결로 결정적으로 재구성된다.
    `members` 는 루트를 포함한 구성원이며 s10/s14 가 정렬·계층 재구성에 사용한다.
    """

    root_document_id: int
    trashed_at: datetime
    members: list[Document]  # 루트 포함 구성원


class DocumentStateEngine:
    """삭제·복구·완전삭제·묶음 식별을 담는 상태 전이 단일 구현(Req 5~9).

    이 task(3.1)는 묶음 식별·열거·active 하위 질의만 구현한다. 생성자로 주입된
    `DocumentRepository` 에 계층·상태 질의를 위임하고, 무엇을 묶음으로 볼지(루트 판정·구성원
    재구성 규칙)는 엔진이 결정한다.
    """

    def __init__(self, repository: DocumentRepository) -> None:
        self._repository = repository

    def active_descendants(
        self, db: Session, document: Document
    ) -> list[Document]:
        """특정 문서의 active 하위 집합(root 포함)을 반환한다(Req 9.3).

        `repo.collect_active_descendants` 에 위임한다. 삭제 캐스케이드(그 시점 active 하위만
        포착)와 s14 공유 렌더가 공용하는 **단일 계층 질의**로, root 를 포함하고 이미 trashed 된
        하위(그 서브트리째)는 제외한다.
        """
        return self._repository.collect_active_descendants(db, document)

    def trash_document(self, db: Session, document: Document) -> Bundle:
        """active 문서를 그 시점 active 하위(root 포함)와 함께 trashed 로 캐스케이드한다
        (design.md §DocumentStateEngine 삭제, Req 5.1~5.7·6.1~6.4·9.4).

        대상이 active 가 아니면 409(CONFLICT)로 거부한다(비active 삭제 금지, Req 5.7). active 면
        단일 공통 `trashed_at`(utcnow) 을 산정하고, `active_descendants`(=repo.
        collect_active_descendants) 로 **그 시점** active 하위(root 포함)만 포착한다. 이미 trashed
        된 하위는 이 질의가 서브트리째 자동 제외하므로 흡수되지 않는다(비흡수, Req 6.2·6.2.1).
        포착 구성원 전체를 `repo.set_status_bulk` 로 단일 트랜잭션에서 status=trashed·공통
        trashed_at 으로 전환한다(원자적, INV-10). 잠금과 무관하게 전이하며 lock 값은 읽지도 쓰지도
        않는다(상태·잠금 독립, Req 9.4·9.5). 반환 묶음의 루트는 대상 문서다.
        """
        if document.status != _ACTIVE:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message=(
                    f"Document {document.id} is not active "
                    "and cannot be trashed"
                ),
                http_status=409,
            )
        trashed_at = datetime.utcnow()
        members = self.active_descendants(db, document)
        self._repository.set_status_bulk(
            db, members, status=_TRASHED, trashed_at=trashed_at
        )
        return Bundle(
            root_document_id=document.id,
            trashed_at=trashed_at,
            members=members,
        )

    def identify_bundles(self, db: Session, workspace_id: int) -> list[Bundle]:
        """워크스페이스의 trashed 문서를 묶음으로 분할해 전체 열거한다(Req 6.5).

        `repo.list_trashed_by_workspace` 로 trashed 문서를 `trashed_at`(동률 시 `id`) 순으로
        얻어, 각 문서가 묶음 루트인지 판정한다. 각 trashed 문서는 정확히 한 번만 trashed 되므로
        묶음은 trashed 집합을 분할(partition)한다. 루트를 열거 순서대로 취해 구성원을
        재구성하며, 서로 다른 `trashed_at` 묶음은 병합되지 않는다(비흡수, INV-10·11).
        """
        trashed = self._repository.list_trashed_by_workspace(db, workspace_id)
        by_id = {doc.id: doc for doc in trashed}
        bundles: list[Bundle] = []
        for doc in trashed:
            if self._is_bundle_root(doc, by_id):
                members = self._reconstruct_members(db, doc)
                bundles.append(
                    Bundle(
                        root_document_id=doc.id,
                        trashed_at=doc.trashed_at,
                        members=members,
                    )
                )
        return bundles

    def get_bundle(self, db: Session, root_document_id: int) -> Bundle:
        """루트 문서 id 로 묶음 구성원을 확정·검증한다(Req 6.5).

        유효하지 않은 루트 — 문서 미존재, 비trashed, 또는 묶음 루트가 아님(부모가 같은
        trashed_at 으로 trashed 된 구성원) — 이면 404(NOT_FOUND)로 거부한다. 유효하면 루트에서
        동일 trashed_at 연결 서브트리를 결정적으로 재구성해 반환한다.
        """
        root = self._repository.get(db, root_document_id)
        if root is None or root.status != _TRASHED:
            raise self._not_found(root_document_id)
        # 루트 판정은 부모를 직접 로드해 확인한다(열거 경로와 동일 규칙).
        by_id: dict[int, Document] = {root.id: root}
        if root.parent_id is not None:
            parent = self._repository.get(db, root.parent_id)
            if parent is not None:
                by_id[parent.id] = parent
        if not self._is_bundle_root(root, by_id):
            raise self._not_found(root_document_id)
        members = self._reconstruct_members(db, root)
        return Bundle(
            root_document_id=root.id,
            trashed_at=root.trashed_at,
            members=members,
        )

    def _is_bundle_root(
        self, doc: Document, by_id: dict[int, Document]
    ) -> bool:
        """trashed 문서 `doc` 가 묶음 루트인지 판정한다(비흡수 핵심 불변식).

        루트 조건: (a) parent_id 가 None, (b) 부모가 trashed 가 아님(active/deleted/부재),
        (c) 부모가 trashed 지만 부모.trashed_at 이 doc 과 다름. 즉 부모가 trashed 이면서
        부모.trashed_at == doc.trashed_at 이면 doc 은 루트가 아니다(부모 묶음의 구성원).
        `by_id` 는 참조 가능한 trashed 문서(또는 부모) 조회용 맵이다. 맵에 부모가 없으면
        부모가 trashed 가 아닌 것으로 간주한다(조건 b).
        """
        if doc.parent_id is None:
            return True
        parent = by_id.get(doc.parent_id)
        if parent is None or parent.status != _TRASHED:
            return True
        return parent.trashed_at != doc.trashed_at

    def _reconstruct_members(
        self, db: Session, root: Document
    ) -> list[Document]:
        """루트에서 시작해 동일 trashed_at 연결 서브트리(구성원)를 결정적으로 재구성한다.

        루트를 포함하고, 각 구성원의 직계 trashed 자식(`repo.list_children(..., "trashed")`,
        sort_order 오름차순) 중 `trashed_at` 이 루트와 같은 것만 계속 내려간다. 방문 집합으로
        무한 루프를 방어하며, 다른 trashed_at 하위·비trashed 하위는 제외한다(비흡수).
        """
        members: list[Document] = []
        visited: set[int] = set()
        queue: list[Document] = [root]
        while queue:
            node = queue.pop(0)
            if node.id in visited:
                continue
            visited.add(node.id)
            members.append(node)
            children = self._repository.list_children(db, node.id, _TRASHED)
            for child in children:
                if child.id not in visited and child.trashed_at == root.trashed_at:
                    queue.append(child)
        return members

    def _not_found(self, root_document_id: int) -> DomainError:
        """유효하지 않은 묶음 루트에 대한 404 DomainError 를 생성한다."""
        return DomainError(
            code=ErrorCode.NOT_FOUND,
            message=f"Bundle root document {root_document_id} not found",
            http_status=404,
        )
