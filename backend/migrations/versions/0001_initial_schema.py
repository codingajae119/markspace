"""initial schema — 7 tables + is_admin (s01-contract-foundation, Task 2.2).

전체 DB 계약(design.md §Physical Data Model)을 재현 가능한 초기 마이그레이션으로
확정한다. upgrade() 는 user·workspace·workspace_member·document·document_version·
attachment·share_link 7개 테이블을 컬럼·타입·ENUM·server_default·UNIQUE·INDEX·FK
그대로 생성하고, downgrade() 는 순환 FK ALTER 를 먼저 해제한 뒤 역의존 순서로
전부 되돌린다(Req 1.1, 1.9, 1.10, 1.11).

물리 삭제 없음(INV-4)이므로 ON DELETE 는 기본(RESTRICT) 유지. 모델은 Python-side
default 만 두므로, DDL-level DEFAULT 는 이 마이그레이션이 server_default 로 명시한다.
순환 FK(document.current_version_id ↔ document_version.id)는 테이블 생성 후 ALTER 로
분리 추가한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_KW = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    # --- user ---
    op.create_table(
        "user",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("login_id", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_id", name="uq_user_login_id"),
        **_TABLE_KW,
    )
    # soft-delete 필터 인덱스(Req 1.11): 로그인·목록 조회.
    op.create_index("ix_user_is_deleted_is_active", "user", ["is_deleted", "is_active"])

    # --- workspace ---
    op.create_table(
        "workspace",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_shareable", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "trash_retention_days",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        **_TABLE_KW,
    )

    # --- workspace_member ---
    op.create_table(
        "workspace_member",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "editor", "viewer", name="workspace_member_role"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name="uq_workspace_member_ws_user"
        ),
        **_TABLE_KW,
    )
    op.create_index("ix_workspace_member_user_id", "workspace_member", ["user_id"])

    # --- document ---
    # 순환 FK(current_version_id → document_version.id)는 여기서 생성하지 않고
    # document_version 생성 후 ALTER 로 추가한다. parent_id 자기참조는 인라인 가능.
    op.create_table(
        "document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "trashed", "deleted", name="document_status"),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.DECIMAL(precision=30, scale=15), nullable=False),
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        sa.Column("lock_user_id", sa.BigInteger(), nullable=True),
        sa.Column("lock_acquired_at", sa.DateTime(), nullable=True),
        sa.Column("trashed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["document.id"]),
        sa.ForeignKeyConstraint(["lock_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        **_TABLE_KW,
    )
    # soft-delete 필터 인덱스(Req 1.11).
    op.create_index(
        "ix_document_ws_status_parent",
        "document",
        ["workspace_id", "status", "parent_id"],
    )
    op.create_index(
        "ix_document_ws_status_trashed_at",
        "document",
        ["workspace_id", "status", "trashed_at"],
    )

    # --- document_version ---
    op.create_table(
        "document_version",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        **_TABLE_KW,
    )
    op.create_index(
        "ix_document_version_doc_created_at",
        "document_version",
        ["document_id", "created_at"],
    )

    # 순환 FK: document.current_version_id → document_version.id (양 테이블 생성 후).
    op.create_foreign_key(
        "fk_document_current_version",
        "document",
        "document_version",
        ["current_version_id"],
        ["id"],
    )

    # --- attachment ---
    op.create_table(
        "attachment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("image", "file", name="attachment_kind"),
            nullable=False,
        ),
        sa.Column(
            "is_archived", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.PrimaryKeyConstraint("id"),
        **_TABLE_KW,
    )
    # soft-delete(보관) 필터 인덱스(Req 1.11).
    op.create_index(
        "ix_attachment_ws_is_archived", "attachment", ["workspace_id", "is_archived"]
    )
    op.create_index("ix_attachment_document_id", "attachment", ["document_id"])

    # --- share_link ---
    op.create_table(
        "share_link",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_share_link_token"),
        **_TABLE_KW,
    )


def downgrade() -> None:
    # 순환 FK ALTER 를 먼저 해제(Req 1.10 재현 가능한 완전 역전).
    op.drop_constraint("fk_document_current_version", "document", type_="foreignkey")

    # 역의존 순서로 테이블 삭제(테이블 삭제 시 소속 인덱스·FK 는 함께 제거).
    op.drop_table("share_link")
    op.drop_table("attachment")
    op.drop_table("document_version")
    op.drop_table("document")
    op.drop_table("workspace_member")
    op.drop_table("workspace")
    op.drop_table("user")
