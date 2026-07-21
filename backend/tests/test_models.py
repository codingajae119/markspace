"""ORM 모델 메타데이터 단위 테스트 (Requirement 1.1~1.8).

DB 연결 없이 ``Base.metadata`` 를 순수 introspection 하여 물리 데이터 모델
(design.md §Physical Data Model)과의 계약을 결정적으로 검증한다.

각 assertion 은 컬럼 존재·타입·ENUM 값·nullable·유일제약·자기참조 FK 를
구체적으로 확인한다(사소하지 않은 검증).
"""

from sqlalchemy import Enum as SAEnum
from sqlalchemy import UniqueConstraint

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base

METADATA = Base.metadata


def _unique_column_sets(table):
    """테이블의 UNIQUE 제약(단일 컬럼 unique 포함)을 frozenset 집합으로 반환."""
    sets = set()
    for c in table.constraints:
        if isinstance(c, UniqueConstraint):
            sets.add(frozenset(col.name for col in c.columns))
    for col in table.columns:
        if col.unique:
            sets.add(frozenset({col.name}))
    return sets


def _enum_values(column):
    assert isinstance(column.type, SAEnum), f"{column} 은 Enum 타입이 아님"
    return set(column.type.enums)


def test_all_registered_tables():
    """s01 초기 7개 테이블 + additive 확장 ``user_setting`` 이 정확히 등록된다 (Req 1.1).

    s01 은 7개 테이블로 계약을 고정했고, 이후 additive 확장으로 ``user_setting``
    (사용자별 설정 1:1 테이블)이 추가되었다. ``user`` 테이블은 변경되지 않는다.
    """
    assert set(METADATA.tables) == {
        "user",
        "workspace",
        "workspace_member",
        "document",
        "document_version",
        "attachment",
        "share_link",
        "user_setting",
    }


def test_user_setting_table_user_id_unique_and_fk():
    """user_setting: user_id UNIQUE + FK(user.id), autosave_enabled NOT NULL,
    last_selected_workspace_id nullable + FK 없음 (additive)."""
    t = METADATA.tables["user_setting"]
    for name in ("id", "user_id", "autosave_enabled", "last_selected_workspace_id"):
        assert name in t.columns, f"user_setting.{name} 누락"

    # 사용자당 1행: user_id UNIQUE.
    assert frozenset({"user_id"}) in _unique_column_sets(t)
    # user 테이블로의 FK.
    fk_targets = {fk.column.table.name for fk in t.columns["user_id"].foreign_keys}
    assert fk_targets == {"user"}
    assert all(fk.column.name == "id" for fk in t.columns["user_id"].foreign_keys)

    assert t.columns["user_id"].nullable is False
    assert t.columns["autosave_enabled"].nullable is False

    # 마지막 선택 워크스페이스: nullable(미선택 허용)이고 FK 는 의도적으로 없다
    # (선택 힌트 — 소비자가 stale id 를 폴백 처리, 워크스페이스 삭제와의 결합 회피).
    ws_col = t.columns["last_selected_workspace_id"]
    assert ws_col.nullable is True
    assert len(ws_col.foreign_keys) == 0, (
        "last_selected_workspace_id 는 FK 를 두지 않아야 한다(선택 힌트, 삭제 결합 회피)"
    )


def test_user_table_columns_and_login_id_unique():
    """user: login_id UNIQUE, is_admin/is_active/is_deleted, created_at/updated_at (Req 1.2)."""
    t = METADATA.tables["user"]
    for name in (
        "id",
        "login_id",
        "password_hash",
        "name",
        "email",
        "is_admin",
        "is_active",
        "is_deleted",
        "created_at",
        "updated_at",
    ):
        assert name in t.columns, f"user.{name} 누락"

    assert frozenset({"login_id"}) in _unique_column_sets(t)
    assert t.columns["login_id"].nullable is False
    assert t.columns["email"].nullable is True
    assert t.columns["is_admin"].nullable is False
    assert t.columns["is_active"].nullable is False
    assert t.columns["is_deleted"].nullable is False
    assert t.columns["created_at"].nullable is False
    assert t.columns["updated_at"].nullable is True


def test_workspace_defaults():
    """workspace: is_shareable, trash_retention_days 기본값 30 (Req 1.3)."""
    t = METADATA.tables["workspace"]
    assert "is_shareable" in t.columns
    assert "trash_retention_days" in t.columns
    assert t.columns["trash_retention_days"].default.arg == 30


def test_workspace_member_unique_and_role_enum():
    """workspace_member: UNIQUE(workspace_id,user_id), role ENUM (Req 1.4)."""
    t = METADATA.tables["workspace_member"]
    assert frozenset({"workspace_id", "user_id"}) in _unique_column_sets(t)
    assert _enum_values(t.columns["role"]) == {"owner", "editor", "viewer"}
    assert t.columns["role"].nullable is False


def test_document_columns_status_enum_and_self_ref():
    """document: parent_id 자기참조 FK, status ENUM, 잠금·정렬·감사 컬럼 (Req 1.5)."""
    t = METADATA.tables["document"]
    for name in (
        "parent_id",
        "status",
        "sort_order",
        "current_version_id",
        "lock_user_id",
        "lock_acquired_at",
        "trashed_at",
        "created_by",
    ):
        assert name in t.columns, f"document.{name} 누락"

    # parent_id: nullable 자기참조 FK → document.id
    parent = t.columns["parent_id"]
    assert parent.nullable is True
    fk_targets = {fk.column.table.name for fk in parent.foreign_keys}
    assert fk_targets == {"document"}
    assert all(fk.column.name == "id" for fk in parent.foreign_keys)

    assert _enum_values(t.columns["status"]) == {"active", "trashed", "deleted"}
    # current_version_id 는 순환 FK 회피를 위해 nullable
    assert t.columns["current_version_id"].nullable is True
    assert t.columns["created_by"].nullable is False


def test_attachment_columns_and_kind_enum():
    """attachment: workspace_id, document_id, file_path, kind ENUM, is_archived (Req 1.6)."""
    t = METADATA.tables["attachment"]
    for name in ("workspace_id", "document_id", "file_path", "original_name", "kind", "is_archived"):
        assert name in t.columns, f"attachment.{name} 누락"
    assert _enum_values(t.columns["kind"]) == {"image", "file"}
    assert t.columns["is_archived"].nullable is False


def test_share_link_token_unique_and_is_enabled():
    """share_link: token UNIQUE, is_enabled (Req 1.7)."""
    t = METADATA.tables["share_link"]
    assert frozenset({"token"}) in _unique_column_sets(t)
    assert t.columns["token"].nullable is False
    assert "is_enabled" in t.columns
    assert t.columns["is_enabled"].nullable is False


def test_soft_delete_columns_present():
    """soft-delete 컬럼: user.is_deleted, document.status, attachment.is_archived (Req 1.8)."""
    assert "is_deleted" in METADATA.tables["user"].columns
    assert "status" in METADATA.tables["document"].columns
    assert "is_archived" in METADATA.tables["attachment"].columns
