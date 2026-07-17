"""TrashSchemas 단위 검증 (s10-trash task 1.1).

requirements.md 1.3·1.4·6.2, design.md §Components and Interfaces #TrashSchemas 검증:
- `TrashBundleRead`·`TrashMemberRead` 는 s01 `ORMReadModel`(from_attributes) 을 상속한
  순수 표시 스키마다(6.2).
- `TrashBundleRead.from_bundle(bundle, expires_at=...)` 은 s07 `Bundle` DTO(루트·구성원·
  묶음 공통 trashed_at)를 표시 스키마로 투영한다(1.3): bundle_id == root_document_id,
  root_title/workspace_id 는 루트 구성원에서, member_count == len(members), 각 구성원 →
  `TrashMemberRead`(id·parent_id·title).
- `expires_at` 은 서버 산정 파생값(요청 입력 아님)이며 스키마에 저장 컬럼이 아니라 응답 시
  주입되는 필수 필드다(1.4). retention_days 계산은 스키마 밖(서비스/리포지토리)에서 하며
  `from_bundle` 은 계산된 값을 주입만 받는다.
- 목록 응답은 s01 `Page[TrashBundleRead]` 규약을 따른다(6.2).
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.document.engine import Bundle
from app.models import Document
from app.schemas.base import ORMReadModel, Page
from app.trash.schemas import TrashBundleRead, TrashMemberRead


def _doc(
    *,
    id: int,
    parent_id: int | None,
    title: str,
    workspace_id: int,
    trashed_at: datetime,
) -> Document:
    """DB 세션 없이 in-memory ORM Document 인스턴스를 만든다(투영 검증용)."""
    return Document(
        id=id,
        parent_id=parent_id,
        title=title,
        workspace_id=workspace_id,
        status="trashed",
        trashed_at=trashed_at,
    )


def _bundle() -> Bundle:
    """루트 + 자식 2개(루트 포함 구성원 3)의 s07 Bundle 을 만든다."""
    trashed_at = datetime(2026, 7, 1, 12, 0, 0)
    root = _doc(
        id=10,
        parent_id=None,
        title="루트 문서",
        workspace_id=5,
        trashed_at=trashed_at,
    )
    child_a = _doc(
        id=11,
        parent_id=10,
        title="자식 A",
        workspace_id=5,
        trashed_at=trashed_at,
    )
    child_b = _doc(
        id=12,
        parent_id=10,
        title="자식 B",
        workspace_id=5,
        trashed_at=trashed_at,
    )
    return Bundle(
        root_document_id=10,
        trashed_at=trashed_at,
        members=[root, child_a, child_b],
    )


# --- 스키마 형태·상속 규약 (6.2) ---


def test_trash_member_read_inherits_orm_read_model() -> None:
    assert issubclass(TrashMemberRead, ORMReadModel)
    assert TrashMemberRead.model_config.get("from_attributes") is True
    assert set(TrashMemberRead.model_fields) == {"id", "parent_id", "title"}


def test_trash_bundle_read_inherits_orm_read_model() -> None:
    assert issubclass(TrashBundleRead, ORMReadModel)
    assert TrashBundleRead.model_config.get("from_attributes") is True
    assert set(TrashBundleRead.model_fields) == {
        "bundle_id",
        "root_document_id",
        "root_title",
        "workspace_id",
        "trashed_at",
        "expires_at",
        "member_count",
        "members",
    }


# --- from_bundle 투영: s07 Bundle → 표시 스키마 (1.3) ---


def test_from_bundle_projects_every_field() -> None:
    bundle = _bundle()
    expires_at = datetime(2026, 7, 31, 12, 0, 0)

    read = TrashBundleRead.from_bundle(bundle, expires_at=expires_at)

    assert read.bundle_id == bundle.root_document_id == 10
    assert read.root_document_id == 10
    assert read.root_title == "루트 문서"
    assert read.workspace_id == 5
    assert read.trashed_at == bundle.trashed_at
    assert read.expires_at == expires_at
    assert read.member_count == len(bundle.members) == 3


def test_from_bundle_projects_members_as_trash_member_read() -> None:
    bundle = _bundle()
    expires_at = datetime(2026, 7, 31, 12, 0, 0)

    read = TrashBundleRead.from_bundle(bundle, expires_at=expires_at)

    assert all(isinstance(m, TrashMemberRead) for m in read.members)
    assert [(m.id, m.parent_id, m.title) for m in read.members] == [
        (10, None, "루트 문서"),
        (11, 10, "자식 A"),
        (12, 10, "자식 B"),
    ]


def test_from_bundle_root_title_taken_from_root_member() -> None:
    """루트 제목·workspace_id 는 members 순서와 무관하게 root_document_id 로 찾은
    구성원에서 취한다(구성원 목록이 루트-우선 정렬이 아니어도 정확)."""
    trashed_at = datetime(2026, 7, 1, 12, 0, 0)
    child = _doc(
        id=21, parent_id=20, title="자식", workspace_id=9, trashed_at=trashed_at
    )
    root = _doc(
        id=20, parent_id=None, title="진짜 루트", workspace_id=9, trashed_at=trashed_at
    )
    # 루트가 목록 첫 번째가 아니도록 배치.
    bundle = Bundle(
        root_document_id=20, trashed_at=trashed_at, members=[child, root]
    )
    expires_at = datetime(2026, 7, 31, 12, 0, 0)

    read = TrashBundleRead.from_bundle(bundle, expires_at=expires_at)

    assert read.root_title == "진짜 루트"
    assert read.workspace_id == 9
    assert read.member_count == 2


# --- expires_at 은 필수 서버 산정값(요청 입력 아님) (1.4) ---


def test_expires_at_is_required_on_schema() -> None:
    """`expires_at` 은 옵셔널이 아니라 서버 산정 필수 필드다."""
    with pytest.raises(ValidationError):
        TrashBundleRead(
            bundle_id=10,
            root_document_id=10,
            root_title="t",
            workspace_id=5,
            trashed_at=datetime(2026, 7, 1, 12, 0, 0),
            member_count=1,
            members=[],
        )  # type: ignore[call-arg]


def test_from_bundle_requires_expires_at_keyword() -> None:
    """`from_bundle` 은 expires_at 을 키워드 인자로 주입받는다(스키마가 계산하지 않음)."""
    bundle = _bundle()
    with pytest.raises(TypeError):
        TrashBundleRead.from_bundle(bundle)  # type: ignore[call-arg]


# --- 목록은 s01 Page[TrashBundleRead] 규약 (6.2) ---


def test_list_envelope_follows_page_contract() -> None:
    bundle = _bundle()
    expires_at = datetime(2026, 7, 31, 12, 0, 0)
    item = TrashBundleRead.from_bundle(bundle, expires_at=expires_at)

    page: Page[TrashBundleRead] = Page[TrashBundleRead](items=[item], total=1)

    assert page.total == 1
    assert len(page.items) == 1
    assert isinstance(page.items[0], TrashBundleRead)
    assert page.items[0].bundle_id == 10
