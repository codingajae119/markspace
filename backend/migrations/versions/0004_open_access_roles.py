"""워크스페이스 role 2단계화 — editor·viewer → member 이관 (s26-open-access-roles).

s01-contract-foundation 이 정의한 3단계 위계(owner/editor/viewer)를 owner/member
2단계로 재편한다. ``workspace_member.role`` ENUM 을 재정의하고 기존 editor·viewer
멤버십을 데이터 손실 없이 member 로 이관한다(편집 권한 유지, R2.1).

**3-스텝 ENUM 재편 (upgrade)** — MySQL 은 컬럼이 취할 수 없는 ENUM 값으로 UPDATE 할 수
없으므로, 값 이관을 안전하게 수행하려면 잠시 4값(구·신 병존)으로 확장한 뒤 UPDATE 하고
다시 2값으로 축소한다. owner 행은 **어느 스텝에서도 건드리지 않으므로** 워크스페이스당
단일 owner 불변식(R2.3)이 그대로 보존된다.

    1) ENUM 을 owner/editor/viewer/**member** 4값으로 확장 (제약 위반 없이 UPDATE 준비)
    2) editor·viewer 행을 member 로 UPDATE (owner 미변경 → 단일 owner 유지, R2.2/R2.3)
    3) ENUM 을 owner/member 2값으로 축소 (이후 저장 가능한 값 = owner·member 만, R2.4)

**downgrade 는 역순·비대칭이다.** member → editor 로만 복원하고 **viewer 는 복구하지
않는다**(R2.5, 의도된 비대칭). upgrade 시점에 editor/viewer 구분이 이미 member 로 병합·
소실되었으므로, 어떤 member 가 원래 viewer 였는지 알 수 없기 때문이다. 구조(ENUM) 는
owner/editor/viewer 로 완전히 되돌아가 roundtrip 이 통과하지만, 데이터 비대칭은 설계상
수용된다(viewer 는 편집 권한이 없던 role 이므로 member→editor 승격이 안전한 기본값).

비-additive 변경(0002/0003 의 가산 컬럼 패턴과 다름)이므로 head-guard·roundtrip 회귀
테스트가 head="0004"·4-리비전 체인을 반영해야 한다(그 갱신은 후속 task 5.2 소관).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 4값으로 임시 확장 — UPDATE 가 제약을 위반하지 않도록 구·신 값을 병존시킨다.
    op.execute(
        sa.text(
            "ALTER TABLE workspace_member "
            "MODIFY role ENUM('owner','editor','viewer','member') NOT NULL"
        )
    )
    # 2) editor·viewer → member 이관. owner 행은 건드리지 않아 워크스페이스당 단일
    #    owner 불변식(R2.3)이 보존된다.
    op.execute(
        sa.text(
            "UPDATE workspace_member SET role='member' "
            "WHERE role IN ('editor','viewer')"
        )
    )
    # 3) owner/member 2값으로 축소 — 이후 저장 가능한 role 값 집합을 확정한다(R2.4).
    op.execute(
        sa.text(
            "ALTER TABLE workspace_member "
            "MODIFY role ENUM('owner','member') NOT NULL"
        )
    )


def downgrade() -> None:
    # 1) 4값으로 임시 확장 — member 를 editor 로 되돌리기 위한 준비.
    op.execute(
        sa.text(
            "ALTER TABLE workspace_member "
            "MODIFY role ENUM('owner','editor','viewer','member') NOT NULL"
        )
    )
    # 2) member → editor 복원(비대칭, R2.5). viewer 는 **복구하지 않는다** — upgrade 에서
    #    editor/viewer 구분이 이미 member 로 병합되어 소실되었으므로 어떤 member 가 원래
    #    viewer 였는지 알 수 없다. member→editor 승격이 안전한 기본값이다(의도된 비대칭).
    op.execute(sa.text("UPDATE workspace_member SET role='editor' WHERE role='member'"))
    # 3) owner/editor/viewer 3값 구조로 축소 — ENUM 구조 roundtrip 을 완성한다.
    op.execute(
        sa.text(
            "ALTER TABLE workspace_member "
            "MODIFY role ENUM('owner','editor','viewer') NOT NULL"
        )
    )
