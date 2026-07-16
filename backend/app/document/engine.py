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
from decimal import Decimal

from sqlalchemy.orm import Session

from app.common.errors import DomainError, ErrorCode
from app.document.repository import DocumentRepository
from app.models import Document

__all__ = ["Bundle", "DocumentStateEngine"]

# 문서 "휴지통" 상태 값(s01 document.status ENUM). 묶음 식별·재구성이 소비한다.
_TRASHED = "trashed"

# 문서 "살아있는" 상태 값. 삭제 캐스케이드의 대상 자격(비active 거부) 판정이 소비한다.
_ACTIVE = "active"

# 복구 시 root append 폴백의 sort_order 규약. service._SORT_ORDER_START/STEP 와 동일한 값·
# 의미(형제 없으면 결정적 시작값, 있으면 마지막 형제 뒤 고정 step)를 엔진 안에서 미러링한다
# (경계상 service 를 import 하지 않으므로 상수를 복제; DECIMAL(30,15) 이라 Decimal 로 계산).
_SORT_ORDER_START = Decimal("1000")
_SORT_ORDER_STEP = Decimal("1000")


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

    def restore_bundle(
        self, db: Session, root_document_id: int
    ) -> list[Document]:
        """trashed 묶음을 active 로 되돌린다 — 복귀 위치·순서 결정 primitive
        (design.md §DocumentStateEngine 복구·복구 primitive 위치·순서, Req 7.1~7.7·9.2).

        `get_bundle` 으로 구성원을 확정·검증한다(유효하지 않은 루트면 그 검증이 404 를 던진다).
        복귀 위치는 **복구 시점 루트의 부모 상태**로 1회 검사해 결정한다(Req 7.1·7.2):

        - 부모가 존재하고 active 이면 부모 밑으로 복귀시키고 부모 참조(parent_id)를 유지하며,
          보존된 원래 `sort_order` 를 원위치 복원한다. 그 위치가 생존 active 형제와 충돌하면
          `_resolve_restore_sort_order` 의 폴백 계단(원래 직전·직후 형제 사이 중간값 → 한쪽만
          잔존 시 그 형제 기준 근사 → 맨 뒤)으로 재삽입한다(Req 7.3).
        - 부모가 non-active(trashed·deleted) 이거나 부재(parent_id=None) 이면 root 로 복귀시켜
          parent_id 를 NULL 로 만들고, 원위치 복원 대신 root 레벨 생존 active 형제 맨 뒤에
          배치한다(Req 7.2·7.4).

        구성원 전체를 status=active·trashed_at=NULL 로 전환하되(Req 7.7), 재삽입은 **루트만**
        수행하므로 구성원 내부의 상대 계층(각 구성원의 parent_id/sort_order)은 그대로 유지된다.
        자동 재중첩은 하지 않는다 — root 로 복구된 자식은 이후 부모가 복구돼도 스스로 재중첩되지
        않는다(이 primitive 는 복구 대상 묶음의 trashed 자식만 훑고 다른 묶음을 건드리지 않으므로,
        Req 7.5). 독립 묶음은 단독 복구 가능하며 다른 묶음을 함께 되살리지 않는다(Req 7.6).

        원자성(INV-10): 루트의 parent_id/sort_order 를 세션 추적 ORM 객체 위에서 **먼저 in-memory
        로 변경**한 뒤, 그 루트를 포함한 구성원 전체를 `repo.set_status_bulk` 로 단일 커밋
        전환한다. 루트의 위치 변경은 같은 세션의 pending 변경이라 그 단일 커밋에서 함께 flush
        되므로 위치 재배치와 상태 전이가 한 트랜잭션으로 원자 적용된다(별도 커밋 불필요).

        잠금과 무관하게 전이하며 lock 값은 읽지도 쓰지도 않는다(상태·잠금 독립, Req 9.4·9.5).
        반환 타입은 `list[Document]`(복구된 구성원)다 — `Bundle.trashed_at` 은 비옵셔널이라 NULL
        로 비운 뒤 Bundle 을 반환하면 타입 위반이므로, s10 이 소비할 구성원 목록을 그대로 준다.
        """
        bundle = self.get_bundle(db, root_document_id)
        members = bundle.members
        root = next(m for m in members if m.id == root_document_id)

        parent = None
        if root.parent_id is not None:
            parent = self._repository.get(db, root.parent_id)
        if parent is not None and parent.status == _ACTIVE:
            # 부모 밑 복귀: parent_id 유지, 원래 sort_order 원위치 복원(충돌 시 폴백).
            siblings = self._repository.list_siblings(
                db, root.workspace_id, root.parent_id, _ACTIVE
            )
            root.sort_order = self._resolve_restore_sort_order(
                siblings, root.sort_order
            )
        else:
            # root 복귀: parent_id=NULL, root 레벨 생존 active 형제 맨 뒤 append.
            root_siblings = self._repository.list_siblings(
                db, root.workspace_id, None, _ACTIVE
            )
            root.parent_id = None
            root.sort_order = (
                root_siblings[-1].sort_order + _SORT_ORDER_STEP
                if root_siblings
                else _SORT_ORDER_START
            )

        self._repository.set_status_bulk(
            db, members, status=_ACTIVE, trashed_at=None
        )
        return members

    def _resolve_restore_sort_order(
        self, siblings: list[Document], original: Decimal
    ) -> Decimal:
        """부모 밑 복귀 시 루트에 부여할 `sort_order` 를 원위치 복원·폴백 계단으로 계산한다
        (Req 7.3, service._resolve_move_sort_order 의 중간값 삽입 규약과 정합).

        `siblings` 는 대상 부모의 생존 active 형제(정렬 오름차순, 루트는 trashed 라 미포함),
        `original` 은 삭제 시 보존된 루트의 원래 sort_order 다.

        - 원래 위치에 충돌(동일 sort_order 형제)이 없으면 원래 값을 그대로 쓴다(원위치 복원).
        - 충돌하면 원래 값 기준 잔존 이웃으로 근사한다: 아래·위 잔존 이웃이 모두 있으면 그 둘
          사이 중간값(원래 직전·직후 형제 사이), 위쪽 잔존 이웃만 있으면(원래 위치가 목록 앞쪽)
          그 이웃 앞에 근사 배치한다. 위쪽 잔존 이웃이 없으면(원래 위치가 목록 맨 끝이거나 위쪽
          이웃이 모두 사라짐) 형제 맨 뒤에 append 한다.
        """
        if all(s.sort_order != original for s in siblings):
            return original
        lo = max(
            (s.sort_order for s in siblings if s.sort_order < original),
            default=None,
        )
        hi = min(
            (s.sort_order for s in siblings if s.sort_order > original),
            default=None,
        )
        if lo is not None and hi is not None:
            return (lo + hi) / Decimal(2)
        if hi is not None:
            return hi - _SORT_ORDER_STEP
        # 위쪽 잔존 이웃 없음 → 원래 위치가 목록 끝이므로 맨 뒤(최대 형제 뒤)로 append.
        return siblings[-1].sort_order + _SORT_ORDER_STEP

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
