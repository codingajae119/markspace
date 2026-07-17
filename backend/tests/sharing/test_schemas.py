"""SharingSchemas 단위 검증 (s14-sharing task 1.1).

design.md §Components and Interfaces #SharingSchemas, requirements.md 2.1·3.1·4.1·7.1 검증:
- `ShareLinkRead` 는 s01 `TimestampedRead`(id·created_at·updated_at) 를 상속한 링크 응답
  스키마이며, `document_id`·`token`·`is_enabled` 와 서버 산정 파생 필드 `share_url`
  (`/public/{token}`) 을 가진다. ORM `ShareLink` 에는 `share_url` 컬럼이 없으므로
  `ShareLinkRead.from_share_link(link)` 로 컬럼을 읽고 파생 url 을 주입해 구성한다.
- `ShareLinkUpdate` 는 토글 요청(부분): `is_enabled` 만 담는 plain BaseModel 이다.
- `PublicDocumentNode` 는 공개 읽기 전용 트리 노드로 id·title·content_html·children 만
  노출하고 workspace_id·created_by·sort_order·status 등 내부 필드는 노출하지 않는다(최소 노출).
- `PublicDocumentRead` 는 공유 문서를 루트로 하는 중첩 트리 응답(root: PublicDocumentNode)이다.
"""

from datetime import datetime
from enum import Enum

import pytest
from pydantic import BaseModel, ValidationError

from app.models import ShareLink
from app.schemas.base import ORMReadModel, TimestampedRead
from app.sharing.schemas import (
    PublicDocumentNode,
    PublicDocumentRead,
    ShareLinkRead,
    ShareLinkUpdate,
)


def _share_link(
    *,
    id: int = 7,
    document_id: int = 10,
    token: str = "tok-abc",
    is_enabled: bool = True,
    created_at: datetime | None = None,
) -> ShareLink:
    """DB 세션 없이 in-memory ORM ShareLink 인스턴스를 만든다(투영 검증용)."""
    return ShareLink(
        id=id,
        document_id=document_id,
        token=token,
        is_enabled=is_enabled,
        created_at=created_at or datetime(2026, 7, 1, 12, 0, 0),
    )


# --- ShareLinkRead: TimestampedRead 상속·필드 규약 (2.1·7.1) ---


def test_share_link_read_inherits_timestamped_read() -> None:
    assert issubclass(ShareLinkRead, TimestampedRead)
    assert issubclass(ShareLinkRead, ORMReadModel)
    assert ShareLinkRead.model_config.get("from_attributes") is True
    assert set(ShareLinkRead.model_fields) == {
        "id",
        "created_at",
        "updated_at",
        "document_id",
        "token",
        "is_enabled",
        "share_url",
    }


def test_share_link_read_share_url_is_required() -> None:
    """`share_url` 은 옵셔널이 아니라 서버 산정 필수 파생 필드다."""
    with pytest.raises(ValidationError):
        ShareLinkRead(
            id=7,
            document_id=10,
            token="tok-abc",
            is_enabled=True,
            created_at=datetime(2026, 7, 1, 12, 0, 0),
        )  # type: ignore[call-arg]


def test_model_validate_on_raw_share_link_fails_without_share_url() -> None:
    """ORM ShareLink 에는 share_url 속성이 없어 model_validate 단독으로는 구성 불가(파생값)."""
    link = _share_link()
    with pytest.raises(ValidationError):
        ShareLinkRead.model_validate(link)


# --- from_share_link: ORM → 표시 스키마, share_url 산정 ---


def test_from_share_link_computes_share_url_and_projects_columns() -> None:
    link = _share_link(id=7, document_id=10, token="tok-abc", is_enabled=True)

    read = ShareLinkRead.from_share_link(link)

    assert read.id == 7
    assert read.document_id == 10
    assert read.token == "tok-abc"
    assert read.is_enabled is True
    assert read.created_at == datetime(2026, 7, 1, 12, 0, 0)
    assert read.updated_at is None  # share_link 에는 updated_at 컬럼이 없다(기본 None)
    assert read.share_url == "/public/tok-abc"


def test_from_share_link_url_tracks_token() -> None:
    assert ShareLinkRead.from_share_link(_share_link(token="xyz")).share_url == "/public/xyz"
    assert ShareLinkRead.from_share_link(_share_link(token="q9")).share_url == "/public/q9"


def test_from_share_link_preserves_disabled_state() -> None:
    read = ShareLinkRead.from_share_link(_share_link(is_enabled=False))
    assert read.is_enabled is False


# --- ShareLinkUpdate: 토글 요청(is_enabled) (4.1) ---


def test_share_link_update_is_plain_base_model() -> None:
    assert issubclass(ShareLinkUpdate, BaseModel)
    assert not issubclass(ShareLinkUpdate, ORMReadModel)
    assert set(ShareLinkUpdate.model_fields) == {"is_enabled"}


def test_share_link_update_requires_is_enabled() -> None:
    with pytest.raises(ValidationError):
        ShareLinkUpdate()  # type: ignore[call-arg]
    assert ShareLinkUpdate(is_enabled=True).is_enabled is True
    assert ShareLinkUpdate(is_enabled=False).is_enabled is False


# --- PublicDocumentNode/Read: 공개 읽기 전용 중첩 트리·최소 노출 (3.1·7.1) ---


def test_public_document_node_fields_are_minimal_exposure() -> None:
    """공개 노드는 id·title·content_html·children 만 노출하고 내부 필드는 없다."""
    assert set(PublicDocumentNode.model_fields) == {
        "id",
        "title",
        "content_html",
        "children",
    }
    # 내부 필드는 스키마에 존재하지 않는다(최소 노출).
    for internal in ("workspace_id", "created_by", "sort_order", "status", "parent_id"):
        assert internal not in PublicDocumentNode.model_fields


def test_public_document_node_children_default_empty() -> None:
    node = PublicDocumentNode(id=1, title="root", content_html="<p>hi</p>")
    assert node.children == []


def test_public_document_read_is_nested_tree() -> None:
    tree = PublicDocumentRead(
        root=PublicDocumentNode(
            id=1,
            title="root",
            content_html="<h1>Root</h1>",
            children=[
                PublicDocumentNode(id=2, title="child-a", content_html="<p>a</p>"),
                PublicDocumentNode(
                    id=3,
                    title="child-b",
                    content_html="<p>b</p>",
                    children=[
                        PublicDocumentNode(id=4, title="grandchild", content_html="<p>g</p>"),
                    ],
                ),
            ],
        )
    )

    assert set(PublicDocumentRead.model_fields) == {"root"}
    assert tree.root.id == 1
    assert tree.root.children[1].children[0].id == 4

    dumped = tree.model_dump()
    assert dumped == {
        "root": {
            "id": 1,
            "title": "root",
            "content_html": "<h1>Root</h1>",
            "children": [
                {"id": 2, "title": "child-a", "content_html": "<p>a</p>", "children": []},
                {
                    "id": 3,
                    "title": "child-b",
                    "content_html": "<p>b</p>",
                    "children": [
                        {"id": 4, "title": "grandchild", "content_html": "<p>g</p>", "children": []},
                    ],
                },
            ],
        }
    }


def test_public_read_rejects_internal_field_injection() -> None:
    """공개 노드는 내부 필드를 받아도 무시(노출 없음) — 스키마에 필드가 없다."""
    node = PublicDocumentNode.model_validate(
        {
            "id": 1,
            "title": "root",
            "content_html": "<p>x</p>",
            "children": [],
            "workspace_id": 99,
            "created_by": 5,
        }
    )
    dumped = node.model_dump()
    assert "workspace_id" not in dumped
    assert "created_by" not in dumped


class _EnumTitle(str, Enum):
    A = "a"


def test_content_html_and_title_are_str_typed() -> None:
    """title·content_html 은 문자열 타입으로 안전 렌더 HTML 을 담는다(3.2 소비 준비)."""
    node = PublicDocumentNode(id=1, title="t", content_html="<p>safe</p>")
    assert isinstance(node.title, str)
    assert isinstance(node.content_html, str)
