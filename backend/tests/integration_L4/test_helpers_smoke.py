"""Task 1.2 관찰 가능 완료 스모크 — L4 헬퍼가 실제 잠금·버전·휴지통·스윕을 구동함을 검증.

이 스모크는 mock 없이 부팅된 결합 런타임(마이그레이션 DB + `app.main.create_app` — s09 잠금·
버전 라우터 + s10 휴지통 라우터·스케줄러 조립 + 실제 멤버십/문서 데이터 + 실제
`DocumentStateEngine`/`RetentionSweepService`) 위에서 :mod:`tests.integration_L4.helpers`
래퍼를 태운다("역-RED": helpers.py 부재 시 이 모듈은 수집 단계에서 import 오류로 **실패**하고,
helpers.py 추가 후 **통과**하는 것으로 관찰 가능 완료를 증명한다).

관찰 가능 완료(tasks.md 1.2):
1. editor A 가 :func:`lock` 후 :func:`save`(content) 하면 :func:`list_versions` 가 버전을 반환.
2. editor 가 :func:`delete_document`(L3 헬퍼 재-export) 로 문서를 삭제하면 :func:`list_trash`
   가 그 묶음을 반환.
3. 스윕 헬퍼가 주입된 ``now`` 로 처리한 묶음 수(int)를 반환.

mock·stub·pytest.skip 미사용. 애플리케이션 코드·하위 하네스는 만지지 않는다.
"""

from tests.integration_L4 import helpers as h


def _uniq(prefix: str) -> str:
    """공유 ``markspace_test`` DB 에서 충돌하지 않는 고유 제목(L1 관용 재사용)."""
    return h.l3_helpers.l1_helpers.unique_login_id(prefix)


# =============================================================================
# 1) 잠금 → 저장 → 버전 목록 — s09 잠금·버전 라우트 래퍼 왕복 (관찰 가능 완료 ①)
# =============================================================================


def test_lock_save_then_list_versions_returns_version(lock_scenario):
    """editor A 가 :func:`lock` 후 :func:`save` 하면 :func:`list_versions` 가 버전을 반환한다.

    실제 ``POST /lock``(200 DocumentLockRead) → ``POST /save``(200 DocumentVersionRead, 본문
    저장·잠금 해제) → ``GET /versions``(200 Page)를 순서대로 태워, save 헬퍼가 만든 버전이
    목록에 나타남을 관찰한다(trivial pass 가 아님).
    """
    editor_a = lock_scenario.editor_a_client
    ws_id = lock_scenario.workspace_id

    doc = h.l3_helpers.create_document(editor_a, ws_id, _uniq("잠금저장"))
    doc_id = doc["id"]

    lock_body = h.lock(editor_a, doc_id)
    assert lock_body["document_id"] == doc_id
    assert lock_body["lock_user_id"] == lock_scenario.editor_a_user_id

    version = h.save(editor_a, doc_id, "첫 저장 본문")
    assert version["document_id"] == doc_id

    page = h.list_versions(editor_a, doc_id)
    assert page["total"] >= 1, f"저장 후 버전이 최소 1개여야 한다: {page}"
    version_ids = {item["id"] for item in page["items"]}
    assert version["id"] in version_ids, (
        f"방금 저장한 버전이 목록에 나타나야 한다: {version['id']} not in {version_ids}"
    )


# =============================================================================
# 2) 삭제 → 휴지통 목록 — L3 delete_document 재-export + s10 휴지통 목록 래퍼 (관찰 가능 완료 ②)
# =============================================================================


def test_delete_document_then_list_trash_returns_bundle(ws_scenario):
    """editor 가 :func:`delete_document`(L3 재-export) 로 삭제하면 :func:`list_trash` 가 묶음을 반환.

    실제 ``DELETE /documents/{id}``(엔진 trash 캐스케이드) 후 ``GET /workspaces/{id}/trash``
    (200 Page[TrashBundleRead])에 방금 삭제한 문서가 묶음 루트로 나타남을 관찰한다.
    """
    editor = ws_scenario.editor_client
    ws_id = ws_scenario.workspace_id

    doc = h.l3_helpers.create_document(editor, ws_id, _uniq("삭제대상"))
    doc_id = doc["id"]

    h.l3_helpers.delete_document(editor, doc_id)

    page = h.list_trash(editor, ws_id)
    bundle_ids = {item["bundle_id"] for item in page["items"]}
    assert doc_id in bundle_ids, (
        f"삭제한 문서가 휴지통 묶음 루트로 나타나야 한다: {doc_id} not in {bundle_ids}"
    )


# =============================================================================
# 3) 스윕 래퍼 — 주입된 now 로 처리 묶음 수 반환 (관찰 가능 완료 ③)
# =============================================================================


def test_run_sweep_returns_processed_count(trash_scenario, sweep_access):
    """스윕 래퍼가 주입된 ``now`` 로 실제 ``sweep_expired_bundles`` 를 구동해 처리 수(int)를 반환.

    ``trash_scenario`` 는 손자 묶음을 기준시각 40일 전(만료)·루트 묶음을 5일 전(미만료)로 핀
    고정하고 retention=30 이므로, 기준시각을 ``now`` 로 주입하면 만료된 손자 묶음만 완전삭제된다.
    래퍼가 처리 묶음 수(int)를 돌려주고 만료 묶음만 DB 에서 deleted 로 전환됨을 관찰한다.
    """
    now = trash_scenario.reference

    purged = h.run_sweep(sweep_access, now)

    assert isinstance(purged, int), "스윕 래퍼는 처리한 묶음 수(int)를 반환해야 한다"
    assert purged >= 1, f"만료된 손자 묶음이 최소 1개 처리되어야 한다: {purged}"
    assert sweep_access.status_of(trash_scenario.grandchild_id) == "deleted", (
        "만료된 손자 묶음은 deleted 로 전환되어야 한다(주입 now 만료 경계)"
    )
    assert sweep_access.status_of(trash_scenario.root_id) == "trashed", (
        "미만료 루트 묶음은 자식 만료에 끌려가지 않고 trashed 로 유지되어야 한다(INV-12)"
    )
