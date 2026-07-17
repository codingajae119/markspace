"""잠금↔삭제 독립 + 엔진 결합 스위트 — 편집 잠금 상태와 문서 trashed/deleted 상태가 서로
간섭하지 않고 s09·s10 이 s07 엔진·s01 게이팅을 재사용함을 관찰 (Task 2.4 / Req 5.1·5.2·5.3·
5.4·5.5, design §LockDeleteIndependenceSuite; §System Flows "잠금↔삭제 독립(§4.3)").

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕**s09**⊕**s10**) + **실제 세션 쿠키** 위에서
잠금·삭제 독립(§4.3)의 다섯 축을 mock 없이 결합 검증한다:

1. **(5.1)** 잠긴 문서를 `DELETE /documents/{id}` 로 trashed 전이 → 상태 전이 정상·`lock_user_id`
   가 상태 전이로 변경되지 않음(DB 관찰).
2. **(5.2)** trashed 상태 문서에 `POST /lock`·`/save`·`/cancel` → 각 동작이 문서 `status` 를
   검사하지 않고 잠금 필드/버전 append 에만 작용하며 상태 전이(status·trashed_at)를 유발하지
   않음. 저장은 trashed 문서에서도 새 버전을 만들고 `current_version_id` 를 갱신하되 status 는
   trashed 로 유지.
3. **(5.3)** 복구·완전삭제·보관 스윕이 s10 에서 `status`/`trashed_at` 을 직접 갱신하지 않고 s07
   엔진 primitive(`restore_bundle`·`purge_bundle`·`identify_bundles`)에 위임하며, 그 전이가
   lock 필드를 변경하지 않음(전이 후에도 `lock_user_id` 보존).
4. **(5.4, INV-1)** s09 잠금 라우트와 s10 휴지통 라우트가 권한 판정을 재구현하지 않고 s01
   `require_ws_role` + s07 문서→WS(묶음→WS) 어댑터를 재사용함을 **동일 role 매트릭스 결과**
   (viewer 403·비멤버 403·admin bypass·미존재 대상 404)를 두 도메인에서 관찰해 확인(단일 게이팅
   레이어 증거).
5. **(5.5)** 잠금 필드가 설정된 채 trashed 된 문서를 `DELETE /trash/{bundleId}` 완전삭제·`POST
   /trash/{bundleId}/restore` 복구해도 상태 전이가 잠금 유무와 무관하게 정상 수행(전이 API 가
   잠금으로 막히지 않음).

**제약(design §LockDeleteIndependenceSuite)**: 잠금 상태는 **실제 `POST /lock`** 으로만 설정한다
(테스트가 lock 컬럼을 임의 조작해 잠금을 위조하지 않는다). 상태 전이는 실제 라우터(`DELETE
/documents/{id}`·`/trash/{bundleId}` 계열)·실제 스윕(`run_sweep`)으로 유발하고, 결과는
부팅 앱과 **동일 세션 팩토리**(`harness.session_local`)로 DB 를 직접 관측한다(테스트 관찰이며
전이 자체는 실제 s07·s09·s10 코드가 수행 — mock 아님).

이 스위트는 test-authoring task 로 feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가 실제
구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다. 잠금↔삭제 독립이 깨지면
단언을 약화시키지 않고 실제 회귀(s09/s10/s07 결합 버그)를 그대로 표면화한다.
"""

from app.models import Document
from tests.integration_L4 import helpers as h

l3_helpers = h.l3_helpers

# 인증되었으나 대상 문서/묶음이 존재하지 않을 때 어댑터 매핑-실패(→404)를 관측하기 위한 미존재 id.
MISSING_ID = 999_999_999


# =============================================================================
# 관찰 헬퍼 — 부팅 앱과 동일 세션으로 DB 직접 관측(테스트가 전이·잠금을 손으로 만들지 않음)
# =============================================================================


def _doc_row(harness, document_id: int) -> dict | None:
    """부팅 앱과 동일 세션 팩토리로 문서 행의 관찰 필드를 신규 세션으로 직접 관측한다(없으면 None).

    반환값이 None 이면 물리 행 부재를 뜻한다(물리 삭제 부재 관측용). status·trashed_at 전이와
    `lock_user_id`(잠금 독립 관찰)·`current_version_id`(저장 결과)를 실제 DB 로 확인한다 — 테스트는
    이 값을 **읽기만** 하고 쓰지 않는다(잠금은 실제 `POST /lock`, 전이는 실제 라우터/스윕이 수행).
    """
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return None
        return {
            "status": doc.status,
            "trashed_at": doc.trashed_at,
            "lock_user_id": doc.lock_user_id,
            "current_version_id": doc.current_version_id,
        }


# =============================================================================
# 1) 잠긴 문서 trashed 가능 · lock 필드 불변 (Req 5.1, §4.3)
# =============================================================================


def test_locked_document_trashes_and_lock_field_survives(doc_tree_scenario, harness):
    """editor A `POST /lock` → editor `DELETE /documents/{id}` trashed 전이 성공, `lock_user_id` 불변(5.1).

    잠긴 문서를 삭제(trashed 전이)해도 삭제는 잠금 유무를 검사하지 않고(엔진 `trash_document` 은
    status 만 확인) 정상 204 로 수행되며, 상태 전이가 `lock_user_id` 를 건드리지 않는다 — 삭제
    전·후 모두 보유자는 A 다(§4.3 잠금·삭제 독립). 잠금은 **실제 라우트**로만 설정한다.
    """
    editor = doc_tree_scenario.editor_client
    editor_id = doc_tree_scenario.scenario.editor_user_id
    doc_id = doc_tree_scenario.root_id

    # (실제 라우트로 잠금 설정) A 가 잠금 획득 — lock 컬럼 임의 조작 없음.
    body = h.lock(editor, doc_id)
    assert body["lock_user_id"] == editor_id, "잠금 보유자는 A 여야 한다(실제 POST /lock)"

    before = _doc_row(harness, doc_id)
    assert before["status"] == "active" and before["lock_user_id"] == editor_id, (
        f"삭제 전: active·A 잠금이어야 한다: {before}"
    )

    # (실제 라우트로 전이) 잠긴 문서를 삭제 → trashed 캐스케이드(잠금 유무 무관 204).
    l3_helpers.delete_document(editor, doc_id)

    after = _doc_row(harness, doc_id)
    assert after["status"] == "trashed", (
        f"잠긴 문서도 삭제(trashed 전이)가 정상 수행되어야 한다(§4.3): {after}"
    )
    assert after["trashed_at"] is not None, "trashed 전이는 trashed_at 을 설정해야 한다"
    assert after["lock_user_id"] == editor_id, (
        f"상태 전이(trashed)가 lock_user_id 를 변경하면 안 된다 — 여전히 A(§4.3): {after}"
    )


# =============================================================================
# 2) trashed 문서의 잠금·저장·취소 — status 무검사 · 전이 미유발 (Req 5.2, §4.3)
# =============================================================================


def test_lock_save_cancel_on_trashed_document_are_status_independent(
    doc_tree_scenario, harness
):
    """trashed 문서에 `POST /lock`·`/save`·`/cancel` → status 무검사·잠금/버전만 작용·전이 미유발(5.2).

    문서를 먼저 삭제(trashed)한 뒤 잠금·저장·취소를 순서대로 수행한다. 각 동작은 문서 `status` 를
    검사하지 않으므로(§4.3) trashed 문서에서도 정상 동작하고, 어느 것도 status·trashed_at 을
    바꾸지 않는다(s09 상태 미전이). 저장은 trashed 문서에서도 새 버전을 만들고 `current_version_id`
    를 갱신하되 status 는 trashed 로 유지된다.
    """
    editor = doc_tree_scenario.editor_client
    editor_id = doc_tree_scenario.scenario.editor_user_id
    ws_id = doc_tree_scenario.workspace_id

    # 깨끗한 버전 카운트를 위한 신규 문서 → 삭제(trashed 단독 묶음).
    doc_id = l3_helpers.create_document(editor, ws_id, "trashed-잠금동작")["id"]
    l3_helpers.delete_document(editor, doc_id)

    trashed = _doc_row(harness, doc_id)
    assert trashed["status"] == "trashed", "대상 문서는 trashed 여야 한다(셋업)"
    trashed_at_pinned = trashed["trashed_at"]
    assert trashed_at_pinned is not None, "trashed 문서는 trashed_at 을 가진다"

    # (a) trashed 문서 잠금 — status 무검사로 200. 잠금 필드만 설정, 전이 없음.
    lock_body = h.lock(editor, doc_id)
    assert lock_body["lock_user_id"] == editor_id, "trashed 문서 잠금 보유자는 A(status 독립)"
    after_lock = _doc_row(harness, doc_id)
    assert after_lock["status"] == "trashed", (
        f"잠금은 status 를 바꾸지 않는다 — 여전히 trashed(§4.3): {after_lock}"
    )
    assert after_lock["trashed_at"] == trashed_at_pinned, "잠금은 trashed_at 을 바꾸지 않는다"
    assert after_lock["lock_user_id"] == editor_id, "잠금 필드만 설정됐다"

    # (b) trashed 문서 저장 — 새 버전 생성·current 갱신·잠금 해제. status 는 여전히 trashed.
    before_total = h.list_versions(editor, doc_id)["total"]
    version = h.save(editor, doc_id, "# trashed 문서 본문")
    assert version["document_id"] == doc_id, "생성 버전은 대상 문서 소속"
    assert version["created_by"] == editor_id, "저장자는 A"
    assert "content" not in version, "버전 응답은 본문을 노출하지 않는다(메타데이터 전용)"

    after_save = _doc_row(harness, doc_id)
    assert h.list_versions(editor, doc_id)["total"] == before_total + 1, (
        "trashed 문서 저장도 새 버전을 만든다(버전 append 는 status 독립, 5.2)"
    )
    assert after_save["current_version_id"] == version["id"], (
        f"저장은 current_version_id 를 새 버전으로 갱신한다(status 독립): {after_save}"
    )
    assert after_save["status"] == "trashed", (
        f"저장은 status 를 바꾸지 않는다 — 여전히 trashed(s09 미전이, 5.2): {after_save}"
    )
    assert after_save["trashed_at"] == trashed_at_pinned, (
        "저장은 trashed_at 을 바꾸지 않는다(전이 미유발)"
    )
    assert after_save["lock_user_id"] is None, "저장은 잠금을 해제한다(잠금 필드만 조작)"

    # (c) trashed 문서 재잠금 후 취소 — 잠금만 해제, 버전 미생성, status 여전히 trashed.
    h.lock(editor, doc_id)
    total_before_cancel = h.list_versions(editor, doc_id)["total"]
    h.cancel(editor, doc_id)
    after_cancel = _doc_row(harness, doc_id)
    assert h.list_versions(editor, doc_id)["total"] == total_before_cancel, (
        "취소는 어떤 버전도 만들지 않는다(변경분 폐기, 5.2)"
    )
    assert after_cancel["status"] == "trashed", (
        f"취소는 status 를 바꾸지 않는다 — 여전히 trashed(s09 미전이, 5.2): {after_cancel}"
    )
    assert after_cancel["trashed_at"] == trashed_at_pinned, "취소는 trashed_at 을 바꾸지 않는다"
    assert after_cancel["lock_user_id"] is None, "취소는 잠금만 해제한다(lock_user_id=NULL)"


# =============================================================================
# 3) s10 상태 전이 엔진 위임 · lock 필드 미변경 — 복구·완전삭제·스윕 (Req 5.3)
# =============================================================================


def test_restore_and_purge_delegate_to_engine_and_preserve_lock(
    trash_scenario, harness, engine_access
):
    """복구·완전삭제(s10)가 엔진 primitive 위임으로 status 를 전이하되 lock 필드는 보존한다(5.3).

    `trash_scenario` 의 두 독립 묶음(루트+자식·손자)에 **실제 `POST /lock`** 으로 잠금을 건 뒤,
    루트 묶음은 복구(`POST /trash/{root}/restore`), 손자 묶음은 완전삭제(`DELETE /trash/{gc}`)
    한다. s10 은 status/trashed_at 을 직접 갱신하지 않고 엔진 `restore_bundle`·`purge_bundle` 에
    위임하므로(엔진 관찰 교차 확인), 전이가 일어나되(active/deleted) 잠금 필드는 그대로 보존된다
    (§4.3 잠금 독립 — 엔진은 lock 을 읽지도 쓰지도 않음).
    """
    editor = trash_scenario.editor_client
    editor_id = trash_scenario.scenario.editor_user_id
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id

    # (실제 라우트로 잠금 설정) trashed 묶음 루트에 각각 A 잠금 — lock 컬럼 임의 조작 없음.
    assert h.lock(editor, root_id)["lock_user_id"] == editor_id, "루트 trashed 잠금 A"
    assert h.lock(editor, grandchild_id)["lock_user_id"] == editor_id, "손자 trashed 잠금 A"

    # --- 복구: 엔진 restore_bundle 위임 → 구성원 active·trashed_at NULL, 루트 lock 보존 ---
    h.restore_bundle_via_api(editor, root_id)  # 실제 라우터 204(엔진 위임).
    root_after = _doc_row(harness, root_id)
    assert root_after["status"] == "active" and root_after["trashed_at"] is None, (
        f"복구는 엔진 위임으로 구성원을 active·trashed_at=NULL 로 전이한다: {root_after}"
    )
    assert root_after["lock_user_id"] == editor_id, (
        f"복구(status 전이)는 lock_user_id 를 변경하면 안 된다 — 여전히 A(§4.3, 5.3): {root_after}"
    )
    # 엔진 관찰: 루트 묶음이 identify_bundles 에서 소멸(라우터가 엔진 위임으로 커밋).
    engine_roots = {b.root_document_id for b in l3_helpers.identify_bundles(engine_access, ws_id)}
    assert root_id not in engine_roots, "복구된 루트 묶음은 엔진 열거에서 사라져야 한다(엔진 위임)"

    # --- 완전삭제: 엔진 purge_bundle 위임 → 구성원 deleted·trashed_at 보존, 손자 lock 보존 ---
    h.purge_bundle_via_api(editor, grandchild_id)  # 실제 라우터 204(엔진 위임, 비가역).
    gc_after = _doc_row(harness, grandchild_id)
    assert gc_after is not None and gc_after["status"] == "deleted", (
        f"완전삭제는 엔진 위임으로 구성원을 deleted 종착 전이한다(물리 보존): {gc_after}"
    )
    assert gc_after["trashed_at"] is not None, "완전삭제는 trashed_at 을 보존한다(엔진 위임)"
    assert gc_after["lock_user_id"] == editor_id, (
        f"완전삭제(status 전이)는 lock_user_id 를 변경하면 안 된다 — 여전히 A(§4.3, 5.3): {gc_after}"
    )
    # 자식(복구된 루트 묶음 구성원)은 active — 복구 위임의 원자 전이 확인(잠금 무관).
    assert _doc_row(harness, child_id)["status"] == "active", "복구 묶음 자식도 active(원자 전이)"


def test_sweep_delegates_to_engine_and_preserves_lock(
    trash_scenario, harness, sweep_access
):
    """보관 스윕(s10)이 엔진 위임으로 만료 묶음만 deleted 전이하되 lock 필드는 보존한다(5.3).

    `trash_scenario` 는 손자 묶음을 기준시각 40일 전(retention=30 → 만료), 루트+자식 묶음을 5일
    전(미만료)으로 핀 고정한다. 만료 대상 손자에 **실제 `POST /lock`** 으로 잠금을 건 뒤 부팅 앱과
    동일 세션의 `run_sweep(now=reference)` 를 실행한다. 스윕은 status/trashed_at 을 직접 갱신하지
    않고 엔진 `identify_bundles`·`purge_bundle` 에만 의존하므로, 만료 손자만 deleted 로 전이되고
    (미만료 루트+자식은 불변) 그 전이가 손자의 lock 필드를 건드리지 않는다(잠금 독립, 5.3).
    """
    editor = trash_scenario.editor_client
    editor_id = trash_scenario.scenario.editor_user_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id

    # (실제 라우트로 잠금 설정) 만료 대상(손자)에 A 잠금 — lock 컬럼 임의 조작 없음.
    assert h.lock(editor, grandchild_id)["lock_user_id"] == editor_id, "손자 trashed 잠금 A"

    # (실제 스윕) 주입된 now 로 보관 만료 스윕 1회 — 엔진 identify_bundles·purge_bundle 위임.
    purged = h.run_sweep(sweep_access, trash_scenario.reference)
    assert purged >= 1, "만료 손자 묶음이 최소 하나 완전삭제되어야 한다(now 주입 경계 결정성)"

    # 만료 손자: deleted 전이(엔진 위임)·trashed_at 보존·lock 보존.
    gc_after = _doc_row(harness, grandchild_id)
    assert gc_after is not None and gc_after["status"] == "deleted", (
        f"만료 손자 묶음은 스윕으로 deleted 전이되어야 한다(엔진 위임): {gc_after}"
    )
    assert gc_after["trashed_at"] is not None, "스윕 완전삭제도 trashed_at 을 보존한다"
    assert gc_after["lock_user_id"] == editor_id, (
        f"스윕 전이(status)는 lock_user_id 를 변경하면 안 된다 — 여전히 A(§4.3, 5.3): {gc_after}"
    )

    # 미만료 루트+자식: 스윕이 건드리지 않음(묶음별 독립 타이머 — status/trashed_at 유지).
    for doc_id in (root_id, child_id):
        row = _doc_row(harness, doc_id)
        assert row["status"] == "trashed", (
            f"미만료 묶음 구성원(id={doc_id})은 스윕 후에도 trashed 여야 한다(독립 타이머): {row}"
        )


# =============================================================================
# 4) 게이팅 재사용 — s09·s10 이 동일 role 매트릭스(require_ws_role + 어댑터) (Req 5.4, INV-1)
# =============================================================================


def test_lock_and_trash_routes_share_single_gating_layer(trash_scenario):
    """s09 잠금 라우트와 s10 휴지통 라우트가 **동일 role 매트릭스 결과**를 낸다(5.4, INV-1).

    두 도메인의 EDITOR 게이트 라우트 — s09 `POST /documents/{id}/lock`(`ws_role_for_document`)와
    s10 `POST /trash/{bundleId}/restore`(`ws_role_for_bundle`) — 는 권한 판정을 재구현하지 않고
    동일한 s01 `require_ws_role(EDITOR)` + s07 문서/묶음→WS 어댑터를 재사용한다. 같은 role 세션에
    대해 두 도메인이 **동일한 통과/거부 결과**를 내면 게이팅이 라우트별로 재구현되지 않고 단일
    레이어를 공유한다는 증거다:

    - viewer(멤버·읽기전용) → 두 도메인 모두 403(require_ws_role 위계 거부, INV-2)
    - 비멤버 → 두 도메인 모두 403(멤버십 부재 거부, INV-1)
    - 미존재 대상(문서/묶음) → 두 도메인 모두 404(어댑터 매핑 실패가 role 판정보다 앞섬)
    - admin(비멤버) → 두 도메인 모두 bypass 성공 2xx(INV-3)

    잠금 상태는 실제 라우트 결과이며 lock 컬럼을 조작하지 않는다. viewer/비멤버 거부·미존재 404 는
    상태를 바꾸지 않고, admin bypass 만 실제 전이를 남긴다(순서상 마지막에 관측).
    """
    ws_root = trash_scenario.root_id  # s09 대상(잠금): trashed 문서(게이팅은 status 독립).
    bundle_gc = trash_scenario.grandchild_id  # s10 대상(복구): 손자 단독 묶음 루트.
    viewer = trash_scenario.scenario.viewer_client
    nonmember = trash_scenario.scenario.nonmember_client
    admin = trash_scenario.scenario.admin_client
    editor = trash_scenario.editor_client

    # --- viewer: 두 도메인 모두 403(동일 거부) ---
    s09_viewer = h.attempt_lock(viewer, ws_root).status_code
    s10_viewer = h.attempt_restore_bundle(viewer, bundle_gc).status_code
    assert s09_viewer == 403 and s10_viewer == 403, (
        f"viewer 는 s09 잠금·s10 복구 모두 403 이어야 한다(단일 게이팅 레이어, INV-2): "
        f"s09={s09_viewer} s10={s10_viewer}"
    )
    assert s09_viewer == s10_viewer, "두 도메인의 viewer 게이팅 결과가 동일해야 한다(재구현 부재)"

    # --- 비멤버: 두 도메인 모두 403(동일 거부) ---
    s09_non = h.attempt_lock(nonmember, ws_root).status_code
    s10_non = h.attempt_restore_bundle(nonmember, bundle_gc).status_code
    assert s09_non == 403 and s10_non == 403, (
        f"비멤버는 s09 잠금·s10 복구 모두 403 이어야 한다(단일 게이팅 레이어, INV-1): "
        f"s09={s09_non} s10={s10_non}"
    )
    assert s09_non == s10_non, "두 도메인의 비멤버 게이팅 결과가 동일해야 한다(재구현 부재)"

    # --- 미존재 대상: 두 도메인 모두 404(어댑터 매핑 실패가 role 판정보다 앞섬, authorized editor 로 관측) ---
    s09_missing = h.attempt_lock(editor, MISSING_ID).status_code
    s10_missing = h.attempt_restore_bundle(editor, MISSING_ID).status_code
    assert s09_missing == 404 and s10_missing == 404, (
        f"미존재 문서/묶음은 s09·s10 모두 어댑터 매핑 실패로 404 여야 한다(공통 어댑터): "
        f"s09={s09_missing} s10={s10_missing}"
    )
    assert s09_missing == s10_missing, "두 도메인의 미존재 대상 결과가 동일해야 한다(공통 어댑터)"

    # --- admin(비멤버): 두 도메인 모두 bypass 성공 2xx(INV-3) — 마지막에 관측(상태 전이 유발) ---
    s09_admin = h.attempt_lock(admin, ws_root).status_code
    s10_admin = h.attempt_restore_bundle(admin, bundle_gc).status_code
    assert 200 <= s09_admin < 300 and 200 <= s10_admin < 300, (
        f"비멤버 admin 은 s09 잠금·s10 복구 모두 bypass 성공(2xx)이어야 한다(INV-3): "
        f"s09={s09_admin} s10={s10_admin}"
    )


# =============================================================================
# 5) 잠긴 상태 trashed 문서 완전삭제·복구 정상 전이 (Req 5.5, §4.3)
# =============================================================================


def test_locked_trashed_document_purges_regardless_of_lock(trash_scenario, harness):
    """잠금 필드가 설정된 채 trashed 된 문서를 완전삭제하면 잠금 유무와 무관하게 정상 전이(5.5).

    루트+자식 묶음 루트에 **실제 `POST /lock`** 으로 잠금을 건 뒤 `DELETE /trash/{root}` 완전삭제
    한다. 완전삭제 API 는 잠금으로 막히지 않고(409 없이) 204 로 성공하며, 구성원 전체가 deleted 로
    전이된다(§4.3 상태/잠금 독립의 완전삭제 경로). 잠금 필드는 전이 후에도 보존된다.
    """
    editor = trash_scenario.editor_client
    editor_id = trash_scenario.scenario.editor_user_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id

    assert h.lock(editor, root_id)["lock_user_id"] == editor_id, "루트 trashed 잠금 A(실제 라우트)"

    # 완전삭제 API 는 잠금 유무와 무관하게 성공(204) — 잠금이 전이를 막지 않는다.
    assert h.attempt_purge_bundle(editor, root_id).status_code == 204, (
        "잠긴 채 trashed 된 문서도 완전삭제가 정상 204(잠금 무관 전이, 5.5)"
    )
    for doc_id in (root_id, child_id):
        row = _doc_row(harness, doc_id)
        assert row is not None and row["status"] == "deleted", (
            f"완전삭제는 잠금 유무와 무관하게 구성원을 deleted 전이해야 한다(5.5): id={doc_id} {row}"
        )
    # 잠긴 채 완전삭제된 루트의 lock 필드는 보존된다(전이가 lock 을 건드리지 않음).
    assert _doc_row(harness, root_id)["lock_user_id"] == editor_id, (
        "완전삭제(전이)는 lock_user_id 를 변경하지 않는다(§4.3)"
    )


def test_locked_trashed_document_restores_regardless_of_lock(trash_scenario, harness):
    """잠금 필드가 설정된 채 trashed 된 문서를 복구하면 잠금 유무와 무관하게 정상 전이(5.5).

    손자 단독 묶음 루트에 **실제 `POST /lock`** 으로 잠금을 건 뒤 `POST /trash/{gc}/restore` 복구
    한다. 복구 API 는 잠금으로 막히지 않고 204 로 성공하며 손자가 active·trashed_at=NULL 로 전이
    된다(§4.3 상태/잠금 독립의 복구 경로). 잠금 필드는 전이 후에도 보존된다.
    """
    editor = trash_scenario.editor_client
    editor_id = trash_scenario.scenario.editor_user_id
    grandchild_id = trash_scenario.grandchild_id

    assert h.lock(editor, grandchild_id)["lock_user_id"] == editor_id, (
        "손자 trashed 잠금 A(실제 라우트)"
    )

    # 복구 API 는 잠금 유무와 무관하게 성공(204) — 잠금이 전이를 막지 않는다.
    assert h.attempt_restore_bundle(editor, grandchild_id).status_code == 204, (
        "잠긴 채 trashed 된 문서도 복구가 정상 204(잠금 무관 전이, 5.5)"
    )
    row = _doc_row(harness, grandchild_id)
    assert row["status"] == "active" and row["trashed_at"] is None, (
        f"복구는 잠금 유무와 무관하게 문서를 active·trashed_at=NULL 로 전이해야 한다(5.5): {row}"
    )
    assert row["lock_user_id"] == editor_id, (
        "복구(전이)는 lock_user_id 를 변경하지 않는다(§4.3)"
    )
