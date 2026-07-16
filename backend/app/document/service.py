"""문서 구조 서비스 — `DocumentService`
(design.md §Components and Interfaces #DocumentService).

문서 생성·조회·목록·제목 수정·이동/재정렬·렌더 오케스트레이션을 소유하며, 상태 전이는
`DocumentStateEngine` 에 위임한다(9.1). 생성 시 부모 존재·active·동일 WS 검증과 형제 마지막
순서 `sort_order` 부여(초기 버전 생성 없음), 조회 응답에 현재 버전 본문(`content`)과
`MarkdownRenderer` 렌더 결과(`content_html`) 포함, 제목 부분 갱신, 이동/재정렬(순환 방지
INV-5·동일 WS INV-6·두 형제 사이 중간값 삽입)을 담당한다. `DocumentRead` 구성은 스키마의
`from_document` 파생 필드 경로를 따른다.

생성·조회·목록(2.1)과 제목 부분 갱신(2.2, `update_document`)을 구현한다. 제목 수정은
title 메타데이터만 다루며 본문·버전 저장은 s09 에 위임한다(Req 3.4). 이동/재정렬과 상태
전이 위임(삭제 등)은 후속 task 의 소유이며, Service 는 active 구조만 다루고 상태 전이는
엔진만 수행한다(design.md Invariants).

경계(design.md §Dependency Direction): 서비스는 `DocumentRepository`·`MarkdownRenderer`
(생성자 주입)·s01 `common`·s07 `schemas` 만 소비하며 라우터·다른 feature 도메인
(s09/s10/s14)을 import 하지 않는다. DB 세션은 메서드별 인자로 전달받아 repo 로 넘긴다.
스키마 형식 검증(필수·공백)은 pydantic 이 라우터 계층에서 422 로 처리하므로 서비스는 도메인
판정(부모 부재 404·상태/WS 위반 409)만 담당한다.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.document.renderer import MarkdownRenderer
from app.document.repository import DocumentRepository
from app.document.schemas import (
    DocumentCreate,
    DocumentMoveRequest,
    DocumentRead,
    DocumentUpdate,
)
from app.models import Document
from app.schemas.base import Page

__all__ = ["DocumentService"]

# 문서의 "살아있는" 상태 값(s01 document.status ENUM). 부모 검증·형제 조회가 소비한다.
_ACTIVE = "active"

# 형제 sort_order 부여 규약: 형제가 없으면 결정적 시작값, 있으면 마지막(최대) 형제보다
# 고정 step 큰 값을 부여해 목록 끝에 위치시킨다(Req 1.5). DECIMAL(30,15) 컬럼이므로
# Decimal 로 계산한다.
_SORT_ORDER_START = Decimal("1000")
_SORT_ORDER_STEP = Decimal("1000")


class DocumentService:
    """문서 생성·조회·목록 비즈니스 로직
    (design.md §Components → DocumentService, Req 1.1~1.5, 2.1, 2.3, 2.4, 2.7).

    저장소·렌더러는 생성자 주입하고 DB 세션은 메서드별 인자로 전달받는다. 도메인 오류는
    s01 `DomainError` 로 raise 하며 s01 전역 핸들러가 공통 `ErrorResponse` 로 변환한다.
    """

    def __init__(
        self, repository: DocumentRepository, renderer: MarkdownRenderer
    ) -> None:
        self._repo = repository
        self._renderer = renderer

    def create_document(
        self,
        db: Session,
        ctx: AuthContext,
        workspace_id: int,
        payload: DocumentCreate,
    ) -> DocumentRead:
        """루트/하위 문서를 active 로 생성한다 (Req 1.1·1.2·1.3·1.4·1.5).

        `parent_id` 가 지정되면 부모가 존재(미존재→404)·동일 workspace_id(타 WS→409,
        INV-6)·active 상태(비active→409)인지 검증한다. 부모가 None 이면 루트다. 형제
        (같은 workspace_id + 같은 parent_id + active) 중 마지막 순서 뒤로 `sort_order` 를
        부여하고(형제 최대값 + 고정 step, 없으면 결정적 시작값), status=active·
        created_by=요청자로 삽입한다. **초기 버전을 만들지 않으므로** current_version_id 는
        NULL 로 남는다(본문·버전 저장은 s09 소유). 응답의 content 는 현재 버전 부재이므로
        빈 문자열, content_html 은 빈 본문의 안전 렌더 결과다.
        """
        if payload.parent_id is not None:
            parent = self._repo.get(db, payload.parent_id)
            if parent is None:
                raise DomainError(
                    code=ErrorCode.NOT_FOUND,
                    message="Parent document not found",
                    http_status=404,
                )
            # WS 경계 위반(INV-6): 부모가 다른 워크스페이스면 하위 문서를 만들 수 없다.
            if parent.workspace_id != workspace_id:
                raise DomainError(
                    code=ErrorCode.CONFLICT,
                    message="Parent document belongs to another workspace",
                    http_status=409,
                )
            # active 하위 구조에만 문서를 추가한다(비active 부모 아래 생성 금지).
            if parent.status != _ACTIVE:
                raise DomainError(
                    code=ErrorCode.CONFLICT,
                    message="Parent document is not active",
                    http_status=409,
                )

        sort_order = self._next_sort_order(db, workspace_id, payload.parent_id)
        document = self._repo.insert(
            db,
            workspace_id=workspace_id,
            parent_id=payload.parent_id,
            title=payload.title,
            sort_order=sort_order,
            created_by=ctx.user_id,
        )
        return self._to_read(db, document)

    def get_document(self, db: Session, document_id: int) -> DocumentRead:
        """문서 상세를 조회한다 — content·content_html 포함 (Req 2.1·2.3·2.4).

        대상을 로드해 없으면 404 로 거부한다(상태로 필터하지 않고 존재만 판정). 응답에는
        현재 버전 본문(`load_current_content`, 부재 시 "")과 `MarkdownRenderer` 안전 렌더
        결과를 함께 담는다. 권한 게이트(viewer 이상)는 라우터가 담당한다.
        """
        document = self._repo.get(db, document_id)
        if document is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Document not found",
                http_status=404,
            )
        return self._to_read(db, document)

    def list_documents(
        self, db: Session, workspace_id: int, limit: int, offset: int
    ) -> Page[DocumentRead]:
        """워크스페이스의 active 문서를 공통 `Page` 엔벨로프로 반환한다 (Req 2.1).

        `total` 은 저장소가 계산한 active 전체 개수를 그대로 전달한다. `DocumentRead` 는
        content/content_html 이 필수이므로 각 항목도 자기 현재 버전 기준으로 본문 로드·안전
        렌더해 채운다(정확성 우선). 권한 게이트(viewer 이상)는 라우터가 담당한다.
        """
        items, total = self._repo.list_active_by_workspace(
            db, workspace_id, limit, offset
        )
        return Page[DocumentRead](
            items=[self._to_read(db, doc) for doc in items],
            total=total,
        )

    def update_document(
        self, db: Session, document_id: int, changes: DocumentUpdate
    ) -> DocumentRead:
        """문서 제목을 부분 갱신한다 (Req 3.1·3.3·3.4).

        대상을 로드해 없으면 404 로 거부한다(Req 3.3). 명시적으로 제공된 필드만
        (`model_dump(exclude_unset=True)`) `apply_updates` 로 넘긴다 — 이 task 는 title 만
        다루며, 저장소가 `{"title"}` 화이트리스트로 안전 적용하므로 화이트리스트 밖 키는
        무시된다. 갱신된 문서를 현재 버전 본문·안전 렌더 HTML 과 함께 `DocumentRead` 로
        구성해 반환한다(공통 `_to_read` 경로 재사용).

        **본문 내용 저장·버전 생성은 이 경계에서 수행하지 않고 s09(lock-version)에 위임한다
        (Req 3.4).** 따라서 `content`·`current_version_id` 등 본문/버전 필드는 여기서 건드리지
        않는다(제목 메타데이터만 갱신). 권한 게이트(editor 이상)는 라우터가 담당한다.
        """
        document = self._repo.get(db, document_id)
        if document is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Document not found",
                http_status=404,
            )
        update_fields = changes.model_dump(exclude_unset=True)
        updated = self._repo.apply_updates(db, document, update_fields)
        return self._to_read(db, updated)

    def move_document(
        self, db: Session, document_id: int, payload: DocumentMoveRequest
    ) -> DocumentRead:
        """문서를 새 부모 밑으로 옮기거나 형제 사이 순서를 재정렬한다 (Req 4.1~4.5·4.7).

        대상을 로드해 없으면 404 로 거부하고, active 문서에만 이동을 허용한다(비active
        대상→409). `new_parent_id` 가 지정되면 새 부모가 존재(미존재→404)·동일 workspace_id
        (타 WS→409, INV-6)·active(비active→409)인지 검증하고, 새 부모에서 루트까지 parent_id
        체인을 거슬러 올라가며 대상 자신을 만나면 순환으로 판정해 거부한다(자기/후손 밑 이동
        금지, 409, INV-5·4.2·4.7). `new_parent_id` 가 None 이면 루트로 이동한다(parent_id=NULL).

        정렬 순서는 `before_sibling_id`/`after_sibling_id` 로 지정된 인접 형제 **사이**의
        중간값을 부여하며 다른 형제는 재배치하지 않는다(4.5). 형제 참조가 새 부모의 형제가
        아니거나 서로 모순되면 잘못된 이동 파라미터로 422 로 거부한다. 최종적으로
        `set_parent_and_order` 로 parent_id·sort_order 를 갱신하고 `DocumentRead` 로 반환한다.
        권한 게이트(editor 이상)는 라우터가 담당한다.
        """
        document = self._repo.get(db, document_id)
        if document is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Document not found",
                http_status=404,
            )
        # 이동은 active 구조에만 적용한다(trashed/deleted 는 휴지통 도메인 소유).
        if document.status != _ACTIVE:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="Only active documents can be moved",
                http_status=409,
            )

        new_parent_id = payload.new_parent_id
        if new_parent_id is not None:
            new_parent = self._repo.get(db, new_parent_id)
            if new_parent is None:
                raise DomainError(
                    code=ErrorCode.NOT_FOUND,
                    message="New parent document not found",
                    http_status=404,
                )
            # WS 경계 위반(INV-6): 새 부모가 다른 워크스페이스면 이동을 거부한다.
            if new_parent.workspace_id != document.workspace_id:
                raise DomainError(
                    code=ErrorCode.CONFLICT,
                    message="New parent belongs to another workspace",
                    http_status=409,
                )
            # active 하위 구조로만 이동한다(비active 새 부모 아래로 이동 금지, 4.4).
            if new_parent.status != _ACTIVE:
                raise DomainError(
                    code=ErrorCode.CONFLICT,
                    message="New parent document is not active",
                    http_status=409,
                )
            # 순환 방지(INV-5): 새 부모 조상 체인에 대상이 있으면 자기/후손 밑 이동이다.
            self._reject_cycle(db, document_id, new_parent)

        sort_order = self._resolve_move_sort_order(
            db, document, new_parent_id, payload
        )
        moved = self._repo.set_parent_and_order(
            db, document, parent_id=new_parent_id, sort_order=sort_order
        )
        return self._to_read(db, moved)

    def _reject_cycle(
        self, db: Session, document_id: int, new_parent: Document
    ) -> None:
        """새 부모에서 루트까지 조상 체인을 거슬러 올라가 대상을 만나면 거부한다(INV-5).

        `new_parent` 자신부터 시작해 `parent_id` 를 따라 루트까지 올라가며 각 노드가 대상
        (document_id)인지 확인한다. 대상을 만나면 자기 자신(new_parent==대상) 또는 후손 밑으로
        옮기려는 사이클이므로 409 로 거부한다. 방문 집합으로 기존 데이터의 사이클에 대한 무한
        루프도 방어한다.
        """
        node: Document | None = new_parent
        visited: set[int] = set()
        while node is not None:
            if node.id == document_id:
                raise DomainError(
                    code=ErrorCode.CONFLICT,
                    message="Cannot move a document under itself or its descendant",
                    http_status=409,
                )
            if node.id in visited:
                break
            visited.add(node.id)
            if node.parent_id is None:
                break
            node = self._repo.get(db, node.parent_id)

    def _resolve_move_sort_order(
        self,
        db: Session,
        document: Document,
        new_parent_id: int | None,
        payload: DocumentMoveRequest,
    ) -> Decimal:
        """중간 삽입 규약(4.5)에 따라 대상에 부여할 `sort_order` 를 계산한다.

        새 부모의 active 형제 목록(대상 자신 제외)을 정렬 순으로 얻고, 지정된
        `before_sibling_id`/`after_sibling_id` 로 삽입 지점의 하한(lo)·상한(hi) 이웃 순서를
        결정한다. 두 이웃 사이면 그 중간값을, 한쪽 끝이면 고정 step 만큼 밀어 배치한다(다른
        형제는 재배치하지 않는다). 참조가 새 부모의 형제가 아니거나 서로 모순되면(역순·비인접)
        422 로 거부한다.
        """
        siblings = self._repo.list_siblings(
            db, document.workspace_id, new_parent_id, _ACTIVE
        )
        others = [s for s in siblings if s.id != document.id]
        by_id = {s.id: s for s in others}

        before_id = payload.before_sibling_id
        after_id = payload.after_sibling_id
        if before_id is not None and before_id not in by_id:
            raise self._invalid_move("before_sibling_id is not a sibling")
        if after_id is not None and after_id not in by_id:
            raise self._invalid_move("after_sibling_id is not a sibling")

        lo, hi = self._insertion_bounds(others, by_id, before_id, after_id)
        if lo is not None and hi is not None:
            return (lo + hi) / Decimal(2)
        if lo is not None:
            return lo + _SORT_ORDER_STEP
        if hi is not None:
            return hi - _SORT_ORDER_STEP
        return _SORT_ORDER_START

    def _insertion_bounds(
        self,
        others: list[Document],
        by_id: dict[int, Document],
        before_id: int | None,
        after_id: int | None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """삽입 지점의 (하한, 상한) 이웃 `sort_order` 를 결정한다(None 이면 목록 끝/처음).

        - 두 참조 모두: `after` 바로 뒤가 `before` 여야 하며(인접), 아니면 422.
        - `after` 만: 그 형제 뒤·다음 형제 앞(끝이면 상한 None → append).
        - `before` 만: 그 형제 앞·이전 형제 뒤(처음이면 하한 None → prepend).
        - 참조 없음: 목록 마지막 뒤(append; 비면 하한·상한 모두 None → 시작값).
        """
        if before_id is not None and after_id is not None:
            after = by_id[after_id]
            before = by_id[before_id]
            if others.index(after) + 1 != others.index(before):
                raise self._invalid_move("sibling references are inconsistent")
            return after.sort_order, before.sort_order
        if after_id is not None:
            after = by_id[after_id]
            idx = others.index(after)
            hi = others[idx + 1].sort_order if idx + 1 < len(others) else None
            return after.sort_order, hi
        if before_id is not None:
            before = by_id[before_id]
            idx = others.index(before)
            lo = others[idx - 1].sort_order if idx - 1 >= 0 else None
            return lo, before.sort_order
        return (others[-1].sort_order if others else None), None

    def _invalid_move(self, message: str) -> DomainError:
        """잘못된 이동 파라미터를 나타내는 422 DomainError 를 만든다(design §Error Handling)."""
        return DomainError(
            code=ErrorCode.UNPROCESSABLE,
            message=message,
            http_status=422,
        )

    def _next_sort_order(
        self, db: Session, workspace_id: int, parent_id: int | None
    ) -> Decimal:
        """형제 마지막 순서 뒤에 놓일 `sort_order` 를 계산한다 (Req 1.5).

        형제(같은 workspace_id + 같은 parent_id + active)를 정렬 순으로 조회해 마지막(최대)
        형제보다 고정 step 큰 값을 반환한다. 형제가 없으면 결정적 시작값을 반환한다. repo 의
        `list_siblings` 는 sort_order 오름차순 정렬을 보장하므로 마지막 원소가 최대값이다.
        """
        siblings = self._repo.list_siblings(db, workspace_id, parent_id, _ACTIVE)
        if not siblings:
            return _SORT_ORDER_START
        return siblings[-1].sort_order + _SORT_ORDER_STEP

    def _to_read(self, db: Session, document: Document) -> DocumentRead:
        """ORM 문서를 현재 버전 본문·안전 렌더 HTML 과 함께 `DocumentRead` 로 구성한다.

        content/content_html 은 ORM 컬럼이 아닌 파생 필드이므로 스키마의 단일 구성 경로인
        `from_document` 로 함께 주입한다. content 는 현재 버전 markdown(부재 시 ""),
        content_html 은 그 안전 렌더 결과다.
        """
        content = self._repo.load_current_content(db, document)
        content_html = self._renderer.render(content)
        return DocumentRead.from_document(
            document, content=content, content_html=content_html
        )
