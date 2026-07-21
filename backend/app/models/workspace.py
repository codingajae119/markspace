"""``workspace``·``workspace_member`` 테이블 ORM 모델
(design.md §Physical Data Model, Req 1.3·1.4).

Workspace 는 권한·공유·보관 정책 경계 집계 루트이며, WorkspaceMember 는
(workspace, user) 쌍마다 role(owner/member)을 부여한다(INV-2, s26 2단계 모델).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class Workspace(Base):
    __tablename__ = "workspace"
    __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_shareable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trash_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkspaceMember(Base):
    __tablename__ = "workspace_member"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member_ws_user"),
        Index("ix_workspace_member_user_id", "user_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspace.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.id"), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("owner", "member", name="workspace_member_role"), nullable=False
    )
