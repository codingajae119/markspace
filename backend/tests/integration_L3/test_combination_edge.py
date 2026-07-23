"""결합 엣지케이스 스위트 (Task 2.6 / Req 7.1, 7.2, 7.3, 7.4, 7.5, 7.6,
design §CombinationEdgeSuite · §bundle 삭제 캐스케이드 flow — API+엔진+DB 관찰).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕**s07**) + 실 세션 +
부팅 앱과 동일 세션 팩토리의 `DocumentStateEngine`) 위에서, 이번 계층에서 처음 결합되는
세 경계를 mock 없이 관찰한다:

1. **trashed_at 초 단위 묶음 경계 정밀도**(7.1·7.2, s07 flagged Risk).
2. **삭제(`is_deleted=true`) 사용자의 작성자 표시 보존**(7.3, INV-4; L1 계정 생명주기 ↔ 문서 도메인).
3. **문서 보유 워크스페이스 삭제 거부(409) + 빈 워크스페이스 삭제 성공(204)**(7.5·7.6,
   `s01` `workspace` 참조 FK `ON DELETE RESTRICT`·INV-4). 이 409 경로는 s05 가 s08 로 이연한
   것으로, 문서가 처음 존재하는 L3 에서 **최초로 end-to-end 관측**된다.
   ✅ **회귀 포착·수정 완료(s05)**: 7.5 는 409 거부 시 **멤버십**도 물리 보존을 요구한다. 이
   스위트가 처음 결합했을 때 s05 `WorkspaceService.delete_workspace` 가 멤버십 선삭제
   (`remove_all_for_workspace`)를 **독립 커밋**한 뒤 워크스페이스 물리 DELETE 가 FK RESTRICT 로
   실패하면 rollback 으로도 되돌리지 못해 **멤버십이 제거**되는 원자성 결함을
   :func:`test_workspace_delete_rejection_preserves_memberships` 가 포착했다. 체크포인트는 이를
   우회하지 않고 실패로 보고했고(Requirement 1.5), 수정은 **원인 spec s05**에서 이뤄졌다: 두 repo
   메서드에 `commit=False` 경로를 두고 서비스가 단일 트랜잭션(단일 `db.commit()`)을 소유하여 FK
   RESTRICT 실패 시 한 번의 rollback 으로 멤버십을 복원한다. 이 테스트는 이제 통과하며 그 회귀의
   재발을 막는 sentinel 로 남는다.
4. **삭제·완전삭제 시나리오 전반의 물리 삭제 부재**(7.4, INV-4) — `document`·`document_version`·
   `user` 레코드가 상태 전환만 겪고 물리적으로 보존됨을 직접 `SELECT` 로 확인.

## DATETIME(0) 초 단위 정밀도 한계와 7.2 승격 트리거 (반드시 정독)
`document.trashed_at` 은 `s01` 물리 데이터 모델상 `sa.DateTime()` → MySQL `DATETIME(0)`(초 단위
정밀도)이다. MySQL 은 저장 시 소수 초를 **버림이 아니라 반올림**한다(예: 12:00:00.6 → :01,
12:00:01.4 → :01). 엔진 재구성(`identify_bundles`/`get_bundle`, `app/document/engine.py`)은
trashed 문서를 그 **부모가 동일 `trashed_at` 으로 함께 trashed 되지 않은 한** 묶음 **루트**로
본다. 따라서 자식 삭제와 부모 삭제가 **같은 저장 초**에 떨어지면, 재구성이 자식을 부모 묶음으로
**병합**해 자식이 더는 독립 루트가 아니게 된다. 이는 `s07` 이 명시적으로 flagged 한 **정밀도
Risk** 다.

- **본 스위트가 검증하는 것(7.1 positive property)**: 두 삭제가 **서로 다른 저장 초**에 떨어지면
  재구성이 독립 묶음을 **오병합 없이** 식별한다. 이를 위해 자식의 **저장된(재조회)** `trashed_at`
  에 ~2s 마진을 더한 시각까지 대기한 뒤 부모를 삭제한다(:func:`_wait_until_strictly_after`,
  `DATETIME(0)` 반올림 대응 — task 2.4/2.5 와 동일 접근을 이 모듈에 **로컬 정의**).
- **본 스위트가 검증하는 것(7.1 결정성)**: 삭제 시점 포착은 초 정밀도와 **무관하게 결정적**이다.
  부모 삭제는 그 시점 **active** 하위(`active_descendants`)만 포착하므로, 이미 trashed 된 자식은
  재포착·재스탬프되지 않고 자기 `trashed_at` 을 유지한다. 이 property 는 **같은 초에서도 성립**
  하므로, 초 경계 정밀도 한계와 독립적으로 GREEN 하게 단언할 수 있다.
- **7.2 승격 트리거(체크포인트는 수정하지 않음)**: 만약 **같은 초** 경계에서 독립 묶음이 병합되는
  회귀가 관측되면(현재 알려진 Risk), 이는 실패로 **보고**하고 `trashed_at` 정밀도 승격(`DATETIME(0)`
  → 소수 초)을 **`s01` 계약 개정** 대상으로 기록해야 한다(전 체크포인트 재검증 동반). 이 수정은
  원인 spec(`s01`)의 몫이며 **체크포인트는 우회하지 않는다**(design §Error Categories — 정밀도
  회귀는 s01 승격 대상 기록). 그러므로 본 스위트는 **같은 초에서 "재구성 무병합" 을 강제하는
  hard-failing 단언을 두지 않는다**(알려진 Risk 가 게이트를 깨뜨리지 않도록). 같은 초 관측은 오직
  **동일 초에서도 성립하는 property**(삭제 시점 포착의 결정성)만 단언한다. 이 문서화 자체가 7.2 의
  승격 트리거 기록이다.

## 재검증 트리거 (design §GateVerdict)
`s01`·`s02`·`s03`·`s05`·`s07` 중 하나라도 수정되면 이 스위트(및 로드맵상 그 이후 모든 체크포인트)
를 누적 집합 기준으로 재실행한다. 특히 여기서 관측하는 `trashed_at` 정밀도·FK `ON DELETE RESTRICT`·
`created_by` 보존은 `s01` 계약과 `s07`·`s05` 구현 결합에 직접 의존한다.

하네스(`harness`, L1 conftest)·`ws_scenario`(L2 conftest)·`engine_access`(L3 conftest) 픽스처가
제공하는 실 결합 환경 위에서만 동작하며 mock 을 쓰지 않는다. 계정 상태 전이·워크스페이스 생성/멤버/
삭제 헬퍼는 s06 L2(및 L1) 헬퍼 재사용, 문서 생성은 s07 헬퍼 재사용, 묶음 관찰은 엔진 primitive
직접 호출, 물리 존재 관찰은 raw `SELECT` 다.
"""

import time
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import bindparam, text

from tests.integration_L3 import helpers

l1_helpers = helpers.l1_helpers
l2_helpers = helpers.l2_helpers

# DATETIME(0) 초 경계 안전 마진(초). MySQL 은 저장 시 소수 초를 **반올림**하므로(절삭 아님)
# 벽시계 초를 하나 넘는 것만으로는 부족하다 — 기준 저장값보다 최소 이 마진만큼 뒤에 부모 삭제를
# 태우면 반올림 후에도 저장 초가 엄격히 커짐이 보장된다(모듈 docstring 정밀도 근거 참조).
_SECOND_BOUNDARY_MARGIN = timedelta(seconds=2)


def _title(prefix: str) -> str:
    """공유 ``markspace_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _wait_until_strictly_after(reference: datetime) -> None:
    """저장된 기준 `trashed_at` 보다 다음 삭제 초가 엄격히 커지도록 대기한다(DATETIME(0) 반올림 대응).

    `trashed_at` 은 `DATETIME(0)`(초 단위)이고 MySQL 은 저장 시 소수 초를 **반올림**하므로, 같은
    또는 인접 초의 두 삭제가 동일 저장값을 받으면 엔진이 자식을 부모 묶음 구성원으로 병합해 버린다
    (모듈 docstring 정밀도 근거 참조). 독립 묶음(7.1 positive) 관찰은 자식이 **독립 루트**로
    남아야 하므로, 이 함수로 현재 벽시계가 자식 저장값(`reference`)에 :data:`_SECOND_BOUNDARY_MARGIN`
    을 더한 시각을 넘길 때까지 짧게 폴링한다. task 2.4/2.5 와 동일 접근을 이 모듈에 로컬 정의한다
    (다른 스위트에서 import 하지 않음 — boundary 준수).
    """
    target = reference + _SECOND_BOUNDARY_MARGIN
    while datetime.utcnow() < target:
        time.sleep(0.05)


# --- raw SELECT 관찰 헬퍼 (물리 존재 단언용, 공유 DB 에서 특정 id 만 조회) --------------------


def _fetch_document(harness, document_id: int):
    """document 테이블에서 한 문서 행을 직접 조회한다(없으면 None — 물리 삭제 관측용).

    반환 Row 는 (id, status, created_by, workspace_id, trashed_at). 물리 보존(INV-4)·초 단위
    `trashed_at` 재스탬프 부재(7.1 결정성)를 실제 DB 로 확인하는 데 쓴다.
    """
    stmt = text(
        "SELECT id, status, created_by, workspace_id, trashed_at "
        "FROM document WHERE id = :id"
    )
    with harness.session_local() as db:
        return db.execute(stmt, {"id": document_id}).first()


def _fetch_user(harness, user_id: int):
    """user 테이블에서 한 사용자 행을 직접 조회한다(없으면 None — 물리 삭제 관측용).

    반환 Row 는 (id, name, is_deleted). 삭제(`is_deleted=true`) 처리된 작성자의 이름이 물리
    보존됨(7.3, INV-4)을 확인하는 데 쓴다.
    """
    stmt = text("SELECT id, name, is_deleted FROM user WHERE id = :id")
    with harness.session_local() as db:
        return db.execute(stmt, {"id": user_id}).first()


def _document_version_ids(harness, document_ids):
    """주어진 문서 id 들에 대한 document_version 행 id 집합을 직접 조회한다.

    s09 가 버전 생성을 소유하므로 L3 에서는 보통 0 행이다. 물리 삭제 부재(7.4)를 확인하기 위해
    삭제·완전삭제 전후로 이 집합이 보존됨을 단언한다(존재하는 행이 있으면 그것이 보존됨을,
    없으면 없음 그대로 유지됨을 관측).
    """
    stmt = text(
        "SELECT id FROM document_version WHERE document_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with harness.session_local() as db:
        rows = db.execute(stmt, {"ids": list(document_ids)}).all()
    return {int(row[0]) for row in rows}


def _workspace_exists(harness, workspace_id: int) -> bool:
    """workspace 행이 물리적으로 존재하는지 직접 조회한다(삭제 거부·성공 판정용)."""
    stmt = text("SELECT id FROM workspace WHERE id = :id")
    with harness.session_local() as db:
        return db.execute(stmt, {"id": workspace_id}).first() is not None


def _membership_user_ids(harness, workspace_id: int):
    """워크스페이스 멤버십 user_id 집합을 직접 조회한다(멤버십 물리 보존/제거 판정용)."""
    stmt = text(
        "SELECT user_id FROM workspace_member WHERE workspace_id = :ws"
    )
    with harness.session_local() as db:
        rows = db.execute(stmt, {"ws": workspace_id}).all()
    return {int(row[0]) for row in rows}


# =============================================================================
# 7.1 — 초 단위 경계: 서로 다른 초의 두 삭제는 독립 묶음으로 오병합 없이 식별
# =============================================================================


def test_independent_bundles_reconstructed_without_merge_at_distinct_seconds(
    ws_scenario, engine_access, harness
):
    """부모-자식을 서로 다른 저장 초에 삭제하면 재구성이 독립 묶음을 오병합 없이 식별(7.1).

    editor 가 A(부모)→B(자식) 트리를 만든 뒤 **B 를 먼저** 삭제(t1)한다. `DATETIME(0)` 반올림을
    넘기는 마진 대기(:func:`_wait_until_strictly_after`, 저장된 t1 기준) 후 **A 를** 삭제(t2)한다.
    두 삭제가 서로 다른 저장 초에 떨어지므로, 엔진 재구성은 루트+동일 `trashed_at` 연결 서브트리
    기준으로 A·B 를 **두 독립 묶음**으로 식별해야 한다(오병합 없음):

    - `get_bundle(A).member_ids == {A}` — A 삭제(t2) 시점 active 하위는 A 자신뿐(B 는 이미 trashed).
      B 가 A 묶음으로 병합되지 않는다.
    - `get_bundle(B).member_ids == {B}` — B 는 여전히 자기만의 독립 루트 묶음.
    - `identify_bundles(ws)` 가 A·B **두 별개 루트**를 식별한다.
    - `B.trashed_at < A.trashed_at`(서로 다른 초라 엄격 미만) — 삭제 순서·독립성 확인.

    이는 초가 다를 때 재구성이 독립 묶음을 정확히 식별함을 증명한다(7.1 positive property).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    parent = helpers.create_document(editor, ws_id, _title("경계부모A"))
    child = helpers.create_document(
        editor, ws_id, _title("경계자식B"), parent_id=parent["id"]
    )
    parent_id = parent["id"]
    child_id = child["id"]

    # (t1) 자식 B 먼저 삭제 → B 가 자기 루트 묶음(자식만)으로 trashed.
    helpers.delete_document(editor, child_id)
    child_bundle = helpers.get_bundle(engine_access, child_id)
    assert child_bundle.member_ids == {child_id}, (
        f"자식 B 삭제(t1)는 자식만 자기 묶음으로 포착해야 한다(7.1): {child_bundle.member_ids}"
    )
    t1 = child_bundle.trashed_at

    # DATETIME(0) 반올림 — 부모 삭제가 자식 저장 초보다 엄격히 뒤에 떨어져야 독립 루트로 남는다.
    _wait_until_strictly_after(t1)

    # (t2) 부모 A 삭제 → 그 시점 active 하위는 A 자신뿐(자식 B 는 이미 trashed).
    helpers.delete_document(editor, parent_id)

    parent_bundle = helpers.get_bundle(engine_access, parent_id)
    assert parent_bundle.member_ids == {parent_id}, (
        f"서로 다른 초의 부모 삭제(t2)는 이미 trashed 된 자식 B 를 병합하지 않아야 한다"
        f"(7.1 무오병합): 관측 A 묶음={parent_bundle.member_ids}"
    )
    t2 = parent_bundle.trashed_at

    child_bundle_after = helpers.get_bundle(engine_access, child_id)
    assert child_bundle_after.member_ids == {child_id}, (
        f"부모 삭제 후에도 자식 B 는 자기만의 독립 묶음이어야 한다(7.1 무오병합): "
        f"{child_bundle_after.member_ids}"
    )

    identified = helpers.identify_bundles(engine_access, ws_id)
    roots = {b.root_document_id for b in identified}
    assert roots == {parent_id, child_id}, (
        f"서로 다른 초의 두 삭제는 두 별개 루트로 독립 식별되어야 한다(7.1): {roots}"
    )

    assert t1 < t2, (
        f"자식 저장 trashed_at(t1)은 부모 저장 trashed_at(t2)보다 엄격히 앞서야 한다"
        f"(서로 다른 초 보장, 7.1): t1={t1} t2={t2}"
    )


# =============================================================================
# 7.1 결정성 · 7.2 정밀도 한계 — 같은 초에서도 성립하는 삭제 시점 포착 결정성
# =============================================================================


def test_parent_delete_does_not_restamp_earlier_trashed_child(
    ws_scenario, harness
):
    """부모의 나중 삭제가 이미 trashed 된 자식의 trashed_at 을 재스탬프하지 않음 — 초 무관 결정성(7.1, 7.2).

    A(부모)→B(자식) 트리에서 **B 를 먼저** 삭제한 뒤, **대기 없이 곧바로** A 를 삭제한다(같은 초에
    떨어질 수 있는 경계). 삭제 시점 포착은 그 시점 **active** 하위만 대상으로 하므로
    (`active_descendants`), A 의 나중 삭제는 이미 trashed 된 B 를 **재포착·재스탬프하지 않는다**.
    이 property 는 `DATETIME(0)` 초 정밀도와 **무관하게** 성립하므로, raw `SELECT` 로 B 의 저장
    `trashed_at` 을 A 삭제 **전·후** 두 번 읽어 값이 **불변**임을 단언한다(각 삭제가 자기 묶음
    구성원을 삭제 시점에 결정적으로 확정 — 7.1).

    ## 왜 "같은 초 무병합" 을 hard-fail 로 단언하지 않는가 (7.2 승격 트리거)
    `DATETIME(0)` 반올림으로 A·B 가 같은 저장 초를 받으면, **재구성**(`get_bundle(B)`)은 B 를 A
    묶음으로 병합해 B 가 더는 독립 루트가 아니게 될 수 있다(모듈 docstring 정밀도 Risk). 이는 `s07`
    이 flagged 한 알려진 Risk 이며 그 수정은 `trashed_at` 정밀도 승격 = **`s01` 계약 개정**의 몫
    이다(체크포인트는 우회·수정하지 않음). 따라서 본 테스트는 재구성 무병합을 강제하지 **않고**,
    같은 초에서도 성립하는 property(삭제 시점 포착의 결정성 = B 의 저장 trashed_at 불변)만 관측한다.
    이 단언은 A·B 가 같은 초든 다른 초든 항상 GREEN 이며, 초 경계 병합 회귀 관측 시의 승격 대상
    기록은 모듈 docstring 에 명시했다(7.2).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    parent = helpers.create_document(editor, ws_id, _title("결정부모A"))
    child = helpers.create_document(
        editor, ws_id, _title("결정자식B"), parent_id=parent["id"]
    )
    parent_id = parent["id"]
    child_id = child["id"]

    # B 먼저 삭제 → B 저장 trashed_at 을 raw SELECT 로 확정(재구성과 무관하게 물리값 관측).
    helpers.delete_document(editor, child_id)
    child_row_before = _fetch_document(harness, child_id)
    assert child_row_before is not None, (
        "삭제된 자식 B 는 물리적으로 보존되어야 한다(INV-4)"
    )
    assert child_row_before.status == "trashed", (
        f"자식 B 는 삭제 후 status=trashed 여야 한다: {child_row_before.status}"
    )
    child_trashed_at_before = child_row_before.trashed_at
    assert child_trashed_at_before is not None, "trashed 문서는 trashed_at 을 가져야 한다"

    # 대기 없이 곧바로 부모 A 삭제(같은 초에 떨어질 수 있는 경계) — 그 시점 active 하위는 A 뿐.
    helpers.delete_document(editor, parent_id)

    # A 삭제가 이미 trashed 된 B 의 trashed_at 을 재스탬프하지 않았음을 확인(삭제 시점 포착 결정성, 7.1).
    child_row_after = _fetch_document(harness, child_id)
    assert child_row_after is not None, (
        "부모 삭제 후에도 자식 B 는 물리적으로 보존되어야 한다(INV-4)"
    )
    assert child_row_after.trashed_at == child_trashed_at_before, (
        f"부모의 나중 삭제는 이미 trashed 된 자식 B 의 trashed_at 을 재스탬프하지 않아야 한다"
        f"(삭제 시점 포착 결정성, 7.1 — 초 정밀도와 무관): "
        f"전={child_trashed_at_before} 후={child_row_after.trashed_at}"
    )

    # 부모 A 도 자기 삭제 시점에 결정적으로 trashed 됨(자기 묶음 구성원 확정).
    parent_row = _fetch_document(harness, parent_id)
    assert parent_row is not None and parent_row.status == "trashed", (
        f"부모 A 는 삭제 후 status=trashed·물리 보존이어야 한다(7.1, INV-4): {parent_row}"
    )
    assert parent_row.trashed_at is not None, "trashed 부모는 trashed_at 을 가져야 한다"


# =============================================================================
# 7.3, INV-4 — 삭제(is_deleted=true) 사용자의 작성자 표시 보존
# =============================================================================


def test_deleted_user_authorship_preserved(ws_scenario, harness):
    """작성자를 admin 이 삭제(is_deleted=true)해도 문서의 created_by 참조·사용자 이름이 물리 보존됨(7.3, INV-4).

    admin 이 이름을 아는 신규 editor 사용자를 만들어 워크스페이스 멤버(EDITOR)로 추가하고, 그
    사용자의 세션으로 문서를 생성한다 → 문서 `created_by` 가 그 사용자 id 다(raw SELECT 로 확인).
    이후 admin 이 그 사용자를 삭제 처리(`is_deleted=true`)한 뒤:

    - 문서 행의 `created_by` 가 **여전히** 그 사용자 id 를 참조한다(작성자 참조 보존).
    - `user` 행이 **여전히 물리적으로 존재**하고 `name` 이 보존되며 `is_deleted=1` 로만 전이한다
      (물리 삭제 아님 — 작성자 표시 보존, INV-4).

    다른 테스트를 방해하지 않도록 ws_scenario 의 editor 가 아닌 **신규** 사용자를 만들어 삭제한다.
    """
    admin = ws_scenario.admin_client
    ws_id = ws_scenario.workspace_id

    author_name = f"작성자보존-{uuid4().hex[:8]}"
    login_id = l1_helpers.unique_login_id("author")
    author_uid = l1_helpers.create_user(
        admin, login_id, l1_helpers.DEFAULT_PASSWORD, name=author_name
    )
    # owner 가 신규 사용자를 member 멤버로 추가(문서 생성 게이트 충족).
    l2_helpers.add_member(ws_scenario.owner_client, ws_id, author_uid, "member")
    author_client = harness.login(login_id, l1_helpers.DEFAULT_PASSWORD)

    doc = helpers.create_document(author_client, ws_id, _title("작성자문서"))
    doc_id = doc["id"]

    # 생성 직후 created_by 가 이 작성자임을 raw SELECT 로 확인.
    row_before = _fetch_document(harness, doc_id)
    assert row_before is not None and int(row_before.created_by) == author_uid, (
        f"문서 created_by 는 생성 작성자여야 한다(7.3): "
        f"기대={author_uid} 관측={row_before.created_by if row_before else None}"
    )

    # admin 이 작성자를 삭제 처리(is_deleted=true).
    l1_helpers.set_deleted(admin, author_uid, True)

    # 작성자 참조 보존 — 문서 created_by 가 여전히 그 사용자 id.
    row_after = _fetch_document(harness, doc_id)
    assert row_after is not None and int(row_after.created_by) == author_uid, (
        f"작성자 삭제 후에도 문서 created_by 참조는 보존되어야 한다(7.3, INV-4): "
        f"기대={author_uid} 관측={row_after.created_by if row_after else None}"
    )

    # 사용자 물리 보존 — user 행이 여전히 존재하고 name 보존, is_deleted 만 전이(물리 삭제 아님).
    user_row = _fetch_user(harness, author_uid)
    assert user_row is not None, (
        f"삭제 처리된 작성자 user 행은 물리적으로 보존되어야 한다(7.3, INV-4): id={author_uid}"
    )
    assert user_row.name == author_name, (
        f"작성자 이름은 삭제 후에도 보존되어야 한다(작성자 표시 보존, INV-4): "
        f"기대={author_name!r} 관측={user_row.name!r}"
    )
    assert bool(user_row.is_deleted) is True, (
        f"삭제 처리는 is_deleted=true 상태 전이여야 한다(물리 삭제 아님): {user_row.is_deleted}"
    )


# =============================================================================
# 7.4, INV-4 — 삭제·완전삭제 전반에서 document·document_version·user 물리 삭제 부재
# =============================================================================


def test_no_physical_delete_across_delete_and_purge(
    ws_scenario, engine_access, harness
):
    """삭제→완전삭제 전반에서 document·document_version·user 레코드가 물리적으로 보존됨(7.4, INV-4).

    editor 가 루트→자식 2단계 트리를 만들고, 루트를 `DELETE /documents/{id}` 로 삭제(캐스케이드
    trashed)한 뒤, 엔진 `purge_bundle(root)` 로 묶음을 완전삭제(deleted 종착)한다. 삭제·완전삭제는
    **상태 전환**이지 물리 삭제가 아니므로(INV-4), 시나리오 **전반**에서 다음이 물리 보존됨을 raw
    `SELECT` 로 확인한다:

    - `document`: 루트·자식 행이 완전삭제 후에도 **여전히 존재**하며 `status=deleted` 로만 전이.
    - `document_version`: 삭제·완전삭제 전후로 해당 문서들의 version 행 집합이 **불변**(s09 가 버전
      생성을 소유하므로 L3 에서는 보통 0 행 — 있으면 보존, 없으면 없음 유지; 물리 삭제 부재 관측).
    - `user`: 작성자(editor) 행이 **여전히 존재**(문서 상태 전이가 사용자 행을 건드리지 않음).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    editor_uid = ws_scenario.editor_user_id

    root = helpers.create_document(editor, ws_id, _title("보존루트"))
    child = helpers.create_document(
        editor, ws_id, _title("보존자식"), parent_id=root["id"]
    )
    root_id = root["id"]
    child_id = child["id"]
    doc_ids = {root_id, child_id}

    # 시나리오 전 document_version 집합(물리 삭제 부재 비교 기준).
    versions_before = _document_version_ids(harness, doc_ids)

    # 삭제(캐스케이드 trashed) → 완전삭제(deleted 종착).
    helpers.delete_document(editor, root_id)
    purged = helpers.purge_bundle(engine_access, root_id)
    assert purged.member_ids == doc_ids, (
        f"완전삭제 묶음은 루트+자식을 포함해야 한다(7.4 셋업): "
        f"관측={purged.member_ids} 기대={doc_ids}"
    )

    # document 물리 보존 — 두 행 모두 존재하고 deleted 종착.
    for doc_id in doc_ids:
        row = _fetch_document(harness, doc_id)
        assert row is not None, (
            f"완전삭제 후에도 document 행은 물리 보존되어야 한다(7.4, INV-4): id={doc_id}"
        )
        assert row.status == "deleted", (
            f"완전삭제 구성원은 status=deleted 종착이어야 한다(물리 삭제 아님): "
            f"id={doc_id} status={row.status}"
        )

    # document_version 물리 삭제 부재 — 전후 집합 불변.
    versions_after = _document_version_ids(harness, doc_ids)
    assert versions_after == versions_before, (
        f"삭제·완전삭제 전반에서 document_version 행은 물리 삭제되지 않아야 한다(7.4, INV-4): "
        f"전={versions_before} 후={versions_after}"
    )

    # user 물리 보존 — 작성자 행이 여전히 존재(문서 상태 전이가 user 를 건드리지 않음).
    user_row = _fetch_user(harness, editor_uid)
    assert user_row is not None, (
        f"삭제·완전삭제 전반에서 작성자 user 행은 물리 보존되어야 한다(7.4, INV-4): id={editor_uid}"
    )


# =============================================================================
# 7.5, FK RESTRICT·INV-4 — 문서 보유 워크스페이스 삭제 거부(409)·물리 보존
# =============================================================================


def test_workspace_with_document_delete_rejected_409_preserves_ws_and_document(
    ws_scenario, harness
):
    """문서(active)를 보유한 워크스페이스 삭제는 409 로 거부되고 ws·문서가 물리 보존됨(7.5, FK RESTRICT·INV-4).

    owner 가 **새 워크스페이스**를 만들고(요청자 owner 자동 등록) 그 안에 문서를 하나 생성한다
    (owner 는 OWNER≥EDITOR 로 문서 생성 게이트 통과). `DELETE /workspaces/{id}` 를 요청하면, 서비스가
    물리 DELETE 를 시도하다 `s01` `document.workspace_id` FK `ON DELETE RESTRICT` 위반으로
    `IntegrityError` → rollback → **409 conflict** 로 거부한다. 확인:

    - 응답 409, `ErrorResponse` 형태(`code == "conflict"`).
    - workspace·document 행이 **물리 보존**(FK RESTRICT·INV-4 정합).

    멤버십 보존(7.5 의 나머지 절)은 별도 테스트
    (:func:`test_workspace_delete_rejection_preserves_memberships`)에서 단언한다 — 그 테스트가
    초기 결합 시 s05 원자성 결함을 포착했고 수정이 원인 spec(s05)에서 이뤄졌다(모듈 docstring 참조).
    """
    owner = ws_scenario.owner_client

    ws_id = l2_helpers.create_workspace(owner, f"문서보유WS-{uuid4().hex[:8]}")
    doc = helpers.create_document(owner, ws_id, _title("보유문서"))
    doc_id = doc["id"]

    resp = owner.delete(f"/workspaces/{ws_id}")
    assert resp.status_code == 409, (
        f"문서 보유 워크스페이스 삭제는 409 conflict 여야 한다(7.5, FK RESTRICT): "
        f"{resp.status_code} {resp.text}"
    )
    assert resp.json().get("code") == "conflict", (
        f"409 는 s01 에러 카탈로그상 code=conflict(ErrorResponse) 여야 한다(7.5): {resp.text}"
    )

    assert _workspace_exists(harness, ws_id), (
        f"거부된 삭제 후 workspace 행은 물리 보존되어야 한다(7.5, INV-4): ws={ws_id}"
    )
    doc_row = _fetch_document(harness, doc_id)
    assert doc_row is not None and doc_row.status == "active", (
        f"거부된 삭제 후 document 행은 물리 보존(active)되어야 한다(7.5, INV-4): {doc_row}"
    )


def test_trashed_document_still_blocks_workspace_delete(ws_scenario, harness):
    """trashed 문서만 남은 워크스페이스도 삭제는 여전히 409 — trashing 은 ws 를 비우지 않는다(7.5 nuance, INV-4).

    owner 가 새 워크스페이스에 문서를 만든 뒤, **워크스페이스 삭제를 시도하기 전에** 그 문서를
    `DELETE /documents/{id}` 로 trashed 시킨다(이 시점 owner 는 여전히 멤버이므로 문서 삭제 204).
    trashed 문서는 **행이 물리적으로 그대로 존재**하므로(INV-4) `s01` FK `ON DELETE RESTRICT` 가
    여전히 워크스페이스 물리 DELETE 를 막아 **또 409** 다. 즉 문서를 휴지통에 넣는 것만으로는
    워크스페이스가 비지 않는다 — 빈 워크스페이스 성공(7.6)은 문서 행이 **아예 없는** 별도
    워크스페이스로 관찰한다(:func:`test_empty_workspace_delete_succeeds_204`).

    (문서 삭제를 ws 삭제 **전에** 수행하는 순서는, 과거 s05 멤버십 원자성 회귀(모듈 docstring
    참조, 현재 수정됨) 하에서도 owner 멤버십 소실로 후속 작업이 403 이 되지 않도록 견고했다. 수정
    이후에는 순서 무관하게 멤버십이 보존되지만, 회귀 재발에도 안전한 관찰 순서를 유지한다.)
    """
    owner = ws_scenario.owner_client

    ws_id = l2_helpers.create_workspace(owner, f"trashedWS-{uuid4().hex[:8]}")
    doc = helpers.create_document(owner, ws_id, _title("trashed보유문서"))
    doc_id = doc["id"]

    # ws 삭제 시도 전에 문서를 trashed 로 전이(owner 아직 멤버 → 204).
    helpers.delete_document(owner, doc_id)
    trashed_row = _fetch_document(harness, doc_id)
    assert trashed_row is not None and trashed_row.status == "trashed", (
        f"trashing 은 문서 행을 물리 삭제하지 않는다(INV-4): {trashed_row}"
    )

    resp = owner.delete(f"/workspaces/{ws_id}")
    assert resp.status_code == 409, (
        f"trashed 문서를 보유한 워크스페이스 삭제도 여전히 409 여야 한다"
        f"(trashing 이 ws 를 비우지 않음, 7.5 nuance): {resp.status_code} {resp.text}"
    )
    assert resp.json().get("code") == "conflict", (
        f"409 는 code=conflict(ErrorResponse) 여야 한다(7.5 nuance): {resp.text}"
    )
    assert _workspace_exists(harness, ws_id), (
        "trashed 문서 보유 워크스페이스도 삭제 거부 후 물리 보존되어야 한다(7.5)"
    )
    doc_row_after = _fetch_document(harness, doc_id)
    assert doc_row_after is not None and doc_row_after.status == "trashed", (
        f"거부된 ws 삭제 후에도 trashed 문서 행은 물리 보존되어야 한다(7.5, INV-4): {doc_row_after}"
    )


def test_workspace_delete_rejection_preserves_memberships(ws_scenario, harness):
    """[회귀 sentinel] 409 로 거부된 워크스페이스 삭제는 멤버십을 물리 보존해야 한다(7.5) — s05 수정으로 통과.

    요구사항 7.5 는 문서 보유 워크스페이스의 삭제가 409 로 거부될 때 "그 워크스페이스·문서·**멤버십**이
    물리적으로 보존됨" 을 요구하며, s05 워크스페이스 서비스의 문서화된 사후조건도 "아무것도 제거되지
    않는다" 이다. 초기 결합 시 s05 구현은 이를 **위반**했다:

        (수정 전) WorkspaceService.delete_workspace 는
          1. MembershipRepository.remove_all_for_workspace(db, ws_id)  # 내부에서 db.commit() (독립 커밋)
          2. WorkspaceRepository.delete(db, ws)                         # FK RESTRICT → IntegrityError
        순으로 호출하고, 2 의 실패를 except 에서 db.rollback() 했지만 **1 의 멤버십 삭제는 이미
        커밋되어 있어 rollback 으로 되돌릴 수 없어**, 409 거부에도 멤버십(요청자 owner 포함)이 물리
        제거되었다(→ 후속 owner 작업 403 파생).

    이 회귀는 s05 가 s08 로 이연한 409 경로가 L3 에서 **처음 end-to-end 로 관측**되며 드러났다
    (design §Error Categories — s07 문서 도메인 ↔ s05 워크스페이스 삭제 경계). 체크포인트는 이를
    **실패로 보고**하되 feature 로직으로 우회하지 않았고(Requirement 1.5), 수정은 **원인 spec(s05)**에서
    이뤄졌다: `remove_all_for_workspace`/`delete` 에 `commit=False` 경로를 두고 서비스가 단일
    트랜잭션(단일 `db.commit()`)을 소유하여, FK RESTRICT 실패 시 한 번의 rollback 으로 멤버십·
    워크스페이스 삭제를 함께 되돌린다(아무것도 제거되지 않음). 이 테스트는 이제 통과하며 회귀 sentinel
    로 남는다.
    """
    owner = ws_scenario.owner_client
    owner_uid = ws_scenario.owner_user_id

    ws_id = l2_helpers.create_workspace(owner, f"멤버보존WS-{uuid4().hex[:8]}")
    helpers.create_document(owner, ws_id, _title("멤버보존문서"))

    # 셋업 전제: 생성 요청자가 owner 멤버로 등록되어 있다.
    assert owner_uid in _membership_user_ids(harness, ws_id), (
        "셋업: 생성 요청자가 owner 멤버로 등록되어야 한다"
    )

    resp = owner.delete(f"/workspaces/{ws_id}")
    assert resp.status_code == 409, (
        f"문서 보유 워크스페이스 삭제는 409 여야 한다(7.5 전제): {resp.status_code} {resp.text}"
    )

    # 요구사항 7.5: 409 거부 시 멤버십도 물리 보존되어야 한다("아무것도 제거되지 않는다").
    # s05 단일 트랜잭션 수정 후 이 단언은 통과한다(위 docstring 회귀 sentinel).
    assert owner_uid in _membership_user_ids(harness, ws_id), (
        f"409 로 거부된 워크스페이스 삭제는 멤버십을 물리 보존해야 한다(7.5, 원자성): "
        f"owner={owner_uid} 관측 멤버십={_membership_user_ids(harness, ws_id)} "
        f"— s05 delete_workspace 단일 트랜잭션 원자성 회귀 sentinel. 수정은 s05 소유."
    )


# =============================================================================
# 7.6 — 빈 워크스페이스 삭제 성공(204)·ws·멤버십 제거
# =============================================================================


def test_empty_workspace_delete_succeeds_204(ws_scenario, harness):
    """문서가 없는(빈) 워크스페이스 삭제는 204 로 성공하고 ws·멤버십이 제거됨(7.6).

    owner 가 문서를 **한 번도 넣지 않은 별도** 워크스페이스를 만들어(요청자 owner 자동 등록)
    `DELETE /workspaces/{id}` 를 요청하면, FK RESTRICT 위반 없이(문서 행 부재) 멤버십 제거 후
    워크스페이스가 물리 삭제되어 **204** 로 성공한다. 확인:

    - 응답 204(본문 없음).
    - workspace 행 제거·멤버십(owner) 행 제거를 raw SELECT 로 확인.

    이는 삭제가 **오직 문서 행이 없는 워크스페이스에만** 허용됨을 7.5(거부)와 대비해 보인다
    (s05 워크스페이스 삭제 ↔ s07 문서 존재 경계).
    """
    owner = ws_scenario.owner_client
    owner_uid = ws_scenario.owner_user_id

    ws_id = l2_helpers.create_workspace(owner, f"빈WS-{uuid4().hex[:8]}")
    # 셋업 전제 확인: 방금 만든 워크스페이스는 실제로 존재하고 owner 멤버십이 있다.
    assert _workspace_exists(harness, ws_id), "셋업: 빈 워크스페이스가 생성되어야 한다"
    assert owner_uid in _membership_user_ids(harness, ws_id), (
        "셋업: 생성 요청자가 owner 멤버로 등록되어야 한다"
    )

    resp = owner.delete(f"/workspaces/{ws_id}")
    assert resp.status_code == 204, (
        f"빈 워크스페이스 삭제는 204 로 성공해야 한다(7.6): {resp.status_code} {resp.text}"
    )

    # ws·멤버십 물리 제거 확인.
    assert not _workspace_exists(harness, ws_id), (
        f"빈 워크스페이스 삭제 후 workspace 행이 제거되어야 한다(7.6): ws={ws_id}"
    )
    assert _membership_user_ids(harness, ws_id) == set(), (
        f"빈 워크스페이스 삭제 후 멤버십 행이 제거되어야 한다(7.6): "
        f"{_membership_user_ids(harness, ws_id)}"
    )
