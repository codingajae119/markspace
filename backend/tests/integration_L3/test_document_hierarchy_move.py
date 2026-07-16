"""문서 계층·이동 스위트 — 같은 WS 이동/재정렬·순환·타 WS·중간삽입 (Task 2.3 /
Req 4.1·4.2·4.3·4.4·4.5, design §DocumentHierarchyMoveSuite).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕**s07**) + **실제 editor 세션** 위에서 문서 이동
라우트(`POST /documents/{id}/move`, s01 카탈로그 행 22)를 mock 없이 e2e 로 관찰한다. 계층 이동
불변식 INV-5(순환 방지)·INV-6(워크스페이스 경계)이 실제 API·서비스 결합에서 성립하는지, 그리고
중간 삽입 정렬이 대상만 재배치하고 다른 형제는 건드리지 않는지를 확인한다.

거부 상태 코드는 s01 에러 카탈로그의 4xx(404/409/422) 범위 내인지 대조하되, **구체 코드는 s07
구현 확정 값**을 단언한다(design §DocumentHierarchyMoveSuite 제약: "구체 코드는 s07 구현 확정 값을
허용"). s07 `DocumentService.move_document` 확정 계약:
- 새 부모 미존재 → 404 / 타 WS 부모 → 409(INV-6) / 비active 부모 → 409 / 순환 → 409(INV-5) /
  잘못된 형제 참조 → 422 / 성공 → 200 `DocumentRead`(부모·정렬 갱신, 중간값 삽입, 다른 형제 불변).

거부 케이스는 상태를 내부 단언하지 않는 `attempt_move_document`(응답 그대로 반환)로 정확한 상태를
단언하고, 성공 셋업 단계는 `move_document`/`create_document`(200/201 단언)로 표현한다. `sort_order`
는 s01 DECIMAL(30,15)이며 JSON 에 문자열로 실려 오므로 `Decimal(str(...))` 로 비교한다.
"""

from decimal import Decimal
from uuid import uuid4

from tests.integration_L3 import helpers

# 어댑터·서비스 어느 쪽에서든 매핑 실패를 관측하기 위한 확실히 미존재인 문서 id.
MISSING_PARENT_ID = 999_999_999


def _title(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _sort_order(doc: dict) -> Decimal:
    """``DocumentRead`` dict 의 sort_order(문자열 직렬화)를 Decimal 로 파싱한다."""
    return Decimal(str(doc["sort_order"]))


# =============================================================================
# 4.1: 같은 WS 이동/재정렬 — 새 부모·정렬 순서 반영
# =============================================================================


def test_same_ws_move_under_different_parent_reflected_on_read(doc_tree_scenario):
    """같은 WS 내 다른 부모 밑으로 이동 → 성공, 이후 조회에서 새 parent_id 반영(4.1).

    손자(부모=자식)를 루트 밑으로 옮긴다. 응답과 이후 ``GET /documents/{id}`` 모두 새 parent_id
    (=root)를 보여야 한다(이동이 내구 반영됨).
    """
    editor = doc_tree_scenario.editor_client
    grandchild_id = doc_tree_scenario.grandchild_id
    root_id = doc_tree_scenario.root_id

    moved = helpers.move_document(editor, grandchild_id, new_parent_id=root_id)
    assert moved["parent_id"] == root_id, (
        f"이동 응답은 새 부모(root)를 반영해야 한다(4.1): parent_id={moved['parent_id']}"
    )

    reread = helpers.get_document(editor, grandchild_id)
    assert reread["parent_id"] == root_id, (
        f"이후 조회는 새 부모(root)를 반영해야 한다(4.1): parent_id={reread['parent_id']}"
    )


def test_same_ws_reorder_between_siblings_reflected_on_read(doc_tree_scenario):
    """같은 WS 내 형제 사이 재정렬 → 성공, 이후 조회에서 새 정렬 순서 반영(4.1).

    한 부모 아래 형제 A·B(오름차순 sort_order)를 만든 뒤 B 를 A 앞으로 재정렬한다
    (``before_sibling_id=A``, 부모 유지). 이후 조회에서 B.sort_order < A.sort_order 로 순서가
    뒤집혀 반영되어야 한다.
    """
    editor = doc_tree_scenario.editor_client
    ws_id = doc_tree_scenario.workspace_id
    parent_id = doc_tree_scenario.root_id

    sib_a = helpers.create_document(editor, ws_id, _title("형제A"), parent_id=parent_id)
    sib_b = helpers.create_document(editor, ws_id, _title("형제B"), parent_id=parent_id)
    assert _sort_order(sib_a) < _sort_order(sib_b), (
        "생성 직후 형제는 오름차순 sort_order 여야 한다(재정렬 전제)"
    )

    # 부모를 유지한 채(new_parent_id=parent 명시) B 를 A 앞으로 이동한다.
    moved_b = helpers.move_document(
        editor, sib_b["id"], new_parent_id=parent_id, before_sibling_id=sib_a["id"]
    )
    reread_a = helpers.get_document(editor, sib_a["id"])
    assert _sort_order(moved_b) < _sort_order(reread_a), (
        f"재정렬 후 B 는 A 앞(더 작은 sort_order)이어야 한다(4.1): "
        f"B={_sort_order(moved_b)} A={_sort_order(reread_a)}"
    )


# =============================================================================
# 4.2: 순환 방지(INV-5) — 자기/후손 밑 이동 거부
# =============================================================================


def test_move_under_self_rejected_409(doc_tree_scenario):
    """문서를 자기 자신 밑으로 이동 → 409 거부(INV-5, 4.2).

    ``new_parent_id`` 를 대상 자신으로 지정하면 순환이므로 s07 서비스가 409(CONFLICT)로 거부한다.
    """
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id

    resp = helpers.attempt_move_document(editor, root_id, new_parent_id=root_id)
    assert resp.status_code == 409, (
        f"자기 자신 밑 이동은 순환으로 409 여야 한다(INV-5, 4.2): "
        f"{resp.status_code} {resp.text}"
    )


def test_move_under_own_descendant_rejected_409(doc_tree_scenario):
    """문서를 자기 후손 밑으로 이동 → 409 거부(INV-5, 4.2).

    루트를 자기 후손(손자) 밑으로 옮기면 조상 체인에 대상이 나타나 순환이므로 409 로 거부된다.
    거부 후에도 루트 parent_id 가 변경되지 않았음을 재조회로 확인한다(부분 반영 없음).
    """
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    grandchild_id = doc_tree_scenario.grandchild_id

    resp = helpers.attempt_move_document(
        editor, root_id, new_parent_id=grandchild_id
    )
    assert resp.status_code == 409, (
        f"후손 밑 이동은 순환으로 409 여야 한다(INV-5, 4.2): "
        f"{resp.status_code} {resp.text}"
    )

    reread = helpers.get_document(editor, root_id)
    assert reread["parent_id"] is None, (
        f"거부된 순환 이동은 루트를 변경하지 않아야 한다(부분 반영 없음): "
        f"parent_id={reread['parent_id']}"
    )


# =============================================================================
# 4.3: 워크스페이스 경계(INV-6) — 타 WS 부모 밑 이동 거부
# =============================================================================


def test_move_under_other_workspace_parent_rejected_409(doc_tree_scenario):
    """다른 워크스페이스 문서 밑으로 이동 → 409 거부(INV-6, 4.3).

    owner 가 두 번째 워크스페이스(WS-B)와 그 안의 문서를 만든다. WS-A 의 editor(그 문서를 이동할
    EDITOR 권한 보유)가 WS-A 문서를 WS-B 문서 밑으로 옮기려 하면, 이동 게이트는 **원본 문서**의
    워크스페이스(WS-A)로 판정되어 통과하므로 거부 사유는 권한(403)이 아니라 **WS 경계 규칙**
    (409, INV-6)이다. 거부 후 대상이 여전히 WS-A 소속임을 재조회로 확인한다.
    """
    scenario = doc_tree_scenario.scenario
    owner = scenario.owner_client
    editor = doc_tree_scenario.editor_client
    ws_a_id = doc_tree_scenario.workspace_id
    grandchild_id = doc_tree_scenario.grandchild_id

    # owner 가 WS-B 와 그 안의 부모 문서를 만든다(owner 는 WS-B 의 owner ≥ EDITOR).
    ws_b_id = helpers.l2_helpers.create_workspace(owner, "WS-B 경계 시나리오")
    assert ws_b_id != ws_a_id, "WS-B 는 WS-A 와 별개여야 한다(경계 전제)"
    ws_b_doc = helpers.create_document(owner, ws_b_id, _title("타WS부모"))

    resp = helpers.attempt_move_document(
        editor, grandchild_id, new_parent_id=ws_b_doc["id"]
    )
    assert resp.status_code == 409, (
        f"타 WS 부모 밑 이동은 WS 경계 규칙으로 409 여야 한다(INV-6, 4.3; 권한 403 아님): "
        f"{resp.status_code} {resp.text}"
    )

    reread = helpers.get_document(editor, grandchild_id)
    assert reread["workspace_id"] == ws_a_id, (
        f"거부된 타 WS 이동은 대상 소속(WS-A)을 바꾸지 않아야 한다(INV-6): "
        f"workspace_id={reread['workspace_id']}"
    )


# =============================================================================
# 4.4: 중간 삽입 정렬 — 대상만 인접 형제 사이 sort_order, 다른 형제는 불변
# =============================================================================


def test_midpoint_insertion_only_target_reordered(doc_tree_scenario):
    """두 형제 사이로 이동 시 대상만 인접 sort_order 를 받고 다른 형제는 불변(4.4).

    한 부모 아래 형제 A·B·C(오름차순 sort_order)를 만든 뒤 C 를 A 와 B 사이로 이동한다
    (``after_sibling_id=A``, ``before_sibling_id=B``). C.sort_order 는 A 와 B 사이의 **엄격한**
    중간값이어야 하고, A·B 의 sort_order 는 **재배치되지 않아야** 한다(대상만 새 순서를 받음).
    """
    editor = doc_tree_scenario.editor_client
    ws_id = doc_tree_scenario.workspace_id
    parent_id = doc_tree_scenario.root_id

    sib_a = helpers.create_document(editor, ws_id, _title("삽입A"), parent_id=parent_id)
    sib_b = helpers.create_document(editor, ws_id, _title("삽입B"), parent_id=parent_id)
    sib_c = helpers.create_document(editor, ws_id, _title("삽입C"), parent_id=parent_id)
    a_before = _sort_order(sib_a)
    b_before = _sort_order(sib_b)
    assert a_before < b_before < _sort_order(sib_c), (
        "생성 직후 A<B<C 오름차순 sort_order 여야 한다(중간 삽입 전제)"
    )

    moved_c = helpers.move_document(
        editor,
        sib_c["id"],
        new_parent_id=parent_id,
        after_sibling_id=sib_a["id"],
        before_sibling_id=sib_b["id"],
    )
    c_after = _sort_order(moved_c)
    assert a_before < c_after < b_before, (
        f"C 는 A 와 B 사이의 엄격한 중간값 sort_order 를 받아야 한다(4.4): "
        f"A={a_before} C={c_after} B={b_before}"
    )

    # 다른 형제(A·B)는 재배치되지 않아야 한다 — 대상만 새 sort_order 를 받는다.
    reread_a = helpers.get_document(editor, sib_a["id"])
    reread_b = helpers.get_document(editor, sib_b["id"])
    assert _sort_order(reread_a) == a_before, (
        f"A 의 sort_order 는 변하지 않아야 한다(대상만 재배치, 4.4): "
        f"{_sort_order(reread_a)} != {a_before}"
    )
    assert _sort_order(reread_b) == b_before, (
        f"B 의 sort_order 는 변하지 않아야 한다(대상만 재배치, 4.4): "
        f"{_sort_order(reread_b)} != {b_before}"
    )


# =============================================================================
# 4.5: 부모 검증 — 미존재 부모(404)·비active 부모(409) 이동 거부
# =============================================================================


def test_move_under_nonexistent_parent_rejected_404(doc_tree_scenario):
    """존재하지 않는 부모 밑으로 이동 → 404 거부(4.5).

    ``new_parent_id`` 가 확실히 미존재이면 s07 서비스가 새 부모 로드에 실패해 404(NOT_FOUND)로
    거부한다.
    """
    editor = doc_tree_scenario.editor_client
    grandchild_id = doc_tree_scenario.grandchild_id

    resp = helpers.attempt_move_document(
        editor, grandchild_id, new_parent_id=MISSING_PARENT_ID
    )
    assert resp.status_code == 404, (
        f"미존재 부모 밑 이동은 404 여야 한다(4.5): {resp.status_code} {resp.text}"
    )


def test_move_under_trashed_parent_rejected_409(doc_tree_scenario):
    """active 가 아닌(휴지통) 부모 밑으로 이동 → 409 거부(4.5).

    부모 후보를 만든 뒤 삭제(trashed)하고, 다른 문서를 그 비active 부모 밑으로 옮기려 하면 s07
    서비스가 비active 부모 검증에서 409(CONFLICT)로 거부한다.
    """
    editor = doc_tree_scenario.editor_client
    ws_id = doc_tree_scenario.workspace_id
    grandchild_id = doc_tree_scenario.grandchild_id

    trashed_parent = helpers.create_document(editor, ws_id, _title("비active부모"))
    helpers.delete_document(editor, trashed_parent["id"])  # active → trashed

    resp = helpers.attempt_move_document(
        editor, grandchild_id, new_parent_id=trashed_parent["id"]
    )
    assert resp.status_code == 409, (
        f"비active(휴지통) 부모 밑 이동은 409 여야 한다(4.5): "
        f"{resp.status_code} {resp.text}"
    )
