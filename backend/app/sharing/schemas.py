"""공유 링크·공개 렌더 스키마 (design.md §Components and Interfaces #SharingSchemas).

s01 Base Schemas 규약(`{Resource}Read`·`TimestampedRead`)을 상속하며 **스키마 형태와 공유/
공개 URL 규약만** 소유한다(Req 7.1). Base 규약·`share_link` 스키마(테이블 계약) 정의는 s01
소유이므로 여기서 재정의하지 않는다.

- `ShareLinkRead` — 발급/토글 응답. s01 `TimestampedRead`(id·created_at·updated_at) 상속.
  `share_url` 은 ORM 컬럼이 아닌 서버 산정 파생값(`/public/{token}`)이며 필수 필드다.
- `ShareLinkUpdate` — 토글 요청 본문(부분): `is_enabled` 만 전환.
- `PublicDocumentNode`/`PublicDocumentRead` — 공개 읽기 전용 중첩 트리. 공유 문서를 루트로
  하고, 각 노드는 id·title·content_html·children 만 노출한다(최소 노출, Req 7.1).

`share_url` 규약 (Req 2.1)
--------------------------
`share_url`(공유 링크 공개 URL)은 ORM `share_link` 컬럼이 아니라 응답 시 산정되는 **파생값**
(`/public/{token}`)이며 필수 필드다. ORM `ShareLink` 객체에는 `share_url` 속성이 없어
`model_validate(link)` 단독으로는 실패하므로, 서비스는 `ShareLinkRead.from_share_link(link)`
로 ORM 컬럼과 산정된 url 을 함께 넘겨 구성한다(s12 `AttachmentRead.from_attachment` 패턴).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.base import TimestampedRead

__all__ = [
    "ShareLinkRead",
    "ShareLinkUpdate",
    "PublicDocumentNode",
    "PublicDocumentRead",
]


# ORM share_link 컬럼이 아닌, 응답 시 서버가 산정하는 파생 필드.
_DERIVED_FIELDS = frozenset({"share_url"})


class ShareLinkRead(TimestampedRead):
    """공유 링크 발급/토글 응답 (Req 2.1·4.1·7.1).

    s01 `TimestampedRead`(from_attributes) 상속으로 ORM `share_link` 속성 객체로부터
    id·created_at 을 직렬화한다. `share_link` 테이블에는 `updated_at` 컬럼이 없으므로
    `TimestampedRead.updated_at` 기본값 None 이 그대로 사용된다. `share_url` 은 ORM 컬럼이
    아닌 서버 산정 파생값(`/public/{token}`)이므로 `from_share_link` 로 함께 구성한다.
    """

    document_id: int
    token: str
    is_enabled: bool
    share_url: str  # = "/public/{token}" (공유 URL 규약, 서버 산정 파생값)

    @classmethod
    def from_share_link(cls, link: object) -> ShareLinkRead:
        """ORM `share_link` 객체와 산정된 `share_url` 로 응답을 구성한다.

        ORM 컬럼 필드는 속성 접근으로 읽고, ORM 에 없는 파생 필드 `share_url` 은 링크 토큰
        으로부터 `/public/{token}` 규약으로 산정해 주입한다. `share_link` 테이블에 컬럼이 없는
        `updated_at`(`TimestampedRead` 상속 필드)은 ORM 객체에 속성이 없으므로 건너뛰어 스키마
        기본값 None 으로 둔다. 서비스가 응답을 만드는 단일 경로다.
        """
        orm_fields = {
            name: getattr(link, name)
            for name in cls.model_fields
            if name not in _DERIVED_FIELDS and hasattr(link, name)
        }
        return cls(**orm_fields, share_url=f"/public/{link.token}")


class ShareLinkUpdate(BaseModel):
    """공유 링크 토글 요청 본문 (Req 4.1).

    재발급 통일 원칙(INV-8)의 유일한 상태 기반 예외인 토글 요청. `is_enabled` 상태만 전환
    하며 토큰은 유지된다(서비스 소관). ORM Read 베이스를 상속하지 않는 순수 요청 스키마다.
    """

    is_enabled: bool


class PublicDocumentNode(BaseModel):
    """공개 읽기 전용 트리 노드 (Req 3.1·7.1, 최소 노출).

    공유 문서 및 그 현재 active 하위 계층의 노드. `content_html` 은 s07 `MarkdownRenderer`
    로 안전 렌더된 HTML(첨부 참조는 링크 스코프 경로로 재작성, 상위 태스크 소관)을 담는다.
    `workspace_id`·`created_by`·`sort_order`·`status`·`parent_id` 등 내부 필드는 노출하지
    않는다(최소 노출). `children` 은 접근 시점의 현재 active 하위(동적)를 재귀로 담는다.
    """

    id: int
    title: str
    content_html: str
    children: list["PublicDocumentNode"] = Field(default_factory=list)


class PublicDocumentRead(BaseModel):
    """공개 렌더 응답(`GET /public/{token}`) — 읽기 전용 중첩 트리 (Req 3.1).

    공유 문서를 루트로 하고 하위 계층을 `root.children` 으로 중첩 표현한다.
    """

    root: PublicDocumentNode


# 재귀 자기 참조(`list["PublicDocumentNode"]`) 해소 — pydantic v2 forward ref 확정.
PublicDocumentNode.model_rebuild()
