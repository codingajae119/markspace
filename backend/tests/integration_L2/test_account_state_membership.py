"""계정 상태(s03) ↔ 멤버십(s05) 결합 스위트 — 유일 owner 전이·보존 (Task 2.5 / Req 6.1~6.4).

`s03` 계정 상태 전이(`is_active`/`is_deleted`)가 워크스페이스 멤버십·타 멤버 활동에 미치는
영향이 계약대로임을 mock 없이 e2e 로 관찰하는 외부 관찰자 스위트다. 부팅된 실 앱
(`app.main.create_app`, s02·s03·s05 라우터 조립)의 실 라우트를 실제 서명 쿠키 세션으로 태우고,
계정 상태 전이는 s04 L1 헬퍼(`set_active`/`set_deleted` = `PATCH /admin/users/{id}`)를 재사용한다.
DB 수준 단언은 하네스 세션 팩토리(`harness.session_local`)로 커밋된 실제 행을 직접 관찰한다.

## 워크스페이스 owner 는 일반 사용자 (admin 잠금 무관)
`ws_scenario` 의 owner 는 시스템 admin 과 별개인 **일반 사용자**이며 이 워크스페이스의 **유일
owner** 다(editor·viewer 는 비-owner). s03 단일 admin 잠금 가드는 시스템 admin 에만 적용되므로,
일반 사용자 owner 의 비활동/삭제는 admin 경로에서 200 으로 **성공**한다(잠금 미적용).

## 4개 단언 그룹 (Req 매핑, design §계정 상태 ↔ 멤버십 결합)
- **6.1 타 멤버 무영향(docs 3.7)**: admin 이 유일 owner 를 비활동(`is_active=false`) 또는 삭제
  (`is_deleted=true`) 처리해도 editor·viewer 세션은 자신의 role 라우트(`GET /workspaces/{id}`)에
  계속 200 으로 접근한다. 두 상태를 모두 커버한다(parametrize).
- **6.2 멤버십·이름 보존(INV-4)**: 삭제된 owner 의 `workspace_member` 행과 `user` 행(이름 포함)이
  DB 에 물리적으로 보존됨을 직접 조회로 확인한다.
- **6.3 삭제/비활동 멤버 로그인 401(s02 상태 게이트)**: 삭제된 owner·비활동 멤버의 로그인 시도가
  각각 401 로 거부됨을 확인한다.
- **6.4 예기치 않은 물리 삭제 부재**: 유일 owner 상태 전이 시나리오 전반에서 `workspace`·
  `workspace_member`·`user` 레코드 수가 불변임을 DB 수준 카운트로 확인한다(soft-delete/상태 전환만).

각 테스트는 함수 스코프 `ws_scenario` 로 독립 워크스페이스를 받으므로 테스트 간 상태 간섭이 없다.
"""

import pytest
from sqlalchemy import func, select

from app.models import User, Workspace, WorkspaceMember
from tests.integration_L2 import helpers


def _apply_owner_transition(admin_client, owner_user_id: int, state: str) -> None:
    """유일 owner 에게 지정한 계정 상태 전이를 s04 L1 헬퍼로 적용한다(성공 200 내부 단언).

    ``state`` 가 ``"inactive"`` 면 ``is_active=false``, ``"deleted"`` 면 ``is_deleted=true``.
    일반 사용자 owner 이므로 admin 잠금 가드에 걸리지 않고 200 으로 성공해야 한다.
    """
    if state == "inactive":
        result = helpers.l1_helpers.set_active(admin_client, owner_user_id, False)
        assert result["is_active"] is False, (
            f"일반 사용자 owner 비활동 전이는 성공해야 한다(admin 잠금 무관): {result}"
        )
    elif state == "deleted":
        result = helpers.l1_helpers.set_deleted(admin_client, owner_user_id, True)
        assert result["is_deleted"] is True, (
            f"일반 사용자 owner 삭제 전이는 성공해야 한다(admin 잠금 무관): {result}"
        )
    else:  # pragma: no cover - 파라미터 오설정 방어
        raise AssertionError(f"알 수 없는 전이 상태: {state!r}")


# --- 6.1 유일 owner 전이 → 타 멤버 무영향 (docs 3.7) ---------------------------------


@pytest.mark.parametrize("state", ["inactive", "deleted"])
def test_sole_owner_transition_does_not_affect_other_members(ws_scenario, state):
    """유일 owner 비활동/삭제 후에도 editor·viewer 세션은 자신의 role 라우트에 200 접근(6.1).

    editor·viewer 세션은 owner 전이 **이전**에 확립되었고, 각자의 접근은 owner 의 계정 상태가
    아니라 **자신의** 멤버십·계정 상태로 게이팅된다. 따라서 admin 이 유일 owner 를 비활동
    (`is_active=false`) 또는 삭제(`is_deleted=true`) 처리해도 editor·viewer 의
    `GET /workspaces/{id}`(viewer 게이트) 는 200 으로 무영향이어야 한다(docs 3.7).
    두 전이 상태를 모두 커버한다.
    """
    ws_id = ws_scenario.workspace_id

    # 유일 owner 에게 지정 상태 전이 적용(일반 사용자이므로 200 성공).
    _apply_owner_transition(
        ws_scenario.admin_client, ws_scenario.owner_user_id, state
    )

    # editor 세션은 owner 전이와 무관하게 자신의 role 라우트에 계속 200 접근.
    editor_resp = helpers.attempt_get_workspace(ws_scenario.editor_client, ws_id)
    assert editor_resp.status_code == 200, (
        f"유일 owner {state} 전이 후에도 editor 는 자신의 role 라우트에 200 접근해야 한다"
        f"(타 멤버 무영향, 6.1, docs 3.7): {editor_resp.status_code} {editor_resp.text}"
    )

    # viewer 세션도 동일하게 무영향(200).
    viewer_resp = helpers.attempt_get_workspace(ws_scenario.viewer_client, ws_id)
    assert viewer_resp.status_code == 200, (
        f"유일 owner {state} 전이 후에도 viewer 는 자신의 role 라우트에 200 접근해야 한다"
        f"(타 멤버 무영향, 6.1, docs 3.7): {viewer_resp.status_code} {viewer_resp.text}"
    )


# --- 6.2 멤버십·이름 보존 (INV-4) — DB 직접 조회 -------------------------------------


def test_deleted_member_membership_and_name_preserved(ws_scenario, harness):
    """삭제된 owner 의 `workspace_member` 행·`user` 행(이름 포함)이 DB 에 물리 보존됨(6.2, INV-4).

    삭제 전에 owner 의 이름을 DB 에서 캡처하고, admin 이 owner 를 삭제(`is_deleted=true`)한 뒤
    하네스 세션 팩토리로 커밋된 실제 행을 직접 관찰한다: (1) `user` 행이 여전히 존재하고
    `is_deleted=True` 이며 이름이 훼손 없이 보존, (2) `(workspace_id, owner_user_id)`
    `workspace_member` 행이 여전히 존재(계정 soft-delete 가 멤버십을 제거하지 않음). INV-4
    (물리 삭제 없음)의 계정↔멤버십 결합 표현을 증명한다.
    """
    ws_id = ws_scenario.workspace_id
    owner_uid = ws_scenario.owner_user_id

    # 삭제 전 owner 이름을 DB 에서 캡처(전/후 대조 기준).
    with harness.session_local() as db:
        before = db.get(User, owner_uid)
        assert before is not None, "삭제 전 owner user 행이 존재해야 한다(전제)"
        original_name = before.name
    assert original_name, "owner 이름은 비어 있지 않아야 한다(캡처 전제)"

    # admin 이 유일 owner 를 삭제(is_deleted=true) — 일반 사용자이므로 200 성공.
    result = helpers.l1_helpers.set_deleted(
        ws_scenario.admin_client, owner_uid, True
    )
    assert result["is_deleted"] is True, (
        f"일반 사용자 owner 삭제는 성공해야 한다: {result}"
    )

    # DB 직접 관찰: user 행 물리 보존 + flag 만 전환 + 이름 불변.
    with harness.session_local() as db:
        user_row = db.get(User, owner_uid)
        assert user_row is not None, (
            "삭제된 owner 의 user 행은 물리적으로 보존되어야 한다(INV-4, 물리 삭제 없음)"
        )
        assert user_row.is_deleted is True, (
            "삭제는 flag 전환으로만 표현되어야 한다(is_deleted=True)"
        )
        assert user_row.name == original_name, (
            f"삭제된 사용자의 이름은 보존되어야 한다(INV-4): "
            f"기대={original_name!r} 실제={user_row.name!r}"
        )

        # workspace_member 행 물리 보존(계정 삭제가 멤버십을 제거하지 않음).
        member_row = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_id,
                WorkspaceMember.user_id == owner_uid,
            )
        )
        assert member_row is not None, (
            f"삭제된 멤버의 workspace_member 행은 보존되어야 한다"
            f"(계정 soft-delete 는 멤버십을 물리 제거하지 않음, INV-4): "
            f"(workspace_id={ws_id}, user_id={owner_uid})"
        )
        assert member_row.role == "owner", (
            f"보존된 멤버십의 role 은 owner 그대로여야 한다: {member_row.role!r}"
        )


# --- 6.3 삭제/비활동 멤버 로그인 → 401 (s02 상태 게이트) ------------------------------


def test_deleted_or_inactive_member_login_is_rejected(ws_scenario, harness):
    """삭제된 owner·비활동 editor 의 로그인 시도가 각각 401 로 거부됨(6.3, s02 상태 게이트).

    `ws_scenario` 는 login_id 를 노출하지 않으므로 DB 에서 대상 사용자의 login_id 를 조회한 뒤,
    s04 L1 헬퍼 `attempt_login`(쿠키 오염 없는 신규 클라이언트)으로 로그인을 시도한다. 모든
    `ws_scenario` 사용자는 `DEFAULT_PASSWORD` 를 공유하므로, 401 은 자격 오류가 아니라 s02 계정
    상태 게이트(삭제/비활동) 때문임이 증명된다(anti-enumeration byte-identical 401).
    """
    owner_uid = ws_scenario.owner_user_id
    editor_uid = ws_scenario.editor_user_id

    # 대상들의 login_id 를 DB 에서 조회.
    with harness.session_local() as db:
        owner_login_id = db.get(User, owner_uid).login_id
        editor_login_id = db.get(User, editor_uid).login_id

    # 삭제된 owner 로그인 → 401.
    helpers.l1_helpers.set_deleted(ws_scenario.admin_client, owner_uid, True)
    deleted_resp = helpers.l1_helpers.attempt_login(
        harness, owner_login_id, helpers.l1_helpers.DEFAULT_PASSWORD
    )
    assert deleted_resp.status_code == 401, (
        f"삭제된 멤버의 로그인은 401 로 거부되어야 한다(6.3, s02 상태 게이트): "
        f"{deleted_resp.status_code} {deleted_resp.text}"
    )

    # 비활동 editor 로그인 → 401(별개 사용자).
    helpers.l1_helpers.set_active(ws_scenario.admin_client, editor_uid, False)
    inactive_resp = helpers.l1_helpers.attempt_login(
        harness, editor_login_id, helpers.l1_helpers.DEFAULT_PASSWORD
    )
    assert inactive_resp.status_code == 401, (
        f"비활동 멤버의 로그인은 401 로 거부되어야 한다(6.3, s02 상태 게이트): "
        f"{inactive_resp.status_code} {inactive_resp.text}"
    )


# --- 6.4 유일 owner 전이 전반에서 예기치 않은 물리 삭제 부재 --------------------------


def _count(harness, model) -> int:
    """DB 수준 `SELECT COUNT(*)` 로 지정 모델 테이블의 커밋된 행 수를 직접 센다."""
    with harness.session_local() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_no_unexpected_physical_deletion_across_owner_transition(ws_scenario, harness):
    """유일 owner 비활동/삭제 시나리오 전반에서 workspace·workspace_member·user 행 수 불변(6.4).

    전이 이전에 세 테이블의 행 수를 캡처하고, 유일 owner 를 비활동(`is_active=false`)한 뒤
    삭제(`is_deleted=true`)까지 전이한 후 세 카운트가 **정확히 동일**함을 단언한다. 이 시나리오에는
    명시적 멤버 제거가 없으므로 어떤 `workspace`·`workspace_member`·`user` 행도 물리 삭제되어서는
    안 된다(soft-delete/상태 전환만). 카운트가 줄면 예기치 않은 물리 삭제 회귀를 표면화한다.
    """
    owner_uid = ws_scenario.owner_user_id

    # 전이 이전 세 테이블의 행 수 캡처.
    before_ws = _count(harness, Workspace)
    before_member = _count(harness, WorkspaceMember)
    before_user = _count(harness, User)

    # 유일 owner 비활동 → 삭제 전이(둘 다 상태 전환일 뿐 물리 삭제 아님).
    helpers.l1_helpers.set_active(ws_scenario.admin_client, owner_uid, False)
    helpers.l1_helpers.set_deleted(ws_scenario.admin_client, owner_uid, True)

    # 전이 이후 세 테이블의 행 수가 모두 불변이어야 한다(물리 삭제 부재).
    after_ws = _count(harness, Workspace)
    after_member = _count(harness, WorkspaceMember)
    after_user = _count(harness, User)

    assert after_ws == before_ws, (
        f"owner 상태 전이는 workspace 행을 물리 삭제하면 안 된다(6.4): "
        f"{before_ws} → {after_ws}"
    )
    assert after_member == before_member, (
        f"owner 상태 전이는 workspace_member 행을 물리 삭제하면 안 된다(6.4): "
        f"{before_member} → {after_member}"
    )
    assert after_user == before_user, (
        f"owner 상태 전이는 user 행을 물리 삭제하면 안 된다(6.4, INV-4): "
        f"{before_user} → {after_user}"
    )
