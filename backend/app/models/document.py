"""``document``·``document_version`` 테이블 ORM 모델
(design.md §Physical Data Model, Req 1.5).

Document 는 계층(자기참조 ``parent_id``)·상태(``status``)·잠금 집계 루트.
``current_version_id`` ↔ ``document_version.id`` 순환 FK 는 nullable + ``use_alter``
로 테이블 생성 순서 순환을 회피한다. 물리 삭제 없음(INV-4)이므로 상태·플래그로만
삭제/휴지통을 표현한다.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        Index("ix_document_ws_status_parent", "workspace_id", "status", "parent_id"),
        Index("ix_document_ws_status_trashed_at", "workspace_id", "status", "trashed_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspace.id"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "trashed", "deleted", name="document_status"),
        nullable=False,
        default="active",
    )
    sort_order: Mapped[Decimal] = mapped_column(DECIMAL(30, 15), nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        # 순환 FK(document ↔ document_version) 회피: nullable + use_alter.
        ForeignKey("document_version.id", use_alter=True, name="fk_document_current_version"),
        nullable=True,
    )
    lock_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user.id"), nullable=True
    )
    lock_acquired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_version"
    __table_args__ = (
        Index("ix_document_version_doc_created_at", "document_id", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
