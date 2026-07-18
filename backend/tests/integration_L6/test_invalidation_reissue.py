"""무효화·재발급 결합 스위트 (Task 2.3 / Req 4.1, 4.2, 4.3, 4.4, 4.5,
design §InvalidationReissueSuite · §System Flows(무효화·재발급 — status·게이트 관측 retire)).

실제 결합된 런타임(마이그레이션 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12⊕**s14**) +
role별 실 세션 + 익명 공개 클라이언트 + 부팅 앱과 동일 세션 팩토리로 조립한 실제 s14
`ShareInvalidationSweep`)에서 **무효화·재발급 결합(INV-8)의 핵심**을 mock 없이 e2e 로 관찰한다.
무효화된 공유 링크가 **재발급 없이는 되살아나지 않음**(INV-8)이 실 문서 전이(s07/s10)·게이트
설정(s05)·조정 스윕(s14)·공개 접근 관찰로 확인되는지 검증한다. 대조 기준은 s14 design 이 아니라
s01 단일 소스(카탈로그 행 34~37·에러 404 통일·불변식 INV-4·INV-8)다.

이 스위트가 반드시 정확히 모델해야 하는 **두 무효화 경로의 상호작용**(design §System Flows,
conftest `ShareInvalidationSweepAccess` docstring):

1. **실시간 공개 게이트(lazy retire)**: 익명 `GET /public/{token}` 이 문서 trashed/deleted·게이트
   off 를 관측하면, 링크가 아직 활성일 때 `_resolve_valid_link` 가 **그 자리에서** retire
   (is_enabled→False + 토큰 교체)하고 404 를 반환한다. 스윕 이전에 일어나므로 while-invalid
   보장은 스윕 주기에 무관하다(Req 4.5).
2. **관측 스윕(`invalidate_by_observation`)**: `list_enabled_invalidatable`(=`is_enabled=True`
   만 스코프)로 무효-활성 링크를 retire 한다.

**상호작용 함정**: 스윕은 `is_enabled=True` 링크만 보므로, 공개 GET 이 먼저 lazy retire 했다면
그 링크는 이후 스윕에서 **0 건**(이미 비활성 → 스코프 밖 → 멱등)이다. 따라서 스윕 retire 건수를
**> 0** 으로 관측하려면 무효 유발(trash·게이트 off) 후 **그 토큰에 공개 GET 없이** 스윕을
호출한다(Req 4.2 멱등 검증은 스윕을 두 번 호출: 1회차 retire, 2회차 0). 이 스위트는 실 동작에
맞춰 순서를 통제하며 잘못된 건수를 단언하지 않는다.

다섯 개의 단언 그룹(task 2.3):

- **Group 1 — 문서 status 즉시 무효(4.1 / 7.8)**: 발급 후 문서 trashed(`DELETE /documents/{id}`)·
  deleted(`DELETE /trash/{bundleId}`) 전이 → 익명 `GET /public/{token}` 즉시 404(실시간 게이트,
  스윕 불필요, trash L4 결합).
- **Group 2 — retire·멱등(4.2 / 5.6)**: trash 후(공개 GET 없이) 스윕 → retire 건수 ≥ 1·
  `is_enabled=False`·토큰 교체(이전 토큰 소멸)를 DB 관찰; 재실행 → 0(이미 비활성, 스코프 밖, 멱등).
- **Group 3 — 복구 후 재발급(4.3 / 7.9, INV-8)**: retire 후 복구(`POST /trash/{bundleId}/restore`)
  → 이전 토큰 여전히 404(자동 복원 없음) → 재발급(`POST /documents/{id}/share`) 새 토큰만 200,
  이전 토큰 계속 404.
- **Group 4 — 게이트 off/on(4.4 / 7.10, INV-8)**: 게이트 off → (공개 GET 없이) 스윕 retire →
  게이트 재 on 후에도 이전 토큰 404 → 재발급 새 토큰만 200.
- **Group 5 — 관측 판정·while-invalid + INV-4(4.5)**: s14 는 status·게이트를 관측만 하고 전이/설정
  하지 않음(스윕 전후 status·게이트 불변)을 확인; 실시간 게이트가 스윕 이전에도 무효 접근 차단
  (trash → 무-스윕 즉시 404); retire 후에도 share_link 행 물리 존속(INV-4, DELETE row 부재).

문서 전이·복구·게이트 설정·스윕 직접 호출은 실제 s10·s07·s05·s14 코드다(L5→L4/L3/L2 헬퍼 재사용,
mock 없음). 이전 토큰과 재발급 토큰이 다름을 DB(`share_token`)로 확인하며 임의 DB 조작을 하지
않는다. 실 동작이 계약과 다르면(예: 복구 후 이전 토큰 부활) 단언을 약화시키지 않고 그대로 실패
시킨다 — 그것은 원인 spec(s14)에서 고쳐야 할 실제 INV-8 위반이다.

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
`s12`·`s14` 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행한다(`s01` 수정 시
모든 체크포인트).
"""

from app.models import Document, Workspace
from tests.integration_L6 import helpers


def _bundle_id_for_root(editor, workspace_id: int, root_document_id: int) -> int:
    """휴지통 목록에서 루트 문서 id 로 묶음을 찾아 `bundle_id` 를 반환한다(묶음 id 발견).

    `GET /workspaces/{id}/trash` → `Page[TrashBundleRead]` 를 태워, 루트가 `root_document_id`
    인 묶음의 `bundle_id`(= root_document_id, 카탈로그 `{bundleId}`)를 돌려준다. 발견을 실제
    복구/완전삭제(204) 성공으로 확증한다(호출자가 이후 그 id 로 restore/purge 를 태워 확인).
    """
    page = helpers.l4_helpers.list_trash(editor, workspace_id)
    for item in page["items"]:
        if item["root_document_id"] == root_document_id:
            return item["bundle_id"]
    raise AssertionError(
        f"루트 문서 {root_document_id} 의 휴지통 묶음을 찾지 못했다: "
        f"items={page['items']!r}"
    )


def _document_status(harness, document_id: int) -> str:
    """부팅 앱과 동일 세션 팩토리로 문서 status(active/trashed/deleted)를 관측한다(s07/s10 결과).

    s14 가 상태를 전이시키지 않고 **관측만** 함을 확인하기 위한 라이브 DB 관측(스윕 전후 비교).
    """
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        assert doc is not None, f"문서 {document_id} 가 존재해야 한다"
        return doc.status


def _workspace_is_shareable(harness, workspace_id: int) -> bool:
    """부팅 앱과 동일 세션 팩토리로 워크스페이스 게이트(`is_shareable`)를 관측한다(s05 결과)."""
    with harness.session_local() as db:
        ws = db.get(Workspace, workspace_id)
        assert ws is not None, f"워크스페이스 {workspace_id} 가 존재해야 한다"
        return ws.is_shareable


# =============================================================================
# Group 1 — 문서 status 즉시 무효 (Req 4.1 / 7.8, trash L4 결합)
# =============================================================================


def test_trashed_document_public_render_returns_404_realtime_gate(share_scenario):
    """발급 후 문서 trashed → 익명 `GET /public/{token}` 즉시 404(실시간 게이트, 스윕 불필요) (4.1, 7.8).

    준비: (1) 무효화 전 유효 토큰 공개 렌더가 200 임을 확정(대조 기준), (2) editor 가 공유 문서를
    `DELETE /documents/{id}`(s10 trashed 캐스케이드)로 전이시킨다. 이후 (3) **스윕을 호출하지
    않고** 같은 토큰으로 익명 공개 렌더를 태우면 `_resolve_valid_link` 가 문서 trashed 를 관측해
    즉시 404 로 차단함을 확인한다(실시간 게이트가 스윕 이전에 while-invalid 를 보장).
    """
    public = share_scenario.public_client
    token = share_scenario.token

    # (1) 무효화 전 유효 토큰은 200(대조 기준).
    assert helpers.attempt_public_render(public, token).status_code == 200, (
        "무효화 전 유효 토큰 공개 렌더는 200 이어야 한다"
    )

    # (2) 문서 trashed(s10 실제 라우트).
    helpers.l3_helpers.delete_document(
        share_scenario.editor_client, share_scenario.document_id
    )

    # (3) 스윕 없이 즉시 404(실시간 게이트).
    resp = helpers.attempt_public_render(public, token)
    assert resp.status_code == 404, (
        f"문서 trashed 후 공개 렌더는 스윕 없이 즉시 404 여야 한다(실시간 게이트): "
        f"{resp.status_code} {resp.text}"
    )


def test_deleted_document_public_render_returns_404(share_scenario):
    """trashed→deleted(완전삭제) 전이 후 익명 `GET /public/{token}` → 404 (4.1, 7.8).

    (1) editor 가 문서를 trashed 로 전이(`DELETE /documents/{id}`), (2) 휴지통 묶음 id 를 발견해
    (3) 완전삭제(`DELETE /trash/{bundleId}` → deleted 종착), (4) 같은 토큰으로 익명 공개 렌더를
    태우면 문서 deleted 관측으로 404 로 통일됨을 확인한다. 묶음 id 발견은 실제 완전삭제 204 성공
    으로 확증된다.
    """
    editor = share_scenario.editor_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id
    token = share_scenario.token

    # (1) trashed.
    helpers.l3_helpers.delete_document(editor, doc_id)

    # (2) 묶음 id 발견 + (3) 완전삭제(deleted). purge_bundle_via_api 가 204 를 단언한다(발견 확증).
    bundle_id = _bundle_id_for_root(editor, ws_id, doc_id)
    helpers.l4_helpers.purge_bundle_via_api(editor, bundle_id)

    assert _document_status(share_scenario.harness, doc_id) == "deleted", (
        "완전삭제 후 문서 status 는 deleted 여야 한다(s10 결과)"
    )

    # (4) 공개 렌더 404 통일.
    resp = helpers.attempt_public_render(share_scenario.public_client, token)
    assert resp.status_code == 404, (
        f"deleted 문서 공개 렌더는 404 여야 한다: {resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 2 — retire·멱등 (Req 4.2 / 5.6)
# =============================================================================


def test_sweep_retires_trashed_link_swaps_token_and_disables(
    share_scenario, invalidation_sweep, share_link_observation
):
    """trash 후(공개 GET 없이) 스윕 → retire 건수 ≥ 1·is_enabled False·토큰 교체·이전 토큰 소멸 (4.2, 5.6).

    핵심 상호작용 통제: 무효 문서에 **공개 GET 을 하지 않고** 스윕을 호출해야 스윕이 그 활성-무효
    링크를 스코프에 담아 retire 한다(공개 GET 이 먼저면 lazy retire 로 스코프 밖). 관찰:
    (1) 초기 DB 토큰이 발급 토큰 t1 과 일치, (2) 문서 trashed, (3) 스윕 retire 건수 ≥ 1,
    (4) `is_enabled=False`, (5) DB 토큰이 t1 과 **다름**(retire 토큰 교체), (6) 이전 토큰 t1 이
    더 이상 어떤 행으로도 해석되지 않음(영구 무효화, INV-8).
    """
    editor = share_scenario.editor_client
    doc_id = share_scenario.document_id
    t1 = share_scenario.token

    # (1) 초기 DB 토큰 = 발급 토큰.
    assert helpers.share_token(share_link_observation, doc_id) == t1, (
        "초기 DB 토큰은 발급 응답 토큰과 일치해야 한다"
    )

    # (2) 문서 trashed(공개 GET 은 하지 않는다 — 스윕이 활성-무효 링크를 스코프에 담게 하기 위해).
    helpers.l3_helpers.delete_document(editor, doc_id)

    # (3) 스윕 retire — 활성-무효 링크가 있으므로 건수 ≥ 1.
    retired = helpers.run_invalidation_sweep(invalidation_sweep)
    assert retired >= 1, (
        f"trash 후 공개 GET 없이 스윕은 활성-무효 링크를 retire 해 건수 ≥ 1 이어야 한다: {retired}"
    )

    # (4) is_enabled False.
    assert helpers.share_is_enabled(share_link_observation, doc_id) is False, (
        "retire 후 링크 is_enabled 는 False 여야 한다"
    )

    # (5) 토큰 교체 — DB 토큰이 t1 과 다름.
    t_after = helpers.share_token(share_link_observation, doc_id)
    assert t_after is not None and t_after != t1, (
        f"retire 는 토큰을 교체해야 한다(t1 소멸): t1={t1!r} 이후={t_after!r}"
    )

    # (6) 이전 토큰은 더 이상 해석되지 않음(영구 무효화, INV-8).
    assert helpers.token_resolves(share_link_observation, t1) is False, (
        "retire 후 이전 토큰 t1 은 어떤 share_link 행으로도 해석되면 안 된다(INV-8)"
    )


def test_sweep_is_idempotent_second_run_returns_zero(
    share_scenario, invalidation_sweep, share_link_observation
):
    """trash 후 1회차 스윕 retire(≥1) → 2회차 스윕 0(이미 비활성, 스코프 밖, 멱등, 오류 없음) (4.2, 5.6).

    `list_enabled_invalidatable` 은 `is_enabled=True` 링크만 스코프하므로 1회차가 retire 로
    비활성화한 링크는 2회차 스코프에서 제외된다. 두 호출 사이 새 무효-활성 링크를 만들지 않으므로
    2회차는 **정확히 0**(멱등, 재무효화·오류 없음)이어야 한다.
    """
    helpers.l3_helpers.delete_document(
        share_scenario.editor_client, share_scenario.document_id
    )

    first = helpers.run_invalidation_sweep(invalidation_sweep)
    assert first >= 1, f"1회차 스윕은 활성-무효 링크를 retire 해 ≥ 1 이어야 한다: {first}"

    second = helpers.run_invalidation_sweep(invalidation_sweep)
    assert second == 0, (
        f"2회차 스윕은 이미 비활성 링크를 스코프에서 제외해 0 이어야 한다(멱등): {second}"
    )

    # 멱등: 재실행에도 링크는 여전히 비활성(재무효화 부작용 없음).
    assert (
        helpers.share_is_enabled(
            share_link_observation, share_scenario.document_id
        )
        is False
    ), "멱등 재실행 후에도 링크는 비활성이어야 한다"


# =============================================================================
# Group 3 — 복구 후 재발급 (Req 4.3 / 7.9, INV-8)
# =============================================================================


def test_restore_then_old_token_dead_reissue_grants_new_token_only(
    share_scenario, invalidation_sweep, share_link_observation
):
    """trash→스윕 retire→복구 후 이전 토큰 여전히 404, 재발급 새 토큰만 200(이전 토큰 계속 404) (4.3, 7.9, INV-8).

    무효화된 링크가 재발급 없이는 되살아나지 않음(INV-8)의 핵심 검증:
    (1) trash(공개 GET 없이) → 스윕 retire → 이전 토큰 t1 소멸 확정,
    (2) 휴지통 묶음 복구(`POST /trash/{bundleId}/restore`) → 문서 active 재확인,
    (3) 복구 후 이전 토큰 t1 공개 렌더 여전히 404(자동 복원 없음 — 링크 비활성 + 토큰 교체 유지),
    (4) 재발급(`POST /documents/{id}/share`) → 이전 토큰과 **다른** 새 토큰 t3(응답·DB 양쪽 확인),
    (5) 새 토큰 t3 공개 렌더 200, 이전 토큰 t1 은 계속 404.
    """
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id
    t1 = share_scenario.token

    # (1) trash → 스윕 retire(공개 GET 없이) → t1 소멸.
    helpers.l3_helpers.delete_document(editor, doc_id)
    bundle_id = _bundle_id_for_root(editor, ws_id, doc_id)
    assert helpers.run_invalidation_sweep(invalidation_sweep) >= 1
    assert helpers.token_resolves(share_link_observation, t1) is False, (
        "retire 후 이전 토큰 t1 은 소멸해야 한다(INV-8)"
    )

    # (2) 복구 → 문서 active 재확인.
    helpers.l4_helpers.restore_bundle_via_api(editor, bundle_id)
    assert _document_status(share_scenario.harness, doc_id) == "active", (
        "복구 후 문서 status 는 active 여야 한다(s10 복구)"
    )

    # (3) 복구 후에도 이전 토큰 t1 은 여전히 404(자동 복원 없음).
    resp_old_after_restore = helpers.attempt_public_render(public, t1)
    assert resp_old_after_restore.status_code == 404, (
        f"복구 후에도 이전 토큰 t1 공개 렌더는 404 여야 한다(자동 복원 없음, INV-8): "
        f"{resp_old_after_restore.status_code} {resp_old_after_restore.text}"
    )

    # (4) 재발급 → 이전 토큰과 다른 새 토큰 t3(응답·DB 확인).
    reissued = helpers.issue_share(editor, doc_id)
    t3 = reissued["token"]
    assert t3 != t1, f"재발급 토큰 t3 은 이전 토큰 t1 과 달라야 한다(INV-8): t1={t1!r} t3={t3!r}"
    assert reissued["is_enabled"] is True, f"재발급 링크는 활성이어야 한다: {reissued!r}"
    assert helpers.share_token(share_link_observation, doc_id) == t3, (
        "재발급 후 DB 토큰은 새 토큰 t3 여야 한다(임의 DB 조작 아님, 실제 재발급 관찰)"
    )

    # (5) 새 토큰만 200, 이전 토큰은 계속 404.
    assert helpers.attempt_public_render(public, t3).status_code == 200, (
        "재발급 새 토큰 t3 공개 렌더는 200 이어야 한다"
    )
    assert helpers.attempt_public_render(public, t1).status_code == 404, (
        "재발급 이후에도 이전 토큰 t1 공개 렌더는 계속 404 여야 한다(재발급이 이전 토큰을 되살리지 않음)"
    )


# =============================================================================
# Group 4 — 게이트 off/on (Req 4.4 / 7.10, INV-8)
# =============================================================================


def test_gate_off_invalidates_and_reissue_after_reon_grants_new_token(
    share_scenario, invalidation_sweep, share_link_observation
):
    """게이트 off → 스윕 retire → 게이트 재 on 후에도 이전 토큰 404 → 재발급 새 토큰만 200 (4.4, 7.10, INV-8).

    (1) owner 가 s05 경로로 게이트 off(`is_shareable=false`),
    (2) 공개 GET 없이 스윕 → 게이트 off 관측으로 활성-무효 링크 retire(건수 ≥ 1)·이전 토큰 t1 소멸,
    (3) owner 가 게이트 재 on(`is_shareable=true`) → 게이트 관측값 True 재확인,
    (4) 게이트 재활성 후에도 이전 토큰 t1 공개 렌더 여전히 404(이전 토큰 소멸, 자동 복원 없음),
    (5) 재발급(게이트 on 위에서) → 이전 토큰과 다른 새 토큰 t3 → t3 공개 렌더 200, t1 계속 404.
    """
    owner = share_scenario.owner_client
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id
    t1 = share_scenario.token

    # (1) 게이트 off(s05 실제 라우트).
    helpers.set_gate(owner, ws_id, is_shareable=False)
    assert _workspace_is_shareable(share_scenario.harness, ws_id) is False, (
        "게이트 off 후 workspace.is_shareable 는 False 여야 한다(s05 결과)"
    )

    # (2) 공개 GET 없이 스윕 → 게이트 off 관측으로 retire(≥1)·t1 소멸.
    assert helpers.run_invalidation_sweep(invalidation_sweep) >= 1, (
        "게이트 off 후 공개 GET 없이 스윕은 활성-무효 링크를 retire 해 ≥ 1 이어야 한다"
    )
    assert helpers.share_is_enabled(share_link_observation, doc_id) is False
    assert helpers.token_resolves(share_link_observation, t1) is False, (
        "retire 후 이전 토큰 t1 은 소멸해야 한다(INV-8)"
    )

    # (3) 게이트 재 on.
    helpers.set_gate(owner, ws_id, is_shareable=True)
    assert _workspace_is_shareable(share_scenario.harness, ws_id) is True, (
        "게이트 재 on 후 workspace.is_shareable 는 True 여야 한다"
    )

    # (4) 게이트 재활성 후에도 이전 토큰은 여전히 404(자동 복원 없음).
    assert helpers.attempt_public_render(public, t1).status_code == 404, (
        "게이트 재 on 후에도 이전 토큰 t1 공개 렌더는 404 여야 한다(자동 복원 없음, INV-8)"
    )

    # (5) 재발급 → 새 토큰만 유효.
    reissued = helpers.issue_share(editor, doc_id)
    t3 = reissued["token"]
    assert t3 != t1, f"게이트 재 on 후 재발급 토큰 t3 은 t1 과 달라야 한다(INV-8): t1={t1!r} t3={t3!r}"
    assert helpers.share_token(share_link_observation, doc_id) == t3
    assert helpers.attempt_public_render(public, t3).status_code == 200, (
        "재발급 새 토큰 t3 공개 렌더는 게이트 on 위에서 200 이어야 한다"
    )
    assert helpers.attempt_public_render(public, t1).status_code == 404, (
        "재발급 이후에도 이전 토큰 t1 은 계속 404 여야 한다"
    )


# =============================================================================
# Group 5 — 관측 판정·while-invalid + INV-4 (Req 4.5)
# =============================================================================


def test_realtime_gate_blocks_before_any_sweep_while_invalid(share_scenario):
    """trash → (스윕 없이) 즉시 공개 404 — while-invalid 보장이 스윕 주기에 무관함 (4.5).

    무효 유발(trash) 직후 **어떤 스윕도 호출하지 않고** 익명 공개 렌더를 태우면 실시간 공개
    게이트(`_resolve_valid_link`)가 문서 trashed 를 관측해 즉시 404 로 차단한다. 무효화 즉시성이
    조정 스윕 실행에 의존하지 않음(while-invalid ⟂ 스윕 주기)을 확인한다.
    """
    public = share_scenario.public_client
    token = share_scenario.token

    # 무효화 전 200(대조).
    assert helpers.attempt_public_render(public, token).status_code == 200

    # trash 직후 — 스윕 호출 없음.
    helpers.l3_helpers.delete_document(
        share_scenario.editor_client, share_scenario.document_id
    )

    # 스윕 이전에 이미 404(실시간 게이트).
    assert helpers.attempt_public_render(public, token).status_code == 404, (
        "trash 직후 스윕 이전에도 공개 렌더는 404 여야 한다(while-invalid ⟂ 스윕 주기, Req 4.5)"
    )


def test_s14_sweep_only_observes_status_gate_does_not_transition(
    share_scenario, invalidation_sweep, share_link_observation
):
    """s14 무효화는 status·게이트를 관측만 하고 전이/설정하지 않음 — 스윕 전후 status·게이트 불변 (4.5).

    관측 기반 조정 검증: (1) editor 가 문서 trashed(s10 이 전이) → DB status=trashed 확정,
    (2) 게이트는 여전히 on(s05 만 소유) 확정, (3) 스윕 호출 → 링크 retire, (4) 스윕 **이후에도**
    문서 status 는 trashed 그대로·게이트는 on 그대로임을 확인(s14 가 문서 status·게이트를 바꾸지
    않고 관측 결과에만 근거해 링크만 retire 함, Req 4.5).
    """
    harness = share_scenario.harness
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id

    # (1) trashed(s10 이 전이).
    helpers.l3_helpers.delete_document(share_scenario.editor_client, doc_id)
    assert _document_status(harness, doc_id) == "trashed", (
        "s10 이 문서를 trashed 로 전이해야 한다(s14 는 전이하지 않음)"
    )
    # (2) 게이트는 여전히 on(s05 만 소유).
    assert _workspace_is_shareable(harness, ws_id) is True

    # (3) 스윕 → 링크 retire.
    assert helpers.run_invalidation_sweep(invalidation_sweep) >= 1
    assert helpers.share_is_enabled(share_link_observation, doc_id) is False

    # (4) 스윕 이후에도 status·게이트 불변 — s14 는 관측만 하고 전이/설정하지 않는다.
    assert _document_status(harness, doc_id) == "trashed", (
        "스윕 이후에도 문서 status 는 trashed 그대로여야 한다(s14 는 상태 전이 미수행, Req 4.5)"
    )
    assert _workspace_is_shareable(harness, ws_id) is True, (
        "스윕 이후에도 게이트는 on 그대로여야 한다(s14 는 게이트 설정 미수행, Req 4.5)"
    )


def test_retire_preserves_share_link_row_no_physical_delete_inv4(
    share_scenario, invalidation_sweep, share_link_observation
):
    """retire 후에도 share_link 행이 물리적으로 존속 — DELETE row 부재(INV-4).

    무효화는 물리 삭제가 아니라 `is_enabled=False` + 토큰 교체로만 표현된다(INV-4·INV-8):
    (1) trash → 스윕 retire, (2) 링크 비활성·토큰 교체 확정, (3) 그럼에도 문서 기준 share_link
    행이 여전히 물리적으로 존재함(`share_row_exists`=True)을 확인한다(retire ≠ DELETE).
    """
    doc_id = share_scenario.document_id

    helpers.l3_helpers.delete_document(share_scenario.editor_client, doc_id)
    assert helpers.run_invalidation_sweep(invalidation_sweep) >= 1
    assert helpers.share_is_enabled(share_link_observation, doc_id) is False

    # retire 는 물리 삭제가 아니다 — 행은 여전히 존속(INV-4).
    assert helpers.share_row_exists(share_link_observation, doc_id) is True, (
        "retire 후에도 share_link 행은 물리적으로 존속해야 한다(INV-4 물리 삭제 부재)"
    )
