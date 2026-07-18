"""user_setting — 사용자별 설정 1:1 테이블 (s01 계약 additive 확장).

``user`` 테이블에 컬럼을 추가하지 않고 별도 ``user_setting`` 테이블을 신설한다
(비파괴적). ``user_id`` 는 FK(user.id) + UNIQUE 로 사용자당 최대 한 행을 강제하며,
``autosave_enabled`` 는 DDL-level DEFAULT 0(server_default) 으로 명시한다(모델은
Python-side default 만 두므로). downgrade() 는 테이블을 통째로 제거해 재현 가능한
역전을 보장한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_KW = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    op.create_table(
        "user_setting",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "autosave_enabled",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 사용자당 1행 보장(UNIQUE).
        sa.UniqueConstraint("user_id", name="uq_user_setting_user_id"),
        **_TABLE_KW,
    )


def downgrade() -> None:
    op.drop_table("user_setting")
