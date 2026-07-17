"""bundle 복구·완전삭제 스위트 (Task 2.5 / Req 6.1, 6.2, 6.3, 6.4, 6.5,
design §BundleRestorePurgeSuite · §bundle 복구·완전삭제 flow — API 삭제 + 엔진 primitive 직접 호출).

실제 결합 런타임(마이그레이션 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕**s07**) + 실 세션 +
부팅 앱과 동일 세션 팩토리의 `DocumentStateEngine`) 위에서, `s07` 상태 엔진의 **복구·완전삭제
primitive** 가 라우터 밖 재사용 경계(s10 소비 계약)에서도 불변식을 유지함을 관찰한다. 복구·완전
삭제 API 는 L4(s10)에만 존재하므로 이 체크포인트는 엔진 primitive(`restore_bundle`·
`purge_bundle`·`get_bundle`)를 **직접** 호출한다(실제 s07 코드 실행이므로 mock 아님, design
§BundleRestorePurgeSuite 제약). 묶음을 trashed 로 만드는 것은 실제 라우트(`DELETE /documents/{id}`
= 엔진 `trash_document` 캐스케이드, s01 카탈로그 행 23)를 탄다.

다섯 개의 관찰 축(task 2.5):

- **복구 — 부모 active**(6.1, 6.5.1·6.7.1): 부모가 active 인 묶음을 복구 → 루트가 원래 부모 밑으로
  복귀(parent_id 유지)·보존된 원래 `sort_order` 원위치 복원(생존 형제 미충돌)·구성원 전원
  `status=active`·`trashed_at=NULL`.
- **복구 — 부모 non-active/부재**(6.2, 6.5.2·6.5.3·6.7.2): 부모가 non-active(trashed) 이거나
  부재(parent_id=None) 인 묶음을 복구 → 루트가 `parent_id=NULL` 로 root 레벨 생존 active 형제 맨
  뒤에 append 되고, 묶음 내부 상대 계층(구성원의 parent_id)은 유지되며 자동 재중첩이 없다.
- **완전삭제 원자성**(6.3, INV-10·4·7): 묶음을 완전삭제 → 구성원 전체 `status=deleted`(종착,
  INV-7)·물리 삭제 없이 실제 DB `SELECT` 로 행이 여전히 존재(INV-4)·`trashed_at` 보존(NULL 화 없음).
- **묶음별 독립성**(6.4, INV-12): 서로 다른 초에 만든 두 독립 묶음 중 하나를 복구 또는 완전삭제해도
  다른 묶음의 구성원·`trashed_at`(=보관 기준)이 불변.
- **상태/잠금 독립**(6.5, §4.3): 테스트가 `lock_user_id` 를 **직접** 세팅한 문서도 삭제·복구·완전
  삭제가 정상 전이하고, 엔진이 lock 값을 설정/해제하지 않는다(체크포인트가 세팅한 값만 남는다).
  (직접 세팅은 관찰용 전제이며 lock 동작 검증 자체는 s09 소유.)

### DATETIME(0) 초 단위 정밀도와 독립 묶음 대기 (task 2.5 = task 2.4 와 동일 근거)
`document.trashed_at` 은 s01 물리 모델상 DATETIME(0)(초 단위)이고 MySQL 은 저장 시 소수 초를
**반올림**한다(절삭 아님). 그래서 서로 다른 두 삭제를 **독립 묶음**으로 관측하려면(부모 non-active
복구 6.2·독립 묶음 6.4) 두 삭제의 **저장된(재조회) trashed_at 초**가 확실히 달라야 하며, 단순히 1초
경계만 넘기면 `.6s`·다음초 `.4s` 가 같은 초로 반올림돼 두 묶음이 병합될 수 있다. 해결: 첫 삭제의
**저장된** `trashed_at`(get_bundle 로 재조회)에 :data:`_SECOND_BOUNDARY_MARGIN` 여유를 더한 시각을
넘길 때까지 대기한 뒤 두 번째 삭제를 태운다(margin-based wait keyed on stored value). task 2.4
`test_bundle_delete_cascade.py` 와 동일 접근이나 본 스위트가 **자체 정의**한다(다른 스위트에서
import 하지 않음).

하네스(`harness`, L1)·`ws_scenario`(L2)·`engine_access`(L3) 픽스처가 제공하는 실 결합 환경 위에서만
동작하며 mock 을 쓰지 않는다.
"""

import time
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import bindparam, text

from app.models import Document
from tests.integration_L3 import helpers

# DATETIME(0) 초 경계 안전 마진(초). MySQL 은 DATETIME(0) 저장 시 소수 초를 **반올림**하므로
# (절삭 아님) 벽시계 초를 하나 넘는 것만으로는 부족하다 — 예: 12:00:00.6 은 01 로, 12:00:01.4
# 도 01 로 반올림돼 서로 다른 초의 두 삭제가 같은 저장값을 받을 수 있다. 기준 저장값보다
# 최소 이 마진만큼 뒤에 다음 삭제를 태우면 반올림 후에도 저장 초가 엄격히 커짐이 보장된다.
_SECOND_BOUNDARY_MARGIN = timedelta(seconds=2)


def _title(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _dec(value) -> Decimal:
    """직렬화된 sort_order(문자열/수치)를 정확 비교 가능한 :class:`Decimal` 로 정규화한다."""
    return Decimal(str(value))


def _wait_until_strictly_after(reference: datetime) -> None:
    """저장된 기준 `trashed_at` 보다 다음 삭제 초가 엄격히 커지도록 대기한다(DATETIME(0) 반올림 대응).

    `trashed_at` 은 DATETIME(0)(초 단위)이고 MySQL 은 저장 시 소수 초를 **반올림**하므로, 같은
    또는 인접 초의 두 삭제가 동일 저장값을 받으면 두 묶음이 병합되거나 보관 기준이 구별되지 않는다
    (모듈 docstring 정밀도 근거 참조). 부모 non-active 복구(6.2)·독립 묶음(6.4) 관측은 두 묶음이
    서로 다른 초로 떨어져야 하므로, 현재 벽시계가 `reference` + :data:`_SECOND_BOUNDARY_MARGIN` 을
    넘길 때까지 짧게 폴링한다. 그러면 이후 삭제는 반올림 후에도 엄격히 큰 초를 저장받는다.
    """
    target = reference + _SECOND_BOUNDARY_MARGIN
    while datetime.utcnow() < target:
        time.sleep(0.05)


def _select_rows_by_ids(harness, ids) -> dict[int, tuple]:
    """document 테이블에서 주어진 id 들의 (id → (status, trashed_at, lock_user_id)) 를 직접 조회한다.

    반환 dict 에 없는 id 는 물리 행이 존재하지 않음을 뜻한다(물리 삭제 관측용). 완전삭제 INV-4
    물리 보존·`trashed_at` 보존·lock 독립을 실제 DB 로 확인하는 데 쓴다.
    """
    stmt = text(
        "SELECT id, status, trashed_at, lock_user_id FROM document WHERE id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with harness.session_local() as db:
        rows = db.execute(stmt, {"ids": list(ids)}).all()
    return {int(row[0]): (row[1], row[2], row[3]) for row in rows}


def _set_lock_directly(engine_access, document_id: int, lock_user_id: int) -> None:
    """엔진-접근 세션으로 `lock_user_id` 를 **직접** 세팅한다(관찰용 전제, 6.5·§4.3).

    잠금 API 는 s09 소유이므로 체크포인트는 lock 을 앱 경로로 세팅하지 않는다. 상태/잠금 독립을
    관측하기 위한 **테스트 픽스처 직접 세팅**이며(유효 user FK 필요), 이후 상태 전이(삭제/복구/
    완전삭제)가 이 값을 건드리지 않음을 단언한다. lock **동작** 검증은 s09 의 몫이다.
    """
    with engine_access.session() as db:
        doc = db.get(Document, document_id)
        assert doc is not None, f"lock 직접 세팅 대상 문서가 존재해야 한다: id={document_id}"
        doc.lock_user_id = lock_user_id
        db.commit()


def _read_doc(engine_access, document_id: int):
    """엔진-접근 세션으로 문서를 detached-safe 스냅샷으로 재조회한다(전이 후 신선 관찰)."""
    with engine_access.session() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return None
        return helpers.DocumentSnapshot(
            id=doc.id,
            workspace_id=doc.workspace_id,
            parent_id=doc.parent_id,
            status=doc.status,
            sort_order=doc.sort_order,
            trashed_at=doc.trashed_at,
            lock_user_id=doc.lock_user_id,
        )


# =============================================================================
# 6.1, 6.5.1·6.7.1 — 복구(부모 active): 원래 부모 밑 복귀·sort_order 원위치·active/trashed_at=NULL
# =============================================================================


def test_restore_under_active_parent_restores_original_position(
    ws_scenario, engine_access
):
    """부모 active 묶음 복구 → 원래 부모 밑 복귀·sort_order 원위치·구성원 active·trashed_at=NULL(6.1, 6.5.1·6.7.1).

    editor 가 부모(active, root)와 그 밑 자식을 만든 뒤 **자식만** 삭제한다(부모는 active 로 남고
    묶음 루트 = 자식). 삭제 직전 자식의 원래 `sort_order` 를 생성 응답으로 포착한다. 자식이 부모의
    유일한 자식이므로 복구 시점 부모의 생존 active 형제가 없어 충돌이 없다 → 엔진 복구 primitive
    `restore_bundle(child)` 는 자식을 원래 부모 밑(parent_id 유지)으로 되돌리고 원래 sort_order 를
    원위치 복원하며(design §BundleRestorePurgeSuite 6.5.1), 구성원 전원 `status=active`·
    `trashed_at=NULL` 로 전환한다(6.7.1). 복귀 위치·상태를 복구 반환 스냅샷과 DB 재조회로 교차 확인.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    parent = helpers.create_document(editor, ws_id, _title("부모"))
    child = helpers.create_document(
        editor, ws_id, _title("자식"), parent_id=parent["id"]
    )
    original_sort_order = _dec(child["sort_order"])

    # 자식만 삭제 → 묶음 루트 = 자식, 부모는 active 로 유지.
    helpers.delete_document(editor, child["id"])
    trashed = helpers.get_bundle(engine_access, child["id"])
    assert trashed.member_ids == {child["id"]}, (
        f"자식 삭제 묶음은 자식만 포함해야 한다(6.1): {trashed.member_ids}"
    )

    # 엔진 복구 primitive 직접 호출(복구 API 는 L4/s10 — 여기서는 s10 소비 계약 선검증).
    restored = helpers.restore_bundle(engine_access, child["id"])
    by_id = {d.id: d for d in restored}
    assert set(by_id) == {child["id"]}, (
        f"복구 반환 구성원은 자식 묶음과 일치해야 한다(6.1): {set(by_id)}"
    )
    restored_child = by_id[child["id"]]

    assert restored_child.parent_id == parent["id"], (
        f"부모 active 복구는 원래 부모 밑(parent_id 유지)으로 복귀해야 한다(6.1, 6.5.1): "
        f"기대={parent['id']} 관측={restored_child.parent_id}"
    )
    assert restored_child.sort_order == original_sort_order, (
        f"충돌 없는 부모 active 복구는 원래 sort_order 를 원위치 복원해야 한다(6.7.1): "
        f"원래={original_sort_order} 관측={restored_child.sort_order}"
    )
    assert restored_child.status == "active", (
        f"복구 구성원은 status=active 여야 한다(6.7.1): {restored_child.status}"
    )
    assert restored_child.trashed_at is None, (
        f"복구 구성원은 trashed_at=NULL 이어야 한다(6.7.1): {restored_child.trashed_at}"
    )

    # DB 재조회로 신선 교차 확인(복구가 실제 커밋됐고 stale 아님).
    db_child = _read_doc(engine_access, child["id"])
    assert db_child.status == "active" and db_child.trashed_at is None, (
        f"복구 후 DB 재조회에서도 자식은 active·trashed_at=NULL 이어야 한다(6.1): "
        f"status={db_child.status} trashed_at={db_child.trashed_at}"
    )
    assert db_child.parent_id == parent["id"] and db_child.sort_order == original_sort_order, (
        f"복구 후 DB 재조회에서도 원래 부모·원래 sort_order 여야 한다(6.5.1·6.7.1): "
        f"parent_id={db_child.parent_id} sort_order={db_child.sort_order}"
    )


# =============================================================================
# 6.2, 6.5.2·6.5.3·6.7.2 — 복구(부모 non-active/부재): parent_id=NULL·root 맨 뒤·내부 계층 유지
# =============================================================================


def test_restore_with_non_active_parent_moves_to_root_end(ws_scenario, engine_access):
    """부모 non-active 묶음 복구 → parent_id=NULL·root 맨 뒤 append·내부 계층 유지·자동 재중첩 없음(6.2, 6.5.2·6.7.2).

    구성: 부모 A(root)·A 밑 자식 B·B 밑 손자 C, 그리고 별개의 생존 root 문서 D(끝까지 active).
    **B 를 먼저 삭제(t1)** 하면 B+C 가 B 루트 묶음으로 trashed 된다. 초 경계를 넘긴 뒤(정밀도 근거 —
    두 삭제가 다른 초에 떨어져 B 가 독립 루트로 남아야 함) **A 를 삭제(t2)** 한다 — 이 시점 A 의 active
    하위는 A 뿐(B 서브트리 이미 trashed)이라 A 묶음 = {A}.

    이제 B 묶음을 복구하면, 복구 시점 B 의 부모 A 가 non-active(trashed) 이므로 엔진은 B 를 root 레벨로
    복귀시켜 `parent_id=NULL` 로 만들고 root 레벨 생존 active 형제(=D) 맨 뒤에 append 한다(6.5.2·6.7.2).
    묶음 내부 상대 계층(C 는 여전히 B 밑)은 유지되고 자동 재중첩은 없다(6.5.3). A 는 여전히 trashed 로
    남아 B 를 다시 끌어안지 않는다(단독 복구).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    parent_a = helpers.create_document(editor, ws_id, _title("A부모"))
    child_b = helpers.create_document(
        editor, ws_id, _title("B자식"), parent_id=parent_a["id"]
    )
    grandchild_c = helpers.create_document(
        editor, ws_id, _title("C손자"), parent_id=child_b["id"]
    )
    # 생존 root 형제 D — B 가 root 로 복귀할 때 "맨 뒤" 기준이 되는 앵커(끝까지 active).
    sibling_d = helpers.create_document(editor, ws_id, _title("D루트형제"))

    # (t1) B 먼저 삭제 → B+C 가 B 루트 묶음으로 trashed.
    helpers.delete_document(editor, child_b["id"])
    b_bundle = helpers.get_bundle(engine_access, child_b["id"])
    assert b_bundle.member_ids == {child_b["id"], grandchild_c["id"]}, (
        f"B 삭제 묶음은 B+C 여야 한다(6.2): {b_bundle.member_ids}"
    )
    t1 = b_bundle.trashed_at

    # DATETIME(0) 반올림 — A 삭제가 B 저장 초보다 엄격히 뒤에 떨어져야 B 가 독립 루트로 남는다.
    _wait_until_strictly_after(t1)

    # (t2) A 삭제 → 그 시점 active 하위는 A 뿐(B 서브트리 이미 trashed) → A 는 non-active 부모가 된다.
    helpers.delete_document(editor, parent_a["id"])

    # B 묶음 복구 — 복구 시점 부모 A 가 non-active(trashed) → B 는 root 레벨로 복귀.
    restored = helpers.restore_bundle(engine_access, child_b["id"])
    by_id = {d.id: d for d in restored}
    assert set(by_id) == {child_b["id"], grandchild_c["id"]}, (
        f"복구 반환 구성원은 B+C 여야 한다(6.2): {set(by_id)}"
    )
    restored_b = by_id[child_b["id"]]
    restored_c = by_id[grandchild_c["id"]]

    assert restored_b.parent_id is None, (
        f"부모 non-active 복구는 루트를 parent_id=NULL 로 root 레벨에 복귀시켜야 한다(6.5.2): "
        f"관측 parent_id={restored_b.parent_id}"
    )
    assert restored_b.sort_order > _dec(sibling_d["sort_order"]), (
        f"root 복귀는 생존 active root 형제(D) 맨 뒤에 append 되어야 한다(6.7.2): "
        f"B={restored_b.sort_order} D={_dec(sibling_d['sort_order'])}"
    )
    # 내부 상대 계층 유지·자동 재중첩 없음 — C 는 여전히 B 밑.
    assert restored_c.parent_id == child_b["id"], (
        f"묶음 내부 상대 계층은 유지되어야 한다 — C 는 여전히 B 밑(6.5.3): "
        f"기대 parent={child_b['id']} 관측={restored_c.parent_id}"
    )
    assert restored_b.status == "active" and restored_b.trashed_at is None, (
        f"복구 루트는 active·trashed_at=NULL 이어야 한다(6.2): "
        f"status={restored_b.status} trashed_at={restored_b.trashed_at}"
    )
    assert restored_c.status == "active" and restored_c.trashed_at is None, (
        f"복구 구성원 C 도 active·trashed_at=NULL 이어야 한다(6.2): "
        f"status={restored_c.status} trashed_at={restored_c.trashed_at}"
    )

    # A 는 여전히 trashed 로 남아 B 를 재흡수하지 않는다(단독 복구, 자동 재중첩 없음).
    db_a = _read_doc(engine_access, parent_a["id"])
    assert db_a.status == "trashed", (
        f"B 단독 복구는 A 를 함께 되살리지 않아야 한다(6.5.3): A.status={db_a.status}"
    )


def test_restore_with_absent_parent_appends_to_root_end(ws_scenario, engine_access):
    """부모 부재(root-level) 묶음 복구 → parent_id=NULL 유지·root 맨 뒤 append(6.5.3, 6.7.2).

    parent_id=None 인 root 문서 R 과 생존 root 형제 S(끝까지 active)를 만든 뒤 R 을 삭제한다(묶음 {R}).
    복구 시점 R 은 부모가 부재(parent_id=None)이므로 엔진은 R 을 root 레벨로 복귀시켜 root 레벨 생존
    active 형제(=S) 맨 뒤에 append 한다. 부모 non-active 경로와 동일한 root 복귀 규칙을 부모 **부재**
    분기로도 확인한다(design §BundleRestorePurgeSuite 6.5.3).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    sibling_s = helpers.create_document(editor, ws_id, _title("S루트형제"))
    root_r = helpers.create_document(editor, ws_id, _title("R루트"))

    helpers.delete_document(editor, root_r["id"])
    r_bundle = helpers.get_bundle(engine_access, root_r["id"])
    assert r_bundle.member_ids == {root_r["id"]}, (
        f"root 문서 삭제 묶음은 자기만 포함해야 한다(6.5.3): {r_bundle.member_ids}"
    )

    restored = helpers.restore_bundle(engine_access, root_r["id"])
    restored_r = next(d for d in restored if d.id == root_r["id"])
    assert restored_r.parent_id is None, (
        f"부모 부재 복구는 parent_id=NULL 로 root 레벨에 유지되어야 한다(6.5.3): "
        f"{restored_r.parent_id}"
    )
    assert restored_r.sort_order > _dec(sibling_s["sort_order"]), (
        f"root 복귀는 생존 active root 형제(S) 맨 뒤에 append 되어야 한다(6.7.2): "
        f"R={restored_r.sort_order} S={_dec(sibling_s['sort_order'])}"
    )
    assert restored_r.status == "active" and restored_r.trashed_at is None, (
        f"복구 구성원은 active·trashed_at=NULL 이어야 한다(6.5.3): "
        f"status={restored_r.status} trashed_at={restored_r.trashed_at}"
    )


# =============================================================================
# 6.3, INV-10·4·7 — 완전삭제 원자성: 구성원 전체 deleted·물리 보존·trashed_at 보존·종착
# =============================================================================


def test_purge_transitions_all_members_deleted_and_physically_preserves(
    ws_scenario, engine_access, harness
):
    """완전삭제 → 구성원 전체 deleted·물리 보존(DB SELECT)·trashed_at 보존·종착(6.3, INV-10·4·7).

    부모+자식 트리를 부모 삭제로 묶음 {부모, 자식} 으로 trashed 한 뒤 엔진 완전삭제 primitive
    `purge_bundle(root)` 를 직접 호출한다(완전삭제 API 는 L4/s10 — s10 소비 계약 선검증). 확인:

    - **원자성(INV-10)**: 구성원 전체가 함께 `status=deleted` 로 전이(부분 전이 없음).
    - **물리 보존(INV-4)**: 완전삭제 후에도 두 행이 **여전히 물리적으로 존재**함을 실제 DB `SELECT`
      로 확인 — deleted 는 상태 전환이지 물리 삭제가 아니다.
    - **trashed_at 보존**: 완전삭제는 `trashed_at` 을 NULL 화하지 않고 보존한다(엔진 계약).
    - **종착(INV-7)**: deleted 는 종착 상태(복원 경로 없음)임을 상태로 확인.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    parent = helpers.create_document(editor, ws_id, _title("완전삭제부모"))
    child = helpers.create_document(
        editor, ws_id, _title("완전삭제자식"), parent_id=parent["id"]
    )

    helpers.delete_document(editor, parent["id"])
    before = helpers.get_bundle(engine_access, parent["id"])
    assert before.member_ids == {parent["id"], child["id"]}, (
        f"완전삭제 전 묶음은 부모+자식이어야 한다(6.3): {before.member_ids}"
    )
    common_trashed_at = before.trashed_at

    # 엔진 완전삭제 primitive 직접 호출.
    purged = helpers.purge_bundle(engine_access, parent["id"])
    assert purged.member_ids == {parent["id"], child["id"]}, (
        f"완전삭제 반환 구성원은 부모+자식이어야 한다(6.3): {purged.member_ids}"
    )
    assert all(m.status == "deleted" for m in purged.members), (
        f"완전삭제는 구성원 전체를 status=deleted 로 전환해야 한다(6.3, INV-10): "
        f"{[(m.id, m.status) for m in purged.members]}"
    )
    assert all(m.trashed_at == common_trashed_at for m in purged.members), (
        f"완전삭제는 trashed_at 을 보존해야 한다(NULL 화 없음): "
        f"기대={common_trashed_at} 관측={[(m.id, m.trashed_at) for m in purged.members]}"
    )

    # 물리 관찰: 두 행이 여전히 존재하고 전원 deleted·trashed_at 보존(INV-4·10, 부분 전이 없음).
    rows = _select_rows_by_ids(harness, {parent["id"], child["id"]})
    assert set(rows) == {parent["id"], child["id"]}, (
        f"완전삭제 후에도 두 행이 물리적으로 존재해야 한다(INV-4, 물리 삭제 없음): "
        f"기대={{{parent['id']}, {child['id']}}} DB존재={set(rows)}"
    )
    assert all(status == "deleted" for status, _, _ in rows.values()), (
        f"DB 관찰에서도 구성원 전원 deleted 여야 한다(원자성 INV-10, 종착 INV-7): {rows}"
    )
    assert all(ts == common_trashed_at for _, ts, _ in rows.values()), (
        f"DB 관찰에서도 trashed_at 이 보존되어야 한다: 기대={common_trashed_at} 관측={rows}"
    )

    # 종착(INV-7): deleted 는 종착 — get_bundle 은 비trashed 루트를 404 로 거부한다(복원 경로 없음).
    from app.common.errors import DomainError

    try:
        helpers.get_bundle(engine_access, parent["id"])
        raise AssertionError(
            "deleted 종착(INV-7): 완전삭제된 루트의 get_bundle 은 404 여야 한다"
        )
    except DomainError as exc:
        assert exc.http_status == 404, (
            f"완전삭제된 루트의 get_bundle 은 404 여야 한다(deleted 종착, INV-7): {exc.http_status}"
        )


# =============================================================================
# 6.4, INV-12 — 묶음별 독립성: 하나를 완전삭제/복구해도 다른 독립 묶음 불변
# =============================================================================


def _build_independent_pair(editor, ws_id, engine_access):
    """서로 다른 초에 만든 두 독립 묶음(각각 부모+자식)을 구성해 (묶음1 루트, 묶음2 스냅샷) 을 반환한다.

    두 별개 root 트리 P1·P2 를 만들고 **P1 을 먼저 삭제(t1)**, 초 경계를 넘긴 뒤 **P2 삭제(t2)** 하여
    두 묶음이 서로 다른 저장 초(=독립 보관 기준)를 갖게 한다(모듈 docstring 정밀도 근거). 반환값으로
    묶음1 의 루트 id 와 묶음2 의 사전-작업 스냅샷(불변 비교 기준)을 준다.
    """
    p1 = helpers.create_document(editor, ws_id, _title("P1"))
    c1 = helpers.create_document(editor, ws_id, _title("C1"), parent_id=p1["id"])
    p2 = helpers.create_document(editor, ws_id, _title("P2"))
    c2 = helpers.create_document(editor, ws_id, _title("C2"), parent_id=p2["id"])

    helpers.delete_document(editor, p1["id"])  # (t1) 묶음1 trashed.
    t1 = helpers.get_bundle(engine_access, p1["id"]).trashed_at
    _wait_until_strictly_after(t1)  # 다른 초 보장 → 독립 보관 기준.
    helpers.delete_document(editor, p2["id"])  # (t2) 묶음2 trashed.

    bundle2_before = helpers.get_bundle(engine_access, p2["id"])
    assert bundle2_before.member_ids == {p2["id"], c2["id"]}, (
        f"묶음2 는 P2+C2 여야 한다(6.4): {bundle2_before.member_ids}"
    )
    return p1["id"], p2["id"], bundle2_before


def test_purge_one_bundle_leaves_other_bundle_unchanged(ws_scenario, engine_access):
    """두 독립 묶음 중 하나를 완전삭제해도 다른 묶음의 구성원·trashed_at(보관 기준) 불변(6.4, INV-12).

    서로 다른 초의 두 독립 묶음을 만든 뒤 묶음1 을 완전삭제(`purge_bundle`)한다. 묶음2 를
    `get_bundle` 로 재조회해 구성원 집합·공통 `trashed_at`(= 보관 기준)이 사전-작업 스냅샷과 **동일**함을
    확인한다(묶음별 독립성, 각 묶음이 자기 trashed_at 을 보관 기준으로 독립 보유).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    bundle1_root, bundle2_root, bundle2_before = _build_independent_pair(
        editor, ws_id, engine_access
    )

    helpers.purge_bundle(engine_access, bundle1_root)  # 묶음1 완전삭제.

    bundle2_after = helpers.get_bundle(engine_access, bundle2_root)
    assert bundle2_after.member_ids == bundle2_before.member_ids, (
        f"묶음1 완전삭제는 묶음2 구성원을 바꾸지 않아야 한다(6.4, INV-12): "
        f"이전={bundle2_before.member_ids} 이후={bundle2_after.member_ids}"
    )
    assert bundle2_after.trashed_at == bundle2_before.trashed_at, (
        f"묶음1 완전삭제는 묶음2 보관 기준(trashed_at)을 바꾸지 않아야 한다(6.4, INV-12): "
        f"이전={bundle2_before.trashed_at} 이후={bundle2_after.trashed_at}"
    )
    assert all(m.status == "trashed" for m in bundle2_after.members), (
        f"묶음2 구성원은 여전히 trashed 여야 한다(6.4, 간섭 없음): "
        f"{[(m.id, m.status) for m in bundle2_after.members]}"
    )


def test_restore_one_bundle_leaves_other_bundle_unchanged(ws_scenario, engine_access):
    """두 독립 묶음 중 하나를 복구해도 다른 묶음의 구성원·trashed_at(보관 기준) 불변(6.4, INV-12).

    서로 다른 초의 두 독립 묶음을 만든 뒤 묶음1 을 복구(`restore_bundle`)한다. 묶음2 를 `get_bundle`
    로 재조회해 구성원 집합·공통 `trashed_at` 이 사전-작업 스냅샷과 **동일**함을 확인한다(단독 복구가
    다른 묶음을 함께 되살리지 않음, INV-12).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    bundle1_root, bundle2_root, bundle2_before = _build_independent_pair(
        editor, ws_id, engine_access
    )

    helpers.restore_bundle(engine_access, bundle1_root)  # 묶음1 복구.

    bundle2_after = helpers.get_bundle(engine_access, bundle2_root)
    assert bundle2_after.member_ids == bundle2_before.member_ids, (
        f"묶음1 복구는 묶음2 구성원을 바꾸지 않아야 한다(6.4, INV-12): "
        f"이전={bundle2_before.member_ids} 이후={bundle2_after.member_ids}"
    )
    assert bundle2_after.trashed_at == bundle2_before.trashed_at, (
        f"묶음1 복구는 묶음2 보관 기준(trashed_at)을 바꾸지 않아야 한다(6.4, INV-12): "
        f"이전={bundle2_before.trashed_at} 이후={bundle2_after.trashed_at}"
    )
    assert all(m.status == "trashed" for m in bundle2_after.members), (
        f"묶음2 구성원은 여전히 trashed 여야 한다(6.4, 간섭 없음): "
        f"{[(m.id, m.status) for m in bundle2_after.members]}"
    )


# =============================================================================
# 6.5, §4.3 — 상태/잠금 독립: lock 직접 세팅 문서도 삭제·복구/완전삭제 정상·엔진이 lock 미변경
# =============================================================================


def test_state_transition_independent_of_lock_on_restore(ws_scenario, engine_access):
    """lock 직접 세팅 문서도 삭제→복구가 정상 전이하고 엔진이 lock 값을 건드리지 않는다(6.5, §4.3).

    editor 가 문서를 만들고 테스트가 `lock_user_id` 를 **직접**(유효 user FK = owner_user_id) 세팅한다
    (잠금 API 는 s09 — 이는 관찰용 전제일 뿐 lock 동작 검증이 아니다). 이후 삭제(API)→복구(엔진)가
    잠금 유무와 무관하게 정상 전이함을 확인하고, 매 관측 지점에서 `lock_user_id` 가 **테스트가 세팅한
    값 그대로**임을 단언한다 — 엔진은 상태 전이 중 lock 을 읽지도 쓰지도 않으며(상태/잠금 독립),
    체크포인트도 lock 을 앱 경로로 세팅하지 않는다(직접 세팅이 유일한 lock 기록).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    lock_uid = ws_scenario.owner_user_id  # 유효 user FK(멤버) — 관찰용 직접 세팅.

    doc = helpers.create_document(editor, ws_id, _title("잠금복구"))
    _set_lock_directly(engine_access, doc["id"], lock_uid)

    # 삭제(API) → trashed. 엔진은 lock 을 건드리지 않아야 한다(세팅값 유지).
    helpers.delete_document(editor, doc["id"])
    trashed = helpers.get_bundle(engine_access, doc["id"])
    trashed_member = next(m for m in trashed.members if m.id == doc["id"])
    assert trashed_member.lock_user_id == lock_uid, (
        f"삭제 전이는 lock 값을 건드리지 않아야 한다(상태/잠금 독립, §4.3): "
        f"기대={lock_uid} 관측={trashed_member.lock_user_id}"
    )

    # 복구(엔진) → active. lock 은 여전히 세팅값(엔진이 설정/해제하지 않음).
    restored = helpers.restore_bundle(engine_access, doc["id"])
    restored_doc = next(d for d in restored if d.id == doc["id"])
    assert restored_doc.status == "active" and restored_doc.trashed_at is None, (
        f"lock 세팅 문서도 복구가 정상 전이해야 한다(6.5): "
        f"status={restored_doc.status} trashed_at={restored_doc.trashed_at}"
    )
    assert restored_doc.lock_user_id == lock_uid, (
        f"복구 전이도 lock 값을 건드리지 않아야 한다(엔진이 lock 미설정, §4.3): "
        f"기대={lock_uid} 관측={restored_doc.lock_user_id}"
    )


def test_state_transition_independent_of_lock_on_purge(
    ws_scenario, engine_access, harness
):
    """lock 직접 세팅 문서도 삭제→완전삭제가 정상 전이하고 엔진이 lock 값을 건드리지 않는다(6.5, §4.3).

    editor 가 문서를 만들고 테스트가 `lock_user_id` 를 **직접**(유효 user FK = editor_user_id) 세팅한
    뒤 삭제(API)→완전삭제(엔진)를 태운다. 완전삭제 후 문서가 정상적으로 `status=deleted` 로 전이하고,
    DB 직접 조회에서 `lock_user_id` 가 여전히 테스트가 세팅한 값임을 확인한다 — 엔진은 완전삭제 전이
    중에도 lock 을 읽지도 쓰지도 않는다(상태/잠금 독립). 직접 세팅이 유일한 lock 기록임을 증거한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    lock_uid = ws_scenario.editor_user_id  # 유효 user FK(멤버) — 관찰용 직접 세팅.

    doc = helpers.create_document(editor, ws_id, _title("잠금완전삭제"))
    _set_lock_directly(engine_access, doc["id"], lock_uid)

    helpers.delete_document(editor, doc["id"])
    purged = helpers.purge_bundle(engine_access, doc["id"])
    purged_doc = next(m for m in purged.members if m.id == doc["id"])
    assert purged_doc.status == "deleted", (
        f"lock 세팅 문서도 완전삭제가 정상 전이해야 한다(6.5): {purged_doc.status}"
    )
    assert purged_doc.lock_user_id == lock_uid, (
        f"완전삭제 전이도 lock 값을 건드리지 않아야 한다(엔진이 lock 미설정, §4.3): "
        f"기대={lock_uid} 관측={purged_doc.lock_user_id}"
    )

    # DB 직접 조회로 교차 확인 — 완전삭제 후에도 lock 은 테스트 세팅값 그대로(유일한 lock 기록).
    rows = _select_rows_by_ids(harness, {doc["id"]})
    assert doc["id"] in rows, (
        f"완전삭제 후에도 문서 행이 물리적으로 존재해야 한다(INV-4): {set(rows)}"
    )
    status, _, lock_value = rows[doc["id"]]
    assert status == "deleted" and lock_value == lock_uid, (
        f"DB 관찰에서도 deleted·lock 세팅값 유지여야 한다(상태/잠금 독립, §4.3): "
        f"status={status} lock_user_id={lock_value} 기대 lock={lock_uid}"
    )
