"""user_setting — 마지막 선택 워크스페이스 컬럼 추가 (user_settings additive 확장).

0002(user_setting 신설)에 이어, 재로그인/새 브라우저에서 마지막으로 선택한
워크스페이스를 복원하기 위한 ``last_selected_workspace_id`` 컬럼을 additive 로 더한다.
nullable(미선택=NULL)이며 **FK 를 두지 않는다**(모델 주석 참조: 소비자가 stale id 를
무시·폴백하므로 참조 무결성 불필요 + 워크스페이스 삭제와의 cascade 결합 회피).
downgrade() 는 컬럼만 제거해 재현 가능한 역전을 보장한다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_setting",
        sa.Column("last_selected_workspace_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_setting", "last_selected_workspace_id")
