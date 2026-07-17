"""휴지통 묶음 표시 스키마 (design.md §Components and Interfaces #TrashSchemas).

s01 Base Schemas 규약(`{Resource}Read`·`ORMReadModel`·`Page[T]`)을 상속하며 **표시용
스키마 형태만** 소유한다(Req 6.2). 공통 Read 베이스(`ORMReadModel`)와 목록 엔벨로프
`Page[T]` 는 s01 소유이며 여기서 재정의하지 않는다. 묶음(bundle)의 원천은 s07
`DocumentStateEngine` 이 반환하는 `Bundle` DTO(루트 문서 id·묶음 공통 trashed_at·구성원)
이고, 이 스키마는 그 DTO 를 응답 표시용으로 **투영**할 뿐 상태·묶음 규칙을 판정하지 않는다.

- `TrashMemberRead` — 묶음 구성원 요약(계층 파악용). 문서 id·parent_id·title 만 노출한다.
- `TrashBundleRead` — 묶음 = 루트 문서 id. `bundle_id` 는 s07 묶음 식별자(= root_document_id,
  카탈로그 `{bundleId}`)와 동일하다. `trashed_at` 은 묶음 공통 값(INV-11·12 기준)이다.

`expires_at` 규약 (Req 1.4)
--------------------------
`expires_at`(보관 만료 예정 시각)은 **저장 컬럼이 아니라 응답 시 산정되는 파생값**이다
(= 묶음 `trashed_at` + 워크스페이스 `trash_retention_days`). 요청 입력이 아니며 필수
필드다. retention_days 는 서비스/리포지토리 계층(s05 워크스페이스 설정)에서 조회하므로
이 스키마는 **계산하지 않고** `from_bundle(..., expires_at=...)` 로 산정된 값을 주입만
받는다(스키마를 순수 표시 타입으로 유지).
"""

from __future__ import annotations

from datetime import datetime

from app.document.engine import Bundle
from app.schemas.base import ORMReadModel

__all__ = ["TrashMemberRead", "TrashBundleRead"]


class TrashMemberRead(ORMReadModel):
    """휴지통 묶음 구성원 요약(표시용, Req 1.3).

    s01 `ORMReadModel`(from_attributes) 상속으로 문서 속성 객체로부터 계층 파악에 필요한
    최소 필드(id·parent_id·title)만 직렬화한다. 상태/trashed_at 등 전이 관련 필드는
    묶음 수준(`TrashBundleRead`)에서 공통으로 표현하므로 구성원에는 두지 않는다.
    """

    id: int
    parent_id: int | None
    title: str


class TrashBundleRead(ORMReadModel):
    """휴지통 묶음 표시 스키마 — s07 `Bundle` 을 응답 표시용으로 투영 (Req 1.3·1.4).

    `bundle_id` 는 s07 묶음 식별자(루트 문서 id, 카탈로그 `{bundleId}`)와 동일하다.
    `trashed_at` 은 묶음 공통 trashed_at 이고, `expires_at` 은 서버 산정 파생값(= trashed_at
    + 워크스페이스 trash_retention_days)으로 **요청 입력이 아니며 필수**다(Req 1.4). 목록
    응답은 s01 `Page[TrashBundleRead]` 규약을 따른다(Req 6.2).
    """

    bundle_id: int  # = root_document_id (카탈로그 {bundleId})
    root_document_id: int
    root_title: str
    workspace_id: int
    trashed_at: datetime  # 묶음 공통 trashed_at (INV-11·12 기준)
    expires_at: datetime  # = trashed_at + workspace.trash_retention_days (서버 산정 파생값)
    member_count: int
    members: list[TrashMemberRead]  # 구성원 요약(계층 파악용)

    @classmethod
    def from_bundle(cls, bundle: Bundle, *, expires_at: datetime) -> TrashBundleRead:
        """s07 `Bundle` DTO + 호출자가 산정한 `expires_at` 을 표시 스키마로 투영한다.

        무엇이 묶음인지·구성원이 무엇인지는 s07 엔진이 이미 확정한 `Bundle` 을 그대로
        소비한다(재판정 없음, Req 1.2). 루트 구성원은 `root_document_id` 로 찾아(members
        정렬 순서와 무관), 그 문서에서 `root_title`·`workspace_id` 를 취한다.
        `expires_at` 은 여기서 계산하지 않고 인자로 받은 값을 그대로 반영한다(Req 1.4).
        """
        root = next(
            m for m in bundle.members if m.id == bundle.root_document_id
        )
        return cls(
            bundle_id=bundle.root_document_id,
            root_document_id=bundle.root_document_id,
            root_title=root.title,
            workspace_id=root.workspace_id,
            trashed_at=bundle.trashed_at,
            expires_at=expires_at,
            member_count=len(bundle.members),
            members=[
                TrashMemberRead.model_validate(m) for m in bundle.members
            ],
        )
