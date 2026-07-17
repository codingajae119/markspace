"""공개 읽기 전용 렌더 유스케이스 — `PublicShareService`
(design.md §Components and Interfaces #PublicShareService, Feature/Service).

토큰으로 공유 링크를 받아 **접근 시점의 현재 active 하위 계층**을 안전 HTML 로 읽기 전용
렌더해 반환하는 얇은 서비스다. 상태 전이·게이트 설정·안전 렌더 규약·첨부 저장/서빙을 소유하지
않고 s07(`DocumentStateEngine.active_descendants`·`DocumentRepository.load_current_content`·
`MarkdownRenderer`) primitive 를 재사용한다(Req 7.7). 공개 경로이므로 인증을 우회하되 접근 범위는
토큰·게이트·문서 status·워크스페이스 격리로만 제한한다(Req 7.3).

이 태스크(2.2)는 **공개 렌더**(`render_public_document`)만 구현한다. 링크 경유 첨부 서빙
(`serve_public_attachment`)은 후속 태스크(2.3)가 같은 클래스에 추가하며, 그 태스크가 공용
유효성 게이트(`_resolve_valid_link`)를 그대로 재사용할 수 있도록 helper 로 분리해 둔다.

핵심 규약(design.md §System Flows 공개 렌더, §Security):
- **공개 유효성(실시간 게이트)**: 토큰으로 링크 로드(부재→404). 유효 = `is_enabled` AND 문서
  status=active AND 워크스페이스 `is_shareable`. 접근마다 라이브로 관측한다.
- **lazy retire**: 무효 조건(문서 비active·게이트 off)을 관측했고 링크가 아직 활성이면 그 자리에서
  `ShareLinkRepository.retire`(비활성 + 토큰 교체)로 영구 무효화한 뒤 404 로 통일한다(INV-8·5.2).
  이미 비활성 링크는 re-retire 하지 않는다(retire 스코프=enabled-only, 멱등). 모든 무효/부재는
  동일하게 404(정보 비노출, §Error Handling).
- **동적 active 하위**: 유효 시 `active_descendants` 로 접근 시점의 active 하위(root 포함, trashed
  서브트리 제외)를 동적 수집한다(하위 추가는 자동 포함·trashed 제외, Req 3.4·3.5).
- **안전 렌더 + 참조 재작성**: 각 문서 본문을 `MarkdownRenderer` 로 안전 HTML 렌더하고(3.2), 렌더
  HTML 의 `/attachments/{id}` 참조를 `/public/{token}/attachments/{id}` 로 재작성한다(id 경계
  정확, Req 8.4 이미지 로딩). 읽기 전용 중첩 트리를 반환한다(변경 동작 없음, Req 3.3).

경계(design.md §Dependency Direction): 리포지토리·s07 primitive 는 생성자 주입하고 DB 세션은
메서드별 인자로 전달받는다(`app/attachment/service.py` 주입 규약과 정합). 라우터·다른 feature
service 를 import 하지 않으며, 상태 전이·게이트 설정·첨부 저장·렌더 규약을 재구현하지 않는다.
유일한 쓰기는 무효 관측 시의 lazy retire 뿐이다(그 외 읽기 전용).
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.common.errors import DomainError, ErrorCode
from app.document.engine import DocumentStateEngine
from app.document.renderer import MarkdownRenderer
from app.document.repository import DocumentRepository
from app.models import Document, ShareLink, Workspace
from app.sharing.repository import ShareLinkRepository
from app.sharing.schemas import PublicDocumentNode, PublicDocumentRead

__all__ = ["PublicShareService"]

# 문서 "살아있는" 상태 값(s01 document.status ENUM). 공개 유효성이 관측한다.
_ACTIVE = "active"

# 렌더 HTML 의 첨부 참조 패턴. `\d+` 로 숫자 id 전체를 포착해 `/attachments/5` 와
# `/attachments/50` 이 서로 오염되지 않도록 id 경계를 정확히 구분한다(Req 8.4).
_ATTACHMENT_REF = re.compile(r"/attachments/(\d+)")


class PublicShareService:
    """공개 읽기 전용 렌더 유스케이스(Req 3.1~3.6, 5.1·5.2, 7.7).

    리포지토리와 s07 primitive(문서 리포지토리·상태 엔진·렌더러)를 생성자 주입하고 DB 세션은
    메서드별 인자로 전달받는다. 공개 유효성은 접근마다 라이브로 관측하며, 무효 조건 관측 시
    그 자리에서 lazy retire 로 영구화한다(INV-8). 이 태스크는 `render_public_document` 만 소유
    하고 링크 경유 첨부 서빙은 후속 태스크가 같은 유효성 게이트를 재사용해 추가한다.
    """

    def __init__(
        self,
        *,
        repository: ShareLinkRepository | None = None,
        document_repository: DocumentRepository | None = None,
        engine: DocumentStateEngine | None = None,
        renderer: MarkdownRenderer | None = None,
    ) -> None:
        self._repository = repository or ShareLinkRepository()
        self._documents = document_repository or DocumentRepository()
        self._engine = engine or DocumentStateEngine(self._documents)
        self._renderer = renderer or MarkdownRenderer()

    def render_public_document(
        self, db: Session, token: str
    ) -> PublicDocumentRead:
        """토큰으로 문서 + 현재 active 하위 트리를 안전 렌더해 읽기 전용으로 반환한다
        (design.md §System Flows 공개 렌더 flowchart, Req 3.1~3.6·5.1·5.2).

        판정·구성 순서는 flowchart 를 그대로 따른다:

        1. **공개 유효성(실시간 게이트)**: `_resolve_valid_link` 로 토큰→링크·문서를 확정한다.
           무효/부재는 그 helper 가 lazy retire 후 404 로 통일한다(정보 비노출, Req 3.6·5.2).
        2. **동적 active 하위 수집**: `DocumentStateEngine.active_descendants` 로 **접근 시점**의
           현재 active 하위(root 포함, trashed 서브트리 제외)를 동적 수집한다(Req 3.4·3.5). 이
           질의는 root-first BFS 평면 목록을 주므로 각 노드의 부모가 자신보다 먼저 등장한다.
        3. **안전 렌더 + 참조 재작성**: 각 문서 본문을 `load_current_content`(없으면 "") →
           `MarkdownRenderer.render` 로 안전 HTML 렌더하고(3.2), `/attachments/{id}` 참조를
           `/public/{token}/attachments/{id}` 로 재작성한다(id 경계 정확, Req 8.4).
        4. **읽기 전용 중첩 트리 구성**: 평면 목록의 root-first 특성을 이용해 `id → 노드` 매핑으로
           각 비-root 노드를 부모의 `children` 에 붙여 중첩 트리를 만들고 root 를 응답으로 반환
           한다. 변경 동작은 제공하지 않는다(Req 3.3).
        """
        _, document = self._resolve_valid_link(db, token)

        members = self._engine.active_descendants(db, document)

        # root-first BFS 이므로 각 노드의 부모는 자신보다 먼저 매핑에 존재한다.
        nodes: dict[int, PublicDocumentNode] = {}
        root_node: PublicDocumentNode | None = None
        for doc in members:
            node = PublicDocumentNode(
                id=doc.id,
                title=doc.title,
                content_html=self._render_content(db, doc, token),
                children=[],
            )
            nodes[doc.id] = node
            if doc.id == document.id:
                root_node = node
            else:
                parent = nodes.get(doc.parent_id)
                # 부모가 목록에 있으면(root-first 보장) 그 밑에 중첩한다.
                if parent is not None:
                    parent.children.append(node)

        # active_descendants 는 항상 root 를 포함하므로 root_node 는 확정된다.
        assert root_node is not None
        return PublicDocumentRead(root=root_node)

    def _resolve_valid_link(
        self, db: Session, token: str
    ) -> tuple[ShareLink, Document]:
        """토큰으로 공개 유효성을 실시간 관측해 유효 링크·문서를 확정한다(공용 게이트, Req 5.1·5.2).

        후속 태스크(링크 경유 첨부 서빙)가 그대로 재사용하는 유효성 게이트다.

        - 토큰으로 링크 로드(부재→404). 문서·워크스페이스를 로드해 유효성을 판정한다.
        - 유효 = `is_enabled` AND 문서 status=active AND 워크스페이스 `is_shareable`(실시간 관측).
        - **lazy retire**: 링크가 아직 활성인데 무효 조건(문서 비active·게이트 off)을 관측했으면
          그 자리에서 `retire`(비활성 + 토큰 교체)로 영구 무효화한다(INV-8·5.2). 이미 비활성
          링크는 re-retire 하지 않는다(retire 스코프=enabled-only, 멱등).
        - 무효/부재는 사유를 구분하지 않고 모두 404 로 통일한다(정보 비노출, §Error Handling).

        상태 전이·게이트 설정은 하지 않고 문서 status·게이트를 관측만 한다. 유효 시 (link,
        document) 를 반환한다(호출자가 하위 계층 수집·서빙에 사용).
        """
        link = self._repository.get_by_token(db, token)
        if link is None:
            raise self._not_found()

        document = self._documents.get(db, link.document_id)
        workspace = (
            db.get(Workspace, document.workspace_id)
            if document is not None
            else None
        )
        is_valid = (
            link.is_enabled
            and document is not None
            and document.status == _ACTIVE
            and workspace is not None
            and workspace.is_shareable
        )
        if not is_valid:
            # 활성 링크에서 무효 조건을 관측했으면 그 자리에서 영구화(lazy retire).
            if link.is_enabled:
                self._repository.retire(db, link)
            raise self._not_found()

        return link, document

    def _render_content(self, db: Session, doc: Document, token: str) -> str:
        """문서 본문을 안전 HTML 로 렌더하고 첨부 참조를 링크 스코프 경로로 재작성한다(Req 3.2·8.4).

        `load_current_content`(현재 버전 없으면 "") → `MarkdownRenderer.render`(markdown-it +
        nh3 새니타이즈: 스크립트·이벤트 핸들러·위험 URL 제거) → `/attachments/{id}` 참조를
        `/public/{token}/attachments/{id}` 로 재작성한다. 렌더·새니타이즈 규약은 s07 소유이므로
        재구현하지 않고 재사용만 한다.
        """
        markdown = self._documents.load_current_content(db, doc)
        html = self._renderer.render(markdown)
        return self._rewrite_attachment_refs(html, token)

    def _rewrite_attachment_refs(self, html: str, token: str) -> str:
        """렌더 HTML 의 `/attachments/{id}` 참조를 `/public/{token}/attachments/{id}` 로 재작성한다(Req 8.4).

        `\\d+` 로 숫자 id 전체를 포착해 `/attachments/5` 와 `/attachments/50` 이 서로 오염되지
        않도록 id 경계를 정확히 구분한다. 치환은 함수 콜백으로 리터럴 문자열을 반환하므로 토큰
        문자열(url-safe base64)이 치환 백레퍼런스로 해석될 여지가 없다(방어적 안전).
        """
        return _ATTACHMENT_REF.sub(
            lambda m: f"/public/{token}/attachments/{m.group(1)}", html
        )

    def _not_found(self) -> DomainError:
        """공개 경로의 모든 무효/부재를 통일하는 404 DomainError 를 생성한다(정보 비노출).

        토큰·문서 존재 여부·무효 사유를 구분하지 않고 동일한 404 로 매핑해 존재 추정을 차단한다
        (INV-8, §Error Handling).
        """
        return DomainError(
            code=ErrorCode.NOT_FOUND,
            message="공유 링크를 찾을 수 없습니다",
            http_status=404,
        )
