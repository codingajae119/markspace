"""``attachment`` 테이블 ORM 모델 (design.md §Physical Data Model, Req 1.6·1.8).

첨부 파일 참조. 워크스페이스 단위 격리(``workspace_id``, INV-6)이며 보관 폴더
이동(``is_archived``)이 영구 삭제를 대체한다(soft-delete, INV-4).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (
        Index("ix_attachment_ws_is_archived", "workspace_id", "is_archived"),
        Index("ix_attachment_document_id", "document_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspace.id"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum("image", "file", name="attachment_kind"), nullable=False
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
