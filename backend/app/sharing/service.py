"""공유 링크 발급·재발급·토글 유스케이스 — `ShareLinkService`
(design.md §Components and Interfaces #ShareLinkService, Feature/Service).

워크스페이스 `is_shareable` 게이트와 문서 status 를 **관측**해 문서 단위 공유 링크의 발급/
재발급(항상 새 토큰)·토글(상태 전환·토큰 유지)을 오케스트레이션하는 얇은 서비스다. 상태 전이·
게이트 설정·무효화 판정은 소유하지 않으며(각각 s07/s10·s05, 무효화는 `ShareInvalidationSweep`/
공개 게이트), 링크 행의 발급·상태 전환과 응답 구성만 담당한다.

재발급 통일 원칙(INV-8)의 구현 지점이다: 사용자 조작 **토글**만 동일 토큰의 상태를 되돌리는
유일한 상태 기반 예외이고, 그 외 발급/재발급은 항상 새 토큰을 만든다(§4.5). 발급은 게이트 on·
문서 active 일 때만 허용하며(아니면 409), 토글의 활성화도 동일 조건에서만 허용한다. 토글의
비활성화는 게이트·status 와 무관하게 항상 허용한다(토큰 유지).

경계(design.md §Dependency Direction): 리포지토리(`ShareLinkRepository`)·s07 문서 리포지토리
(`DocumentRepository`)는 생성자 주입하고 DB 세션은 메서드별 인자로 전달받는다(`app/attachment/
service.py` 주입 규약과 정합). 게이트 값은 s01 `Workspace` 모델을 세션으로 관측하며, resolver·
권한 판정은 재구현하지 않는다(라우터의 `ws_role_for_document(MEMBER)` 게이트 소관). 라우터·다른
feature service 를 import 하지 않는다. 링크 물리 삭제 없음(INV-4, retire 는 무효화 조정 소관).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.document.repository import DocumentRepository
from app.models import Workspace
from app.sharing.repository import ShareLinkRepository
from app.sharing.schemas import ShareLinkRead, ShareLinkUpdate

__all__ = ["ShareLinkService"]

# 문서의 "살아있는" 상태 값(s01 document.status ENUM). 발급/활성화 허용 조건이 관측한다.
_ACTIVE = "active"


class ShareLinkService:
    """공유 링크 발급/재발급·토글(게이트·문서 active 검사) 유스케이스
    (Req 1.1, 1.2, 1.3, 1.4, 2.1, 2.4, 2.5, 4.1, 4.2, 4.3).

    리포지토리와 s07 문서 리포지토리를 생성자 주입하고 DB 세션은 메서드별 인자로 전달받는다.
    게이트(`workspace.is_shareable`)·문서 status 를 관측만 하며 상태 전이·게이트 설정은 하지
    않는다. 발급/재발급은 항상 새 토큰(INV-8), 토글은 토큰을 유지하는 유일한 상태 기반 예외다.
    """

    def __init__(
        self,
        *,
        repository: ShareLinkRepository | None = None,
        document_repository: DocumentRepository | None = None,
    ) -> None:
        self._repository = repository or ShareLinkRepository()
        self._documents = document_repository or DocumentRepository()

    def get_link(self, db: Session, document_id: int) -> ShareLinkRead | None:
        """문서의 현재 공유 링크 상태를 읽기 전용으로 조회한다: 있으면 응답, 없으면 None
        (design.md §Components and Interfaces #ShareLinkService.get_link, Req 1.1·1.2·1.3).

        `ShareLinkRepository.get_by_document` 로 문서의 링크(최대 1개)를 로드해, 있으면
        `ShareLinkRead.from_share_link` 로 `token·is_enabled·share_url`(`/public/{token}`) 을
        담은 응답을 반환하고, 없으면 "링크 없음"을 나타내는 `None` 을 반환한다(오류 아님, Req 1.2).

        **읽기 전용**: 상태 전이 협력자(`upsert_reissue`·`set_enabled`·`retire`)를 호출하지
        않으며, 발급/토글과 달리 게이트(`workspace.is_shareable`)·문서 `status` 를 관측조차 하지
        않는다(Req 1.3). 어떤 행도 쓰지 않으므로 호출 전후 링크 행·토큰·활성 상태가 불변이다.
        발급/토글과 달리 role 재검사(`ctx`)도 하지 않는다 — 라우터 게이트가 member 이상(admin
        bypass)·문서 부재 404 를 판정 이전 단계에서 산출한다.
        """
        link = self._repository.get_by_document(db, document_id)
        return ShareLinkRead.from_share_link(link) if link is not None else None

    def issue_link(
        self, db: Session, ctx: AuthContext, document_id: int
    ) -> ShareLinkRead:
        """공유 링크를 발급/재발급한다: 게이트 on·문서 active 검사 후 새 토큰의 활성 링크를 반환한다
        (design.md §System Flows 발급·재발급 flowchart, Req 1.1·1.2·1.3·1.4·2.1·2.4·2.5).

        판정 순서는 flowchart 를 그대로 따른다:

        1. **문서 존재 확인**: s07 `DocumentRepository.get` 으로 문서를 로드한다. 없으면 404 로
           거부한다(Req 2.1 부재).
        2. **문서 active 검사**: `document.status` 가 active 가 아니면 409 로 거부한다(비active
           발급 금지, Req 1.4). 상태를 관측만 하고 전이시키지 않는다.
        3. **게이트 관측**: 소속 워크스페이스(`document.workspace_id`)의 `is_shareable` 를
           관측해 off 면 409 로 거부한다(게이트 off 발급 불가, Req 1.1, 7.1). 게이트를 설정하지
           않고 관측만 한다.
        4. **발급/재발급**: `ShareLinkRepository.upsert_reissue` 로 링크 행을 upsert 하되 **항상
           새 토큰 + is_enabled=True** 로 만든다(이전 무효화 토큰을 되살리지 않음, INV-8·§4.5,
           Req 2.4). 문서당 링크 행은 최대 1개이므로 재발급도 같은 행을 재사용한다.
        5. **응답 구성**: `ShareLinkRead.from_share_link` 로 `share_url`(`/public/{token}`) 을
           산정한 응답을 반환한다(단일 read-model 생성 경로).

        `ctx` 는 라우터의 `ws_role_for_document(MEMBER)` 게이트 이후 전달되는 인증 컨텍스트로,
        본 서비스는 권한(role)을 재검사하지 않는다(계약 시그니처 정합용). 물리 삭제도 하지
        않는다(INV-4).
        """
        # 1. 문서 로드. 부재 → 404.
        document = self._documents.get(db, document_id)
        if document is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="공유할 문서를 찾을 수 없습니다",
                http_status=404,
            )

        # 2. 문서 active 검사(관측만). 비active → 409.
        if document.status != _ACTIVE:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="active 문서만 공유 링크를 발급할 수 있습니다",
                http_status=409,
            )

        # 3. 워크스페이스 게이트 관측. off → 409.
        workspace = db.get(Workspace, document.workspace_id)
        if workspace is None or not workspace.is_shareable:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="워크스페이스 공유가 비활성화되어 링크를 발급할 수 없습니다",
                http_status=409,
            )

        # 4. 발급/재발급(항상 새 토큰 + 활성, INV-8).
        link = self._repository.upsert_reissue(db, document_id)

        # 5. share_url(/public/{token}) 을 산정한 응답 구성(단일 생성 경로).
        return ShareLinkRead.from_share_link(link)

    def toggle_link(
        self, db: Session, document_id: int, payload: ShareLinkUpdate
    ) -> ShareLinkRead:
        """문서의 공유 링크 상태를 전환한다: 비활성화는 항상, 활성화는 게이트 on·문서 active 일 때만
        허용하며 **토큰을 유지**한다(design.md §System Flows 토글 flowchart, Req 4.1·4.2·4.3).

        판정 순서는 flowchart 를 그대로 따른다:

        1. **링크 로드**: `ShareLinkRepository.get_by_document` 로 문서의 링크(최대 1개)를 로드
           한다. 없으면 404 로 거부한다(Req 4.1 부재).
        2. **비활성화(is_enabled=False)**: 게이트·문서 status 와 **무관하게 항상 허용**한다.
           `set_enabled(enabled=False)` 로 상태만 끄고 토큰을 유지한다(Req 4.1·4.3).
        3. **활성화(is_enabled=True)**: 게이트 on·문서 active 일 때만 허용한다. 문서를 로드해
           부재/비active 면 409, 소속 워크스페이스 게이트 off 면 409 로 거부한다(Req 4.2, 7.1).
           통과 시 `set_enabled(enabled=True)` 로 상태만 켜고 토큰을 유지한다.

        토글은 새 토큰을 만들지 않는 **재발급 통일 원칙(INV-8)의 유일한 상태 기반 예외**다
        (Req 4.3, 7.7). `upsert_reissue`·`retire` 를 호출하지 않으므로 이전 URL 이 그대로
        되살아난다(단, 이미 retire 된 토큰은 소멸했으므로 되살릴 수 없다). 게이트·status 를
        관측만 하며 상태 전이·게이트 설정은 하지 않고, 물리 삭제도 하지 않는다(INV-4).
        """
        # 1. 링크 로드. 부재 → 404.
        link = self._repository.get_by_document(db, document_id)
        if link is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="공유 링크를 찾을 수 없습니다",
                http_status=404,
            )

        # 2. 비활성화는 게이트·status 와 무관하게 항상 허용(토큰 유지).
        if payload.is_enabled is False:
            updated = self._repository.set_enabled(db, link, enabled=False)
            return ShareLinkRead.from_share_link(updated)

        # 3. 활성화는 게이트 on·문서 active 일 때만 허용(아니면 409).
        document = self._documents.get(db, document_id)
        if document is None or document.status != _ACTIVE:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="active 문서만 공유 링크를 활성화할 수 있습니다",
                http_status=409,
            )

        workspace = db.get(Workspace, document.workspace_id)
        if workspace is None or not workspace.is_shareable:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="워크스페이스 공유가 비활성화되어 링크를 활성화할 수 없습니다",
                http_status=409,
            )

        updated = self._repository.set_enabled(db, link, enabled=True)
        return ShareLinkRead.from_share_link(updated)
