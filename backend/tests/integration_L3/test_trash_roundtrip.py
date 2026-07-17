"""휴지통 왕복 통합 스위트 — s10 휴지통 API e2e (Task 4.1 / s10 Req 1.1·2.1·3.1·6.2·6.5, INV-7,
design §Testing Strategy → Integration Tests(휴지통 왕복), §TrashRouter API Contract).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕**s10**) + **실제 세션 쿠키** 위에서 s10
휴지통 3개 라우트(카탈로그 행 29~31)를 mock 없이 관찰한다. s07 `DELETE /documents/{id}` 로
문서를 trashed 로 만든 뒤 `GET /workspaces/{id}/trash` → `POST /trash/{bundleId}/restore` →
재삭제 → `DELETE /trash/{bundleId}` 왕복이 실제 앱 컨텍스트에서 엔진 primitive
(`restore_bundle`·`purge_bundle`)를 **라우터를 통해** 소비함을 확인한다. 상태 종착
(deleted 복원 경로 없음, INV-7)은 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로 커밋된
행을 직접 관측해 단언한다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다.

`doc_tree_scenario`(L3 conftest) 는 editor 가 만든 실제 문서 트리(루트→자식→손자)를 제공하므로
루트 삭제 캐스케이드가 3개 구성원 묶음을 만든다(묶음 = 루트 문서 id).
"""

from datetime import datetime, timedelta

from app.models import Document, Workspace
from tests.integration_L3 import helpers


def _retention_days(harness, workspace_id: int) -> int:
    """부팅 앱과 동일 세션 팩토리로 워크스페이스 `trash_retention_days`(s05 설정값)를 관측한다."""
    with harness.session_local() as db:
        value = db.execute(
            Workspace.__table__.select().where(Workspace.id == workspace_id)
        ).mappings().one()["trash_retention_days"]
    return int(value)


def _status_of(harness, document_id: int) -> str | None:
    """부팅 앱이 커밋한 문서 행의 `status` 를 신규 세션으로 직접 관측한다(없으면 None)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.status


def _get_trash(client, workspace_id: int):
    """`GET /workspaces/{id}/trash` 를 태워 200 을 단언하고 파싱된 `Page` dict 를 반환한다."""
    resp = client.get(f"/workspaces/{workspace_id}/trash")
    assert resp.status_code == 200, (
        f"휴지통 목록 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _find_bundle(page: dict, bundle_id: int) -> dict | None:
    """`Page[TrashBundleRead]` dict 에서 지정 bundle_id 묶음을 찾는다(없으면 None)."""
    for item in page["items"]:
        if item["bundle_id"] == bundle_id:
            return item
    return None


def _assert_bundle_read_shape(bundle: dict) -> None:
    """관측된 묶음 항목이 s10 `TrashBundleRead` 규약을 따르는지 강제한다(Req 6.2).

    계약(design §TrashSchemas): bundle_id·root_document_id·root_title·workspace_id·
    trashed_at·expires_at·member_count·members(각 구성원 id·parent_id·title)를 갖는다.
    """
    for key in (
        "bundle_id",
        "root_document_id",
        "root_title",
        "workspace_id",
        "trashed_at",
        "expires_at",
        "member_count",
        "members",
    ):
        assert key in bundle, (
            f"TrashBundleRead 는 '{key}' 필드를 노출해야 한다(s10 §TrashSchemas 드리프트): {bundle!r}"
        )
    assert isinstance(bundle["members"], list), "members 는 리스트여야 한다"
    for member in bundle["members"]:
        for key in ("id", "parent_id", "title"):
            assert key in member, (
                f"TrashMemberRead 는 '{key}' 필드를 노출해야 한다: {member!r}"
            )


# =============================================================================
# 1) 휴지통 왕복 (핵심) — Req 1.1·2.1·3.1·6.5, INV-7
# =============================================================================


def test_trash_bundle_roundtrip_list_restore_repurge(doc_tree_scenario, harness):
    """삭제→목록→복구→재삭제→완전삭제 왕복: 엔진 primitive 가 라우터를 통해 소비됨(INV-7).

    editor 가 s07 `DELETE /documents/{root}` 로 루트 트리(루트→자식→손자)를 삭제하면 3개
    구성원 묶음(bundle_id = 루트 문서 id)이 만들어진다. 휴지통 목록이 그 묶음을 만료 예정
    시각과 함께 노출하고(Req 1.1·1.3·1.4), 복구로 목록에서 사라지며 문서가 active 로 돌아오고
    (Req 2.1), 재삭제 후 완전삭제로 deleted 종착(복원 경로 없음, INV-7)이 됨을 실제 앱
    컨텍스트에서 검증한다. deleted 관측은 부팅 앱과 동일 세션으로 커밋된 행을 직접 읽는다.
    """
    scenario = doc_tree_scenario.scenario
    editor = doc_tree_scenario.editor_client
    ws_id = doc_tree_scenario.workspace_id
    root_id = doc_tree_scenario.root_id
    child_id = doc_tree_scenario.child_id
    grandchild_id = doc_tree_scenario.grandchild_id
    root_title = doc_tree_scenario.root["title"]
    member_ids = {root_id, child_id, grandchild_id}

    # (1) s07 로 루트를 삭제 → 트리 전체가 하나의 trashed 묶음으로 캐스케이드(bundle_id=root).
    helpers.delete_document(editor, root_id)

    # (2) 휴지통 목록이 그 묶음을 노출한다(Req 1.1). 계약·필드·만료 예정 시각을 단언한다.
    page = _get_trash(editor, ws_id)
    assert page["total"] >= 1, "삭제한 묶음이 total 에 집계되어야 한다(Req 1.1)"
    bundle = _find_bundle(page, root_id)
    assert bundle is not None, "삭제한 루트 묶음이 휴지통 목록에 있어야 한다(bundle_id=root_id)"

    _assert_bundle_read_shape(bundle)
    assert bundle["bundle_id"] == root_id, "bundle_id 는 묶음 루트 문서 id 여야 한다"
    assert bundle["root_document_id"] == root_id, "root_document_id 는 루트 문서 id 여야 한다"
    assert bundle["root_title"] == root_title, "root_title 은 루트 문서 제목이어야 한다(Req 1.3)"
    assert bundle["workspace_id"] == ws_id, "묶음의 workspace_id 는 소속 워크스페이스여야 한다"
    assert bundle["member_count"] == 3, "루트 삭제 캐스케이드로 구성원은 3개여야 한다(Req 1.3)"
    assert {m["id"] for m in bundle["members"]} == member_ids, (
        "묶음 구성원 집합은 루트·자식·손자여야 한다(엔진 식별 결과 투영, Req 1.2)"
    )

    # (2') 만료 예정 시각 = 묶음 trashed_at + 워크스페이스 trash_retention_days (Req 1.4).
    trashed_at = datetime.fromisoformat(bundle["trashed_at"])
    expires_at = datetime.fromisoformat(bundle["expires_at"])
    retention = _retention_days(harness, ws_id)
    assert expires_at - trashed_at == timedelta(days=retention), (
        f"expires_at 은 trashed_at + {retention}일이어야 한다(Req 1.4): "
        f"{bundle['trashed_at']} → {bundle['expires_at']}"
    )

    # (3) 복구 → 204. 묶음이 목록에서 사라지고 문서가 active 로 돌아온다(Req 2.1).
    restore_resp = editor.post(f"/trash/{root_id}/restore")
    assert restore_resp.status_code == 204, (
        f"묶음 복구는 204 여야 한다(Req 2.1): {restore_resp.status_code} {restore_resp.text}"
    )
    after_restore = _get_trash(editor, ws_id)
    assert _find_bundle(after_restore, root_id) is None, (
        "복구된 묶음은 휴지통 목록에서 사라져야 한다(trashed 아님)"
    )
    for doc_id in member_ids:
        assert _status_of(harness, doc_id) == "active", (
            f"복구 후 구성원 문서(id={doc_id})는 active 로 돌아와야 한다(Req 2.1)"
        )

    # (4) 재삭제 후 완전삭제 → 204. 묶음이 목록에서 사라지고 문서가 deleted 종착이 된다(INV-7).
    helpers.delete_document(editor, root_id)
    purge_resp = editor.delete(f"/trash/{root_id}")
    assert purge_resp.status_code == 204, (
        f"묶음 완전삭제는 204 여야 한다(Req 3.1): {purge_resp.status_code} {purge_resp.text}"
    )
    after_purge = _get_trash(editor, ws_id)
    assert _find_bundle(after_purge, root_id) is None, (
        "완전삭제된 묶음은 휴지통 목록에서 사라져야 한다(deleted 는 노출 안 됨, INV-7)"
    )
    for doc_id in member_ids:
        assert _status_of(harness, doc_id) == "deleted", (
            f"완전삭제 후 구성원 문서(id={doc_id})는 deleted 종착이어야 한다(INV-7, 복원 경로 없음)"
        )


# =============================================================================
# 2) 페이지 계약 정합 — Req 6.2
# =============================================================================


def test_trash_list_conforms_to_page_contract(doc_tree_scenario, harness):
    """휴지통 목록 응답이 s01 `Page[TrashBundleRead]` 규약(`items`·`total`)을 따른다(Req 6.2).

    엔진 식별 결과가 라우터를 통해 s01 Base Schemas 규약으로 직렬화됨을 확인한다 — `items`
    (리스트)·`total`(정수)을 갖고 각 항목이 `TrashBundleRead` 형태다.
    """
    editor = doc_tree_scenario.editor_client
    ws_id = doc_tree_scenario.workspace_id
    root_id = doc_tree_scenario.root_id

    helpers.delete_document(editor, root_id)

    page = _get_trash(editor, ws_id)
    assert isinstance(page.get("items"), list), (
        f"Page 는 items 리스트를 가져야 한다(s01 §BaseSchemas 드리프트): {page!r}"
    )
    assert isinstance(page.get("total"), int), (
        f"Page 는 total 정수를 가져야 한다(s01 §BaseSchemas 드리프트): {page!r}"
    )
    bundle = _find_bundle(page, root_id)
    assert bundle is not None, "삭제한 묶음이 목록에 있어야 한다"
    _assert_bundle_read_shape(bundle)
