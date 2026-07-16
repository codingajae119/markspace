"""물리 삭제 없음(INV-4) 보존 스위트 (Task 2.3 / Req 7.1, 7.2, 7.3).

이 스위트는 s01 불변식 **INV-4(물리 삭제 없음)** 이 계정 생명주기 경로 전반에서 유지됨을
mock 없이 검증한다: admin 삭제(`is_deleted=true`)는 flag 만 전환할 뿐 물리 DB DELETE 를
발행하지 않으며, 삭제된 사용자의 이름·식별 정보가 보존된다(design.md §Components →
SoftDeletePreservationSuite, §Error Handling "불변식 위반: 물리 삭제 발생 → 실패").

대조 기준은 s01 단일 소스의 불변식 카탈로그 INV-4(물리 삭제 금지 — 삭제·비활동·보관은
플래그/상태 전환으로만 표현)다. 검증은 API 응답만이 아니라 하네스의 세션 팩토리
(:attr:`~tests.integration_L1.conftest.L1Harness.session_local`)로 **커밋된 실제 행을 직접
관찰**하여 물리 존재를 확인한다(mock 없는 실 결합).

## 대상 사용자는 항상 비-admin
admin 계정의 삭제는 s03 가 409 로 차단하므로, 모든 상태 전이 대상은 헬퍼로 생성한
**비-admin** 사용자다. 하네스가 시드한 admin 자체도 `user` 테이블에서 한 행을 차지하므로,
레코드 개수 검증은 절대값이 아니라 생성 전후의 **델타**로 판정한다.

## 3개 단언 그룹 (Req 매핑)
1. **7.1 — 물리 행 생존·flag 만 전환**: soft-delete 후 DB 를 직접 조회해 행이 여전히
   물리적으로 존재하고 `is_deleted is True`, 다른 컬럼(login_id·name)이 그대로임을 단언.
2. **7.2 — 이름/식별 보존·삭제 상태로 목록 노출**: soft-delete 후 이름이 보존되고,
   `GET /admin/users` 목록에 `is_deleted=True` 로 계속 노출됨을 단언(필터 아웃되지 않음).
3. **7.3 — 생명주기 왕복에서 레코드 수 불감소**: DB 수준 `SELECT COUNT(*)` 로 생성→삭제→
   재활성화 왕복 전반에서 물리 삭제로 행 수가 줄지 않음을 단언(삭제 단계에서 특히 불변).
"""

from sqlalchemy import func, select

from app.models import User
from tests.integration_L1 import helpers


# --- Req 7.1: soft-delete 후 물리 행 생존·flag 만 전환 --------------------------------


def test_soft_delete_keeps_physical_row_only_flag_flips(harness):
    """admin 삭제(`is_deleted=true`) 후 DB 를 직접 조회하면 행이 물리적으로 존재하며
    `is_deleted is True`, login_id·name 은 생성 시 그대로임을 확인한다 (INV-4, Req 7.1).

    API 응답이 아니라 하네스 세션 팩토리로 커밋된 실제 행을 관찰하여 물리 DELETE 가
    발행되지 않았음을 증명한다.
    """
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("inv4-flip")
    name = "물리보존 사용자"
    user_id = helpers.create_user(admin, login_id, name=name)

    # soft-delete: is_deleted=True 로 전이(헬퍼가 200 을 내부 단언).
    patched = helpers.set_deleted(admin, user_id, True)
    assert patched["is_deleted"] is True

    # DB 직접 관찰: 행이 물리적으로 존재하며 flag 만 전환되고 나머지 컬럼은 불변.
    with harness.session_local() as db:
        row = db.get(User, user_id)
        assert row is not None, "soft-delete 는 물리적으로 행을 제거해서는 안 된다(INV-4)"
        assert row.is_deleted is True, "삭제는 flag 전환으로만 표현되어야 한다"
        # 식별 컬럼은 삭제 처리로 훼손되지 않고 그대로 보존된다.
        assert row.login_id == login_id, "login_id 는 삭제 처리로 변경되면 안 된다"
        assert row.name == name, "name 은 삭제 처리로 변경되면 안 된다"


# --- Req 7.2: 이름/식별 보존 · 삭제 상태로 목록에 계속 노출 -----------------------------


def test_soft_deleted_user_name_preserved_and_still_listed(harness):
    """soft-delete 후 이름이 보존되고, `GET /admin/users` 목록에 `is_deleted=True` 로 계속
    노출됨을 확인한다 — soft-delete 된 사용자는 목록에서 필터되지 않는다 (Req 7.2)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("inv4-list")
    name = "이름보존 사용자"
    user_id = helpers.create_user(admin, login_id, name=name)

    helpers.set_deleted(admin, user_id, True)

    # admin 목록에서 삭제된 사용자를 id 로 찾을 수 있어야 한다(필터 아웃 금지).
    resp = admin.get("/admin/users", params={"limit": 100, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["total"], int)

    listed = next((item for item in body["items"] if item["id"] == user_id), None)
    assert listed is not None, "soft-delete 된 사용자는 목록에서 필터되지 않아야 한다"
    assert listed["is_deleted"] is True, "목록에 삭제 상태로 노출되어야 한다"
    assert listed["name"] == name, "삭제된 사용자의 이름/식별 정보가 보존되어야 한다"

    # DB 수준에서도 이름·식별이 커밋된 채 보존됨을 교차 확인한다.
    with harness.session_local() as db:
        row = db.get(User, user_id)
        assert row is not None
        assert row.name == name
        assert row.login_id == login_id


# --- Req 7.3: 생명주기 왕복에서 레코드 수 불감소(물리 삭제 없음) -------------------------


def _user_count(harness) -> int:
    """DB 수준 `SELECT COUNT(*) FROM user` 로 커밋된 user 행 수를 직접 센다."""
    with harness.session_local() as db:
        return db.scalar(select(func.count()).select_from(User))


def test_record_count_never_shrinks_across_lifecycle_roundtrip(harness):
    """생성 → soft-delete → 재활성화 왕복 전반에서 DB user 행 수가 물리 삭제로 줄지
    않음을 확인한다 (Req 7.3).

    시드 admin 이 이미 한 행을 차지하므로 절대값이 아니라 델타로 판정한다: N 명을 만들면
    행 수가 정확히 +N 만큼 늘고, 그 뒤 삭제/재활성화 단계에서 행 수가 결코 줄지 않는다.
    """
    admin = harness.login_admin()

    # 생성 전 기준 행 수(시드 admin 등 선행 행 포함).
    before_create = _user_count(harness)

    # N 명의 비-admin 사용자를 생성한다.
    n = 3
    user_ids = [
        helpers.create_user(
            admin, helpers.unique_login_id(f"inv4-count{i}"), name=f"카운트 사용자{i}"
        )
        for i in range(n)
    ]

    # 생성 직후: 행 수가 정확히 +N (물리 생성만 발생).
    after_create = _user_count(harness)
    assert after_create == before_create + n, (
        f"생성은 정확히 {n} 개 행을 늘려야 한다: {before_create} → {after_create}"
    )

    # 전원 soft-delete: flag 만 전환되므로 행 수는 그대로여야 한다(물리 DELETE 없음).
    for uid in user_ids:
        helpers.set_deleted(admin, uid, True)
    after_delete = _user_count(harness)
    assert after_delete == after_create, (
        f"soft-delete 는 물리 행을 제거하면 안 된다(불변): {after_create} → {after_delete}"
    )

    # 재활성화(삭제 flag 되돌림): 여전히 flag 전환일 뿐 행 수 불변.
    for uid in user_ids:
        helpers.set_deleted(admin, uid, False)
    after_undelete = _user_count(harness)
    assert after_undelete == after_delete, (
        f"재활성화도 물리 행 수를 바꾸면 안 된다(불변): {after_delete} → {after_undelete}"
    )

    # 왕복 전반의 핵심 불변식: 어느 단계에서도 물리 삭제로 행 수가 줄지 않았다.
    assert after_undelete == before_create + n, (
        "생성→삭제→재활성화 왕복 후 행 수는 생성분(+N)만큼만 늘어야 하며 "
        f"물리 삭제로 줄지 않아야 한다: {before_create} + {n} != {after_undelete}"
    )
