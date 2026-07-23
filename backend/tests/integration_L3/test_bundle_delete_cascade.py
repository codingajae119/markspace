"""bundle 삭제 캐스케이드 스위트 (Task 2.4 / Req 5.1, 5.2, 5.3, 5.4, 5.5,
design §BundleDeleteCascadeSuite · §bundle 삭제 캐스케이드·비흡수 — API 경유 관찰).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕**s07**) + 실 세션 +
부팅 앱과 동일 세션 팩토리의 `DocumentStateEngine`) 위에서 문서 삭제 캐스케이드가 그 시점
서브트리를 묶음으로 **원자적**으로 포착하되(INV-10) 이미 삭제된 자식을 **흡수하지 않음**
(비흡수, INV-11)을 API 경유(삭제) + 엔진 primitive(묶음 식별) 직접 호출로 관찰한다. mock 없음.

삭제는 실제 라우트(`DELETE /documents/{id}` = 엔진 `trash_document` 캐스케이드, s01 카탈로그 행
23)를, 묶음 식별/검증은 실제 엔진 primitive(`identify_bundles`·`get_bundle`·`active_descendants`)를
탄다(design §BundleDeleteCascadeSuite 제약). 다섯 개의 관찰 축(task 2.4):

- **캐스케이드 포착**(5.1, 5.5): active 하위를 가진 문서 삭제 → 그 시점 active 하위(루트 포함)만
  `status=trashed`·공통 `trashed_at`. `get_bundle`/`identify_bundles`로 구성원·trashed_at 동치 확인.
- **비흡수·INV-11**(5.2): 자식 먼저(t1) 삭제 → 부모 나중(t2) 삭제 시 자식이 흡수되지 않고 자기
  묶음·자기 `trashed_at(t1)`을 유지, `child.trashed_at ≤ parent.trashed_at` 성립. 두 별개 루트 식별.
- **독립 묶음**(5.3, 6.3): 일부 하위만 먼저 삭제된 상태에서 부모 삭제 시 두 묶음이 서로 다른
  루트로 독립 식별.
- **비active 재삭제**(5.4): 이미 trashed된 문서 재삭제 → 409 conflict.
- **원자성·물리보존**(5.5, INV-4·10): 포착 구성원 전이가 단일 원자 조작으로 적용(부분 전이 없음)
  되고 문서가 물리적으로 보존됨(물리 삭제 없음)을 실제 DB `SELECT` 로 확인.

### DATETIME(0) 초 단위 정밀도와 비흡수/독립 묶음 대기 (설계 근거)
`document.trashed_at` 은 s01 물리 모델상 DATETIME(0)(초 단위 정밀도)이다. 엔진은 삭제마다
`trashed_at = datetime.utcnow()` 를 산정하는데, **같은 벽시계 초** 안에서 자식과 부모를 연달아
삭제하면 두 삭제가 저장 시 **동일한 trashed_at(초)** 을 받아, 엔진이 자식을 부모 묶음의 **구성원**
으로 재구성해 버린다(부모가 같은 trashed_at 으로 trashed → 자식은 루트가 아님, `_is_bundle_root`).
그 초 단위 경계 정밀도 Risk 자체는 task 2.6 이 별도로 다룬다. 본 스위트의 비흡수(5.2)·독립
묶음(5.3) 관찰은 자식이 **독립 루트**로 남아야 하므로, 자식 삭제와 부모 삭제가 **서로 다른 초**에
떨어지도록 :func:`_advance_to_next_wall_clock_second` 로 벽시계 초 경계를 넘긴 뒤 부모를 삭제한다.
그래서 `child.trashed_at < parent.trashed_at`(다른 초라 엄격 미만)이자 INV-11 문구
`child.trashed_at ≤ parent.trashed_at` 도 성립한다.

하네스(`harness`, L1 conftest)·`ws_scenario`(L2 conftest)·`doc_tree_scenario`/`engine_access`
(L3 conftest) 픽스처가 제공하는 실 결합 환경 위에서만 동작하며 mock 을 쓰지 않는다.
"""

import time
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import bindparam, text

from tests.integration_L3 import helpers

# DATETIME(0) 초 경계 안전 마진(초). MySQL 은 DATETIME(0) 저장 시 소수 초를 **반올림**하므로
# (절삭 아님) 벽시계 초를 하나 넘는 것만으로는 부족하다 — 예: 12:00:00.6 은 01 로, 12:00:01.4
# 도 01 로 반올림돼 서로 다른 초의 두 삭제가 같은 저장값을 받을 수 있다. 기준 저장값보다
# 최소 이 마진만큼 뒤에 부모 삭제를 태우면 반올림 후에도 저장 초가 엄격히 커짐이 보장된다.
_SECOND_BOUNDARY_MARGIN = timedelta(seconds=2)


def _title(prefix: str) -> str:
    """공유 ``markspace_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _wait_until_strictly_after(reference: datetime) -> None:
    """저장된 기준 `trashed_at` 보다 부모 삭제 초가 엄격히 커지도록 대기한다(DATETIME(0) 반올림 대응).

    `trashed_at` 은 DATETIME(0)(초 단위)이고 MySQL 은 저장 시 소수 초를 **반올림**하므로, 같은
    또는 인접 초의 두 삭제가 동일 저장값을 받으면 엔진이 자식을 부모 묶음 구성원으로 흡수해 버린다
    (모듈 docstring 정밀도 근거 참조). 비흡수(5.2)·독립 묶음(5.3) 관찰은 자식이 **독립 루트**로
    남아야 하므로, 이 함수로 현재 벽시계가 자식 저장값(`reference`)에 :data:`_SECOND_BOUNDARY_MARGIN`
    을 더한 시각을 넘길 때까지 짧게 폴링한다. 그러면 이후 부모 삭제는 반올림 후에도 자식보다
    엄격히 큰 초를 저장받아 두 삭제가 서로 다른 묶음 루트로 남는다.
    """
    target = reference + _SECOND_BOUNDARY_MARGIN
    while datetime.utcnow() < target:
        time.sleep(0.05)


def _select_status_by_ids(harness, ids) -> dict[int, str]:
    """document 테이블에서 주어진 id 들의 (id → status) 를 직접 조회한다(물리 관찰).

    반환 dict 에 없는 id 는 물리 행이 존재하지 않음을 뜻한다(물리 삭제 관측용). INV-4 물리
    보존·INV-10 원자성(부분 전이 없음)을 실제 DB 로 확인하는 데 쓴다.
    """
    stmt = text("SELECT id, status FROM document WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    with harness.session_local() as db:
        rows = db.execute(stmt, {"ids": list(ids)}).all()
    return {int(row[0]): row[1] for row in rows}


# =============================================================================
# 5.1, 5.5 — 캐스케이드 포착: 그 시점 active 하위(루트 포함)만·공통 trashed_at
# =============================================================================


def test_delete_cascades_active_subtree_with_common_trashed_at(
    doc_tree_scenario, engine_access
):
    """active 하위를 가진 문서 삭제 → 그 시점 active 하위(루트 포함)만 trashed·공통 trashed_at(5.1, 5.5).

    editor 가 구성한 3단계 트리(루트→자식→손자)에서 삭제 **직전** active 하위 집합을 엔진
    `active_descendants(root)` 로 스냅샷(=예상 구성원)한 뒤, 루트를 `DELETE /documents/{id}` 로
    삭제한다. 삭제 시점에 세 문서가 모두 active 이므로 캐스케이드가 루트 포함 전부를 포착해야 한다.
    엔진 `get_bundle(root)` 로 (1) 구성원 집합이 예상과 정확히 일치하고, (2) 전원 status=trashed,
    (3) 전원 동일 `trashed_at`(= 묶음 trashed_at)임을 확인한다. `identify_bundles(ws)` 로 이
    워크스페이스에 단일 루트 묶음만 식별됨을 함께 확인한다(design §BundleDeleteCascadeSuite 5.1).
    """
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id

    # 삭제 직전 active 하위(루트 포함) 스냅샷 — 캐스케이드가 포착할 예상 구성원 집합.
    expected_before = helpers.active_descendants(engine_access, root_id)
    expected_ids = {d.id for d in expected_before}
    assert expected_ids == {
        root_id,
        doc_tree_scenario.child_id,
        doc_tree_scenario.grandchild_id,
    }, f"삭제 전 active 하위(루트 포함)는 루트·자식·손자여야 한다(5.1): {expected_ids}"

    helpers.delete_document(editor, root_id)  # 실제 라우트 캐스케이드 삭제(204).

    bundle = helpers.get_bundle(engine_access, root_id)
    assert bundle.member_ids == expected_ids, (
        f"캐스케이드는 그 시점 active 하위(루트 포함)만 포착해야 한다(5.1): "
        f"예상={expected_ids} 관측={bundle.member_ids}"
    )
    assert all(m.status == "trashed" for m in bundle.members), (
        f"포착 구성원 전원 status=trashed 여야 한다(5.1): "
        f"{[(m.id, m.status) for m in bundle.members]}"
    )
    assert all(m.trashed_at == bundle.trashed_at for m in bundle.members), (
        f"포착 구성원 전원 공통 trashed_at 을 공유해야 한다(5.1, 5.5): "
        f"묶음={bundle.trashed_at} 관측={[(m.id, m.trashed_at) for m in bundle.members]}"
    )

    identified = helpers.identify_bundles(engine_access, ws_id)
    roots = {b.root_document_id for b in identified}
    assert roots == {root_id}, (
        f"이 워크스페이스에는 단일 루트 묶음만 식별되어야 한다(5.1): {roots}"
    )


# =============================================================================
# 5.2, INV-11 — 비흡수: 자식 먼저(t1) 삭제 → 부모 나중(t2) 삭제 시 자식 미흡수
# =============================================================================


def test_parent_delete_does_not_absorb_earlier_trashed_child(
    doc_tree_scenario, engine_access
):
    """자식 먼저(t1) 삭제 → 부모 나중(t2) 삭제 시 자식 비흡수·자기 trashed_at 유지(5.2, INV-11).

    3단계 트리(루트→자식→손자)에서 **자식**을 먼저 삭제(t1)하면 자식+손자가 t1 묶음으로 trashed
    된다. 벽시계 초 경계를 넘긴 뒤(모듈 docstring 정밀도 근거 — 두 삭제가 서로 다른 초에 떨어져야
    자식이 독립 루트로 남는다) **루트(부모)** 를 삭제(t2)한다. 이 시점 루트의 active 하위는 루트
    자신뿐(자식 서브트리는 이미 trashed)이므로 루트 묶음은 루트만 포함해야 한다(비흡수).

    확인:
    - 루트 묶음(`get_bundle(root)`)은 자식·손자를 **흡수하지 않는다** — member_ids == {root}.
    - 자식 묶음(`get_bundle(child)`)은 자기 묶음(자식+손자)·자기 `trashed_at(t1)` 을 유지한다.
    - `child.trashed_at < parent.trashed_at`(다른 초라 엄격 미만)이고 INV-11 문구
      `child.trashed_at ≤ parent.trashed_at` 도 성립한다.
    - `identify_bundles(ws)` 가 자식·루트 **두 별개 루트**를 식별한다(INV-10 비병합).
    """
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    child_id = doc_tree_scenario.child_id
    grandchild_id = doc_tree_scenario.grandchild_id

    # (t1) 자식 먼저 삭제 → 자식+손자가 자식 루트 묶음으로 trashed.
    helpers.delete_document(editor, child_id)
    child_bundle = helpers.get_bundle(engine_access, child_id)
    assert child_bundle.member_ids == {child_id, grandchild_id}, (
        f"자식 삭제(t1)는 자식+손자를 자기 묶음으로 포착해야 한다(5.2): "
        f"{child_bundle.member_ids}"
    )
    t1 = child_bundle.trashed_at

    # DATETIME(0) 반올림 — 부모 삭제가 자식 저장 초보다 엄격히 뒤에 떨어져야 자식이 독립 루트로 남는다.
    _wait_until_strictly_after(t1)

    # (t2) 부모(루트) 삭제 → 그 시점 active 하위는 루트뿐(자식 서브트리 이미 trashed).
    helpers.delete_document(editor, root_id)
    root_bundle = helpers.get_bundle(engine_access, root_id)
    assert root_bundle.member_ids == {root_id}, (
        f"부모 삭제(t2)는 이미 trashed된 자식을 흡수하지 않아야 한다(5.2, INV-11): "
        f"관측 루트 묶음={root_bundle.member_ids}"
    )
    t2 = root_bundle.trashed_at

    # 자식은 여전히 자기 묶음(자식+손자)·자기 trashed_at(t1)을 유지한다(비흡수).
    child_bundle_after = helpers.get_bundle(engine_access, child_id)
    assert child_bundle_after.member_ids == {child_id, grandchild_id}, (
        f"부모 삭제 후에도 자식은 자기 묶음(자식+손자)을 유지해야 한다(5.2, INV-11): "
        f"{child_bundle_after.member_ids}"
    )
    assert child_bundle_after.trashed_at == t1, (
        f"부모 삭제 후에도 자식은 자기 trashed_at(t1)을 유지해야 한다(5.2): "
        f"t1={t1} 관측={child_bundle_after.trashed_at}"
    )

    # INV-11: child.trashed_at ≤ parent.trashed_at (다른 초이므로 엄격 미만도 성립).
    assert t1 < t2, (
        f"자식 trashed_at(t1)은 부모 trashed_at(t2)보다 엄격히 앞서야 한다"
        f"(다른 초 보장, INV-11): t1={t1} t2={t2}"
    )
    assert t1 <= t2, f"INV-11: child.trashed_at ≤ parent.trashed_at: t1={t1} t2={t2}"

    # 두 별개 루트로 독립 식별(INV-10 비병합).
    identified = helpers.identify_bundles(engine_access, ws_id)
    roots = {b.root_document_id for b in identified}
    assert roots == {child_id, root_id}, (
        f"자식·부모 삭제는 두 별개 루트로 독립 식별되어야 한다(5.2, INV-10): {roots}"
    )


# =============================================================================
# 5.3, 6.3 — 독립 묶음: 일부 하위만 먼저 삭제된 뒤 부모 삭제 → 두 독립 루트
# =============================================================================


def test_partial_child_delete_then_parent_yields_independent_roots(
    ws_scenario, engine_access
):
    """일부 하위만 먼저 삭제된 상태에서 부모 삭제 → 두 묶음이 서로 다른 루트로 독립 식별(5.3, 6.3).

    루트 아래 두 자식(A·B)을 만든 뒤 **자식 A 만** 먼저 삭제(t1)한다. 벽시계 초 경계를 넘긴 뒤
    (정밀도 근거 — A 가 독립 루트로 남으려면 다른 초) **루트**를 삭제(t2)하면, 그 시점 active 하위는
    루트+자식 B(자식 A 는 이미 trashed)이므로 루트 묶음은 {루트, B}, 자식 A 묶음은 {A} 로 분리된다.
    `identify_bundles(ws)` 가 A·루트 **두 서로 다른 루트**를 식별하고, 각 `get_bundle` 이 구성원을
    독립적으로 재구성함을 확인한다(design §BundleDeleteCascadeSuite 독립 묶음 5.3/6.3).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    root = helpers.create_document(editor, ws_id, _title("독립루트"))
    child_a = helpers.create_document(
        editor, ws_id, _title("자식A"), parent_id=root["id"]
    )
    child_b = helpers.create_document(
        editor, ws_id, _title("자식B"), parent_id=root["id"]
    )

    # (t1) 자식 A 만 먼저 삭제 → A 가 자기 루트 묶음으로 trashed.
    helpers.delete_document(editor, child_a["id"])
    t1 = helpers.get_bundle(engine_access, child_a["id"]).trashed_at

    # DATETIME(0) 반올림 — 부모 삭제가 A 저장 초보다 엄격히 뒤에 떨어져야 A 가 독립 루트로 남는다.
    _wait_until_strictly_after(t1)

    # (t2) 부모(루트) 삭제 → 그 시점 active 하위는 루트+자식 B.
    helpers.delete_document(editor, root["id"])

    identified = helpers.identify_bundles(engine_access, ws_id)
    roots = {b.root_document_id for b in identified}
    assert roots == {child_a["id"], root["id"]}, (
        f"먼저 삭제된 자식 묶음과 부모 삭제 묶음은 서로 다른 루트로 독립 식별되어야 한다"
        f"(5.3, 6.3): 관측 루트={roots}"
    )

    root_bundle = helpers.get_bundle(engine_access, root["id"])
    assert root_bundle.member_ids == {root["id"], child_b["id"]}, (
        f"부모 삭제 묶음은 루트+아직 active 였던 자식 B 를 포함해야 한다(5.3): "
        f"{root_bundle.member_ids}"
    )
    child_a_bundle = helpers.get_bundle(engine_access, child_a["id"])
    assert child_a_bundle.member_ids == {child_a["id"]}, (
        f"먼저 삭제된 자식 A 는 자기만의 독립 묶음이어야 한다(5.3, 6.3): "
        f"{child_a_bundle.member_ids}"
    )
    assert child_a["id"] not in root_bundle.member_ids, (
        f"먼저 삭제된 자식 A 는 부모 묶음에 흡수되지 않아야 한다(5.3, INV-11): "
        f"부모 묶음={root_bundle.member_ids}"
    )


# =============================================================================
# 5.4 — 비active 재삭제: 이미 trashed된 문서 재삭제 → 409 conflict
# =============================================================================


def test_redelete_trashed_document_returns_409(ws_scenario):
    """이미 trashed된 문서를 재삭제하면 409 conflict(비active 삭제 금지, 5.4).

    editor 가 문서를 만들어 삭제(204, active→trashed)한 뒤 같은 문서를 다시 삭제하면, 엔진
    `trash_document` 이 비active 대상을 상태 충돌로 거부해 `DELETE /documents/{id}` 가 409 를
    돌려준다(s01 에러 카탈로그 409=conflict). setup 삭제(204)는 `delete_document`, 재삭제는
    상태를 단언하지 않는 `attempt_delete_document` 로 관찰한다(음성 경로 보존).
    """
    doc = helpers.create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, _title("재삭제")
    )
    helpers.delete_document(ws_scenario.editor_client, doc["id"])  # 첫 삭제 204.

    resp = helpers.attempt_delete_document(ws_scenario.editor_client, doc["id"])
    assert resp.status_code == 409, (
        f"trashed 문서 재삭제는 409 conflict 여야 한다(5.4, 비active 삭제 금지): "
        f"{resp.status_code} {resp.text}"
    )
    assert resp.json().get("code") == "conflict", (
        f"409 는 s01 에러 카탈로그상 code=conflict 여야 한다(5.4): {resp.text}"
    )


# =============================================================================
# 5.5, INV-4·10 — 원자성·물리보존: 단일 원자 전이(부분 없음)·물리 삭제 없음
# =============================================================================


def test_cascade_transition_is_atomic_and_physically_preserved(
    doc_tree_scenario, engine_access, harness
):
    """캐스케이드 전이가 단일 원자 조작(부분 전이 없음)이고 문서가 물리 보존됨을 DB로 확인(5.5, INV-4·10).

    3단계 트리에서 삭제 **직전** active 하위(루트 포함)를 엔진 `active_descendants` 로 스냅샷해
    예상 구성원 집합을 잡은 뒤 루트를 `DELETE /documents/{id}` 로 삭제한다. 삭제 후 document
    테이블을 **직접 `SELECT`** 해:

    - **원자성(INV-10)**: 포착 예상 구성원 전원이 status=trashed 로 함께 전이했고 **active 로 남은
      구성원이 없음**(부분 전이 없음)을 확인한다.
    - **물리 보존(INV-4)**: 포착 구성원 행이 모두 **여전히 물리적으로 존재**(SELECT 로 조회됨)함을
      확인한다 — 삭제는 상태 전환이지 물리 삭제가 아니다.

    엔진 `get_bundle` 구성원 집합이 DB 관측·예상 집합과 일치함도 교차 확인한다. `harness` 와
    `doc_tree_scenario` 는 동일 L1 하네스를 공유하므로 같은 마이그레이션 DB 를 본다.
    """
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id

    expected_before = helpers.active_descendants(engine_access, root_id)
    expected_ids = {d.id for d in expected_before}
    assert expected_ids == {
        root_id,
        doc_tree_scenario.child_id,
        doc_tree_scenario.grandchild_id,
    }, f"삭제 전 active 하위(루트 포함) 스냅샷이 루트·자식·손자여야 한다(5.5): {expected_ids}"

    helpers.delete_document(editor, root_id)  # 캐스케이드 삭제(204).

    # 물리 관찰: 포착 구성원 행을 DB 에서 직접 조회.
    status_by_id = _select_status_by_ids(harness, expected_ids)

    # 물리 보존(INV-4) — 모든 행이 여전히 존재해야 한다(물리 삭제 없음).
    assert set(status_by_id) == expected_ids, (
        f"삭제 후에도 포착 구성원 행이 모두 물리적으로 존재해야 한다(INV-4, 물리 삭제 없음): "
        f"예상={expected_ids} DB존재={set(status_by_id)}"
    )
    # 원자성(INV-10) — 전원 trashed, active 로 남은 부분 전이가 없어야 한다.
    left_active = {i for i, s in status_by_id.items() if s == "active"}
    assert not left_active, (
        f"캐스케이드는 단일 원자 조작이어야 한다 — active 로 남은 부분 전이 없음(INV-10): "
        f"{left_active}"
    )
    assert all(s == "trashed" for s in status_by_id.values()), (
        f"포착 구성원 전원이 함께 trashed 로 전이해야 한다(원자성 INV-10): {status_by_id}"
    )

    # 엔진 묶음 구성원과 DB 관측·예상 집합 교차 확인.
    bundle = helpers.get_bundle(engine_access, root_id)
    assert bundle.member_ids == expected_ids == set(status_by_id), (
        f"엔진 묶음 구성원·DB 물리 행·예상 집합이 일치해야 한다(5.5): "
        f"묶음={bundle.member_ids} DB={set(status_by_id)} 예상={expected_ids}"
    )
