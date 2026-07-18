"""L6 헬퍼 스모크 — Task 1.2 관찰 가능 완료 기준 (Req 1.4·3.1·4.1·5.1·6.1·7.1, design §Helpers).

이 스위트는 태스크 1.2 헬퍼(`tests/integration_L6/helpers.py`)가 실제 결합 환경(L5 헬퍼
재사용 + s14 공유 발급/토글·공개 렌더·링크 경유 첨부 서빙·무효화 스윕·share_link 관찰 래퍼)을
제공하는지 mock 없이 확인한다("역-RED": 새 테스트가 실제 구현 위에서 **통과**하는 것이 검증).
관찰 가능 완료 기준(design §Helpers 관찰 가능 완료):

1. editor 가 헬퍼로 링크를 발급(:func:`~tests.integration_L6.helpers.issue_share`; 발급은
   `share_scenario` 픽스처가 이미 수행)하고 익명 `public_client` 의
   :func:`~tests.integration_L6.helpers.public_render` 가 문서 트리(root id 포함)를 돌려준다.
2. 공유 문서를 휴지통으로 보낸 뒤(L3 `delete_document` 재사용) 익명 공개 접근이 **404** 가 된다
   (:func:`~tests.integration_L6.helpers.attempt_public_render`, INV-8 정보 비노출 통일).
3. :func:`~tests.integration_L6.helpers.run_invalidation_sweep` 가 retire 건수(int)를 반환하고,
   share_link 관찰 헬퍼가 토큰 교체(retire)와 행 물리 존재 유지(INV-4)를 보고한다.
4. :func:`~tests.integration_L6.helpers.set_gate` 가 `is_shareable=False` 로 게이트를 닫으면
   후속 발급이 **409** 로 거부된다(게이트 off 발급 불가).

L5(및 그것이 재사용하는 L4/L3/L2/L1) 헬퍼를 재사용·확장하며 애플리케이션 코드·config.yml·하위
하네스는 만지지 않는다. mock·stub·pytest.skip 미사용. 함수-스코프 하네스가 매 테스트마다
마이그레이션을 새로 수행하므로 스윕 건수는 결정적이다(누적 오염 없음).

무효화 스윕 nuance(task 1.1 CONCERNS): 공개 실시간 게이트는 무효 문서 공개 접근 시 lazy retire
(is_enabled→False + 토큰 교체) 한다. `list_enabled_invalidatable` 은 `is_enabled=True` 만 스코프
하므로 이미 lazy retire 된 링크는 스윕에서 0 을 낸다. 따라서 스윕 retire 건수 > 0 을 관찰하려면
아직 공개 접근하지 않은(휴지통 이동만 한) 링크에 스윕을 돌린다.
"""

from tests.integration_L6 import helpers as h


# =============================================================================
# (1) 발급 + 공개 렌더 (관찰 가능 완료 ①)
# =============================================================================


def test_issue_and_public_render_returns_tree(share_scenario):
    """`share_scenario` 발급 링크로 익명 `public_client` 의 공개 렌더가 문서 트리(root id)를 돌려준다.

    - :func:`~tests.integration_L6.helpers.public_render` 가 200 을 단언하고 파싱된
      ``PublicDocumentRead`` dict(`root.id`)를 반환한다.
    - 트리-워크 헬퍼가 root id 가 트리에 포함됨을 확인한다(동적 하위 포함 대조의 기반).
    """
    token = share_scenario.token
    public = share_scenario.public_client

    doc = h.public_render(public, token)
    assert doc["root"]["id"] == share_scenario.document_id, (
        "공개 렌더 트리 루트는 공유 문서 id 여야 한다"
    )
    ids = h.collect_node_ids(doc)
    assert share_scenario.document_id in ids, "트리-워크가 루트 id 를 수집해야 한다"
    assert h.find_node(doc, share_scenario.document_id) is not None, (
        "find_node 가 루트 노드를 찾아야 한다"
    )


# =============================================================================
# (2) 휴지통 이동 후 공개 접근 404 (관찰 가능 완료 ②)
# =============================================================================


def test_trashed_document_public_access_is_404(share_scenario):
    """공유 문서를 휴지통으로 보내면(L3 재사용) 익명 공개 접근이 404 로 통일된다(INV-8 비노출).

    - 발급 직후 익명 접근은 200(사전 관찰).
    - `DELETE /documents/{id}`(trashed) 후 같은 토큰의 익명 접근은 404(사유 비노출).
    """
    token = share_scenario.token
    public = share_scenario.public_client
    doc_id = share_scenario.document_id
    editor = share_scenario.editor_client

    assert h.attempt_public_render(public, token).status_code == 200, (
        "휴지통 이동 전 익명 접근은 200"
    )

    h.l3_helpers.delete_document(editor, doc_id)

    resp = h.attempt_public_render(public, token)
    assert resp.status_code == 404, (
        f"휴지통 이동 문서 공개 접근은 404 로 통일되어야 한다: {resp.status_code} {resp.text}"
    )


# =============================================================================
# (3) 휴지통 이동 → 무효화 스윕 retire + share_link 관찰 (관찰 가능 완료 ③)
# =============================================================================


def test_trash_then_sweep_retires_and_swaps_token(
    share_scenario, invalidation_sweep, share_link_observation
):
    """공유 문서를 휴지통으로 보낸 뒤(공개 접근 없이) 무효화 스윕이 retire(토큰 교체)하고 행은 남는다.

    task 1.1 CONCERNS nuance 를 반영해 **공개 접근 없이** 휴지통 이동만 한 뒤 스윕을 돌린다
    (lazy retire 로 스코프에서 빠지지 않도록). 스윕 retire 건수 >= 1, 토큰 교체(INV-8), 행 물리
    존재 유지(INV-4, retire 는 물리 삭제 아님)를 관찰한다.
    """
    doc_id = share_scenario.document_id
    editor = share_scenario.editor_client

    token_before = h.share_token(share_link_observation, doc_id)
    assert token_before == share_scenario.token, "발급 토큰이 DB 관찰과 일치해야 한다"
    assert h.share_is_enabled(share_link_observation, doc_id) is True, (
        "발급 직후 링크는 활성"
    )

    # 공개 접근 없이 휴지통 이동만(lazy retire 회피 → 스윕이 활성 링크를 스코프에 포함).
    h.l3_helpers.delete_document(editor, doc_id)

    retired = h.run_invalidation_sweep(invalidation_sweep)
    assert isinstance(retired, int), "무효화 스윕은 retire 건수(int)를 반환해야 한다"
    assert retired >= 1, (
        f"휴지통 이동 문서의 활성 링크가 retire 되어야 한다(결정적 하네스): {retired}"
    )

    token_after = h.share_token(share_link_observation, doc_id)
    assert token_after is not None and token_after != token_before, (
        "retire 는 토큰을 교체해야 한다(INV-8)"
    )
    assert h.share_is_enabled(share_link_observation, doc_id) is False, (
        "retire 후 링크는 비활성"
    )
    assert h.share_row_exists(share_link_observation, doc_id) is True, (
        "retire 는 물리 삭제가 아니다 — 행은 남는다(INV-4)"
    )
    assert h.token_resolves(share_link_observation, token_before) is False, (
        "교체된 이전 토큰은 더 이상 해석되지 않아야 한다"
    )
    assert h.token_resolves(share_link_observation, token_after) is True, (
        "교체된 새 토큰은 행으로 해석되어야 한다"
    )


# =============================================================================
# (4) 게이트 토글 — is_shareable=False 시 발급 409 (관찰 가능 완료 ④)
# =============================================================================


def test_set_gate_off_blocks_issue_with_409(share_scenario):
    """:func:`~tests.integration_L6.helpers.set_gate` 로 게이트를 닫으면 후속 발급이 409 로 거부된다.

    - `set_gate(is_shareable=False)` 는 owner 경로 s05 설정 라우트(L2 재사용)를 태워 갱신된
      ``WorkspaceRead`` 를 돌려준다(`is_shareable=False`).
    - 게이트 off 상태에서 editor 재발급 시도는 409(발급 불가)로 표면화된다.
    """
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id
    owner = share_scenario.owner_client
    editor = share_scenario.editor_client

    updated = h.set_gate(owner, ws_id, is_shareable=False)
    assert updated["is_shareable"] is False, "게이트가 닫혀야 한다"

    resp = h.attempt_issue_share(editor, doc_id)
    assert resp.status_code == 409, (
        f"게이트 off 문서 발급은 409 여야 한다: {resp.status_code} {resp.text}"
    )


# =============================================================================
# (5) 토글 — 토큰 유지 (Group A 토글 래퍼 관찰)
# =============================================================================


def test_toggle_keeps_token(share_scenario, share_link_observation):
    """:func:`~tests.integration_L6.helpers.toggle_share` 는 비활성화/재활성화 시 토큰을 유지한다(INV-8 예외).

    발급 → 비활성화 토글 → 토큰 동일 관찰. 토글은 재발급 통일 원칙의 유일한 상태 기반 예외다.
    """
    doc_id = share_scenario.document_id
    editor = share_scenario.editor_client
    token_before = share_scenario.token

    toggled = h.toggle_share(editor, doc_id, is_enabled=False)
    assert toggled["is_enabled"] is False, "토글은 비활성화를 반영해야 한다"
    assert toggled["token"] == token_before, "토글은 토큰을 유지해야 한다(INV-8 예외)"
    assert h.share_token(share_link_observation, doc_id) == token_before, (
        "DB 관찰도 토큰 유지를 확인해야 한다"
    )


# 미사용 경고 방지 + 재-export 확인(후속 스위트가 한 지점에서 L5~L1 헬퍼에 도달).
assert h.l5_helpers is not None
assert h.l4_helpers is not None
assert h.l3_helpers is not None
assert h.l2_helpers is not None
assert h.l1_helpers is not None
