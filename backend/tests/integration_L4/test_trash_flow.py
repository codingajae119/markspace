"""휴지통 흐름 스위트 — s10 휴지통 목록·복구·완전삭제 API가 s07 엔진 primitive 를 재사용해
동작함을 관찰 (Task 2.3 / Req 4.1·4.2·4.3·4.4·4.5, design §TrashFlowSuite; §System Flows
"휴지통 복구/완전삭제 — 엔진 위임 경계(라우터 경유)"; s10 6.5·6.9·6.11·INV-2·10 교차참조).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕**s10**) + **실제 세션 쿠키** 위에서
s10 휴지통 3개 라우트(카탈로그 행 29~31)를 mock 없이 결합 검증한다. 상태 전이(복구·완전삭제)는
s07 `DocumentStateEngine` primitive(`restore_bundle`·`purge_bundle`) 소관이며 s10 은 위임만
하므로, 이 스위트는 **실제 라우터**(`POST /trash/{bundleId}/restore`·`DELETE /trash/{bundleId}`·
`GET /workspaces/{id}/trash`)를 태워 전이를 유발하고 그 결과를 **엔진 primitive/DB 관찰**로
확인한다(테스트가 status/trashed_at 을 손으로 고치지 않는다). 게이트 판정은 s05 가 채운 실제
`workspace_member` 데이터 위에서 s01 `require_ws_role` resolver 가 수행하고, `/trash/{bundleId}/*`
는 s10 묶음→WS 어댑터(`ws_role_for_bundle`)가 묶음 루트 문서 id → workspace_id 를 매핑해 위임
한다. 게이트·어댑터·서비스·엔진이 오작동하면 단언을 약화시키지 않고 실제 회귀를 그대로
표면화한다.

시나리오 셋업은 `trash_scenario`(L4 conftest) 가 제공하는 **독립 묶음 2개**를 쓴다: 손자 단독
묶음(bundle_id = 손자 문서 id, 기준시각 40일 전에 trashed 로 핀) 과 루트+자식 묶음(bundle_id =
루트 문서 id, 5일 전에 trashed 로 핀). 두 묶음은 서로 다른 trashed_at 으로 결정적으로 분리되어
있어 목록·복구 위치·완전삭제 격리·404 경계를 하나의 셋업 위에서 표현한다. 복구 위치 규칙(6.5)
중 "부모 active → 부모 밑" 분기는 trashed 트리만 있는 `trash_scenario` 로는 만들 수 없으므로
fresh `ws_scenario` 위에 부모(active)+자식을 만들고 자식만 삭제해 명시적으로 구성한다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다.
"""

from datetime import datetime, timedelta

from app.models import Document
from tests.integration_L4 import helpers as h

l3_helpers = h.l3_helpers
l1_helpers = h.l1_helpers
l2_helpers = h.l2_helpers

# 인증되었으나 대상 묶음 문서가 존재하지 않을 때 어댑터 매핑-실패(→404)를 관측하기 위한 미존재 id.
MISSING_BUNDLE_ID = 999_999_999


# =============================================================================
# 관찰 헬퍼 — DB 직접 관측·엔진 primitive 관측·목록 파싱(테스트가 전이를 손으로 만들지 않음)
# =============================================================================


def _doc_row(harness, document_id: int) -> dict | None:
    """부팅 앱과 동일 세션 팩토리로 문서 행의 관찰 필드를 신규 세션으로 직접 관측한다(없으면 None).

    반환값이 None 이면 물리 행이 존재하지 않음을 뜻한다(물리 삭제 부재 관측용). deleted/active
    전이·`trashed_at` NULL화/보존·복구 위치(`parent_id`)를 실제 DB 로 확인하는 데 쓴다(테스트는
    이 값을 읽기만 하고 쓰지 않는다 — 전이는 실제 라우터가 수행).
    """
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return None
        return {
            "status": doc.status,
            "trashed_at": doc.trashed_at,
            "parent_id": doc.parent_id,
        }


def _bundle_ids(page: dict) -> set[int]:
    """`Page[TrashBundleRead]` dict 에서 노출된 bundle_id 집합을 반환한다."""
    return {item["bundle_id"] for item in page["items"]}


def _find_bundle(page: dict, bundle_id: int) -> dict | None:
    """`Page[TrashBundleRead]` dict 에서 지정 bundle_id 묶음을 찾는다(없으면 None)."""
    for item in page["items"]:
        if item["bundle_id"] == bundle_id:
            return item
    return None


def _assert_bundle_read_shape(bundle: dict) -> None:
    """관측된 묶음 항목이 s10 `TrashBundleRead` 규약(s01 §TrashSchemas)을 따르는지 강제한다(Req 4.1).

    계약: bundle_id·root_document_id·root_title·workspace_id·trashed_at·expires_at·member_count·
    members(각 구성원 id·parent_id·title)를 갖는다.
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


def _assert_expires_math(bundle: dict, retention_days: int) -> None:
    """묶음의 `expires_at = trashed_at + trash_retention_days`(묶음별 독립 산정, Req 4.1·6.11).

    서비스가 각 묶음의 공통 `trashed_at` 에 워크스페이스 보관일을 더해 만료 예정을 투영하므로,
    알려진 retention 에 대해 두 시각의 차가 정확히 그 일수여야 한다.
    """
    trashed_at = datetime.fromisoformat(bundle["trashed_at"])
    expires_at = datetime.fromisoformat(bundle["expires_at"])
    assert expires_at - trashed_at == timedelta(days=retention_days), (
        f"expires_at 은 trashed_at + {retention_days}일이어야 한다(Req 4.1): "
        f"{bundle['trashed_at']} → {bundle['expires_at']}"
    )


def _provision_editor(scenario, harness, *, prefix: str):
    """admin 이 사용자를 만들고 owner 가 EDITOR 로 멤버 추가한 뒤 그 자격으로 로그인한다(setup).

    "본인 삭제분 외 워크스페이스 전체 포함" 관측을 위한 **두 번째 editor(B)** 를 실제 라우트로
    provision 한다(L3 게이팅 스위트 관용 재사용). (user_id, 인증 client) 를 반환하며 client 는
    자신의 세션 쿠키를 유지한다.
    """
    login_id = l1_helpers.unique_login_id(prefix)
    user_id = l1_helpers.create_user(
        scenario.admin_client, login_id, l1_helpers.DEFAULT_PASSWORD, name=prefix
    )
    l2_helpers.add_member(scenario.owner_client, scenario.workspace_id, user_id, "editor")
    client = harness.login(login_id, l1_helpers.DEFAULT_PASSWORD)
    return user_id, client


# =============================================================================
# 1) 목록 — editor+ WS 전체 열람 · expires_at = trashed_at + retention (Req 4.1, 6.11)
# =============================================================================


def test_list_returns_ws_wide_bundles_with_expires_at(trash_scenario):
    """editor `GET /workspaces/{id}/trash` → `Page[TrashBundleRead]`로 WS 전체 묶음·만료 예정(Req 4.1).

    `trash_scenario` 는 손자 단독 묶음(bundle_id=손자)과 루트+자식 묶음(bundle_id=루트) 2개를
    서로 다른 trashed_at 으로 구성한다. editor 목록이 두 독립 묶음을 모두 노출하고(WS 전체),
    각 묶음이 `TrashBundleRead` 계약을 따르며 `expires_at = trashed_at + trash_retention_days`
    (묶음별 독립 산정)를 담음을 확인한다. 상태 전이 없는 순수 읽기 경로다.
    """
    editor = trash_scenario.editor_client
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id
    retention = trash_scenario.retention_days

    page = h.list_trash(editor, ws_id)
    assert isinstance(page.get("items"), list) and isinstance(page.get("total"), int), (
        f"Page 규약(items 리스트·total 정수)을 따라야 한다(s01 §BaseSchemas): {page!r}"
    )

    # 두 독립 묶음이 모두 노출된다(비흡수 — 손자 묶음이 루트 묶음에 흡수되지 않음).
    assert {root_id, grandchild_id} <= _bundle_ids(page), (
        f"손자 단독 묶음과 루트+자식 묶음이 모두 목록에 있어야 한다(WS 전체, Req 4.1): "
        f"{_bundle_ids(page)}"
    )
    assert page["total"] >= 2, "두 독립 묶음이 total 에 집계되어야 한다(Req 4.1)"

    # 루트+자식 묶음: 구성원 2개(루트·자식), expires_at 산정.
    root_bundle = _find_bundle(page, root_id)
    _assert_bundle_read_shape(root_bundle)
    assert root_bundle["workspace_id"] == ws_id, "묶음 workspace_id 는 소속 WS 여야 한다"
    assert root_bundle["member_count"] == 2, "루트 삭제 캐스케이드 구성원은 루트+자식 2개(비흡수)"
    assert {m["id"] for m in root_bundle["members"]} == {root_id, child_id}, (
        f"루트 묶음 구성원은 루트+자식이어야 한다(손자 비흡수): "
        f"{[m['id'] for m in root_bundle['members']]}"
    )
    _assert_expires_math(root_bundle, retention)

    # 손자 단독 묶음: 구성원 1개, 서로 다른 trashed_at → 독립 만료 예정.
    gc_bundle = _find_bundle(page, grandchild_id)
    _assert_bundle_read_shape(gc_bundle)
    assert {m["id"] for m in gc_bundle["members"]} == {grandchild_id}, (
        f"손자 묶음 구성원은 손자 단독이어야 한다: {[m['id'] for m in gc_bundle['members']]}"
    )
    _assert_expires_math(gc_bundle, retention)
    assert gc_bundle["trashed_at"] != root_bundle["trashed_at"], (
        "두 묶음은 서로 다른 trashed_at(독립 보관 기준)을 가져야 한다(Req 4.1)"
    )


def test_list_includes_bundles_deleted_by_another_editor(trash_scenario, harness):
    """editor A 목록이 editor B(비-삭제자)의 삭제분 묶음도 포함한다(본인 삭제분 외 WS 전체, Req 4.1).

    휴지통은 워크스페이스 단위이므로(문서·묶음별 개별 소유 없음), 같은 WS 의 두 번째 editor(B)가
    삭제한 묶음을 editor A 가 목록에서 본다. B 는 admin 생성 + owner 가 editor 로 멤버 추가한 실제
    두 번째 editor 다.
    """
    scenario = trash_scenario.scenario
    editor_a = trash_scenario.editor_client
    ws_id = trash_scenario.workspace_id

    editor_b_id, editor_b = _provision_editor(scenario, harness, prefix="editorB")
    assert editor_b_id != scenario.editor_user_id, "두 editor 는 서로 다른 사용자여야 한다"

    # editor B 가 자기 문서를 만들고 삭제 → B 소유(가 아닌, WS 소유) 단독 묶음.
    doc_b = l3_helpers.create_document(editor_b, ws_id, "B가삭제한문서")
    l3_helpers.delete_document(editor_b, doc_b["id"])

    # editor A 가 A 의 두 묶음 + B 의 묶음을 모두 본다(WS 전체, 본인 삭제분 아님에도).
    listed = _bundle_ids(h.list_trash(editor_a, ws_id))
    assert {trash_scenario.root_id, trash_scenario.grandchild_id, doc_b["id"]} <= listed, (
        f"editor A 는 B 의 삭제분 묶음까지 WS 전체를 봐야 한다(Req 4.1): {listed}"
    )


# =============================================================================
# 2) 복구 — 엔진 restore_bundle 위임 · 복구 위치 규칙(6.5) · 목록 소멸 (Req 4.2)
# =============================================================================


def test_restore_delegates_members_active_and_disappears_from_list(
    trash_scenario, harness, engine_access
):
    """editor 복구 → 엔진 `restore_bundle` 위임: 구성원 active·trashed_at=NULL·목록/엔진에서 소멸(Req 4.2).

    루트+자식 묶음을 실제 라우터(`POST /trash/{root}/restore`)로 복구한다. s10 은 상태 전이를
    재구현하지 않고 s07 엔진에 위임하므로, 결과를 DB 관찰(구성원 status=active·trashed_at=NULL)과
    엔진 관찰(`identify_bundles` 에서 루트 묶음 소멸)·API 관찰(휴지통 목록에서 소멸)로 교차 확인
    한다. 손자 묶음은 단독 복구 대상이 아니므로 불변으로 남는다.
    """
    editor = trash_scenario.editor_client
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id

    h.restore_bundle_via_api(editor, root_id)  # 실제 라우터 204(엔진 위임).

    # (DB) 루트+자식 구성원 전원 active·trashed_at=NULL(엔진 복구 전이 결과).
    for doc_id in (root_id, child_id):
        row = _doc_row(harness, doc_id)
        assert row is not None and row["status"] == "active", (
            f"복구 구성원(id={doc_id})은 active 여야 한다(Req 4.2): {row}"
        )
        assert row["trashed_at"] is None, (
            f"복구 구성원(id={doc_id})은 trashed_at=NULL 이어야 한다(Req 4.2): {row}"
        )

    # (API) 복구된 루트 묶음은 목록에서 사라지고 손자 묶음은 그대로 남는다.
    listed = _bundle_ids(h.list_trash(editor, ws_id))
    assert root_id not in listed, "복구된 루트 묶음은 휴지통 목록에서 사라져야 한다(Req 4.2)"
    assert grandchild_id in listed, "복구되지 않은 손자 묶음은 목록에 남아야 한다(단독 복구)"

    # (엔진) identify_bundles 에서도 루트 묶음이 사라지고 손자 묶음만 남는다(라우터 커밋 관찰).
    engine_roots = {b.root_document_id for b in l3_helpers.identify_bundles(engine_access, ws_id)}
    assert root_id not in engine_roots and grandchild_id in engine_roots, (
        f"엔진 관찰에서도 루트 묶음만 소멸하고 손자 묶음은 남아야 한다(엔진 위임, Req 4.2): {engine_roots}"
    )


def test_restore_location_under_active_parent(ws_scenario, harness):
    """복구 위치(6.5) — 복구 시점 부모가 active 이면 루트가 그 부모 밑으로 복귀한다(Req 4.2).

    fresh WS 에 부모(active, root)와 자식을 만들고 **자식만** 삭제한다(묶음 루트=자식, 부모는
    active 유지). 실제 라우터로 자식 묶음을 복구하면 엔진이 복구 시점 부모 상태를 보고 부모가
    active 이므로 자식을 원래 부모 밑(parent_id 유지)으로 되돌린다. 복구 위치를 DB 로 확인한다.
    """
    editor = ws_scenario.editor_client
    ws_id = ws_scenario.workspace_id

    parent = l3_helpers.create_document(editor, ws_id, "활성부모")
    child = l3_helpers.create_document(editor, ws_id, "복귀자식", parent_id=parent["id"])
    l3_helpers.delete_document(editor, child["id"])  # 자식만 삭제 → 묶음 루트=자식.

    h.restore_bundle_via_api(editor, child["id"])  # 실제 라우터 204.

    row = _doc_row(harness, child["id"])
    assert row is not None and row["status"] == "active" and row["trashed_at"] is None, (
        f"복구 자식은 active·trashed_at=NULL 이어야 한다(Req 4.2): {row}"
    )
    assert row["parent_id"] == parent["id"], (
        f"부모 active 복구는 원래 부모 밑(parent_id 유지)으로 복귀해야 한다(6.5): "
        f"기대={parent['id']} 관측={row['parent_id']}"
    )


def test_restore_location_non_active_parent_goes_to_root(trash_scenario, harness):
    """복구 위치(6.5) — 복구 시점 부모가 non-active 이면 루트가 root 레벨로 복귀한다(parent_id=NULL, Req 4.2).

    `trash_scenario` 에서 손자 묶음의 부모(자식)는 루트+자식 묶음의 일원으로 trashed(non-active)
    상태다. 손자 묶음을 실제 라우터로 복구하면 엔진이 복구 시점 부모 상태를 보고 부모가 active 가
    아니므로 손자를 root 레벨로 복귀시켜 `parent_id=NULL` 로 만든다(non-active/부재 분기). 부모
    (자식)는 여전히 trashed 로 남아 손자를 재흡수하지 않는다(단독 복구).
    """
    editor = trash_scenario.editor_client
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id

    h.restore_bundle_via_api(editor, grandchild_id)  # 실제 라우터 204(엔진 위임).

    gc = _doc_row(harness, grandchild_id)
    assert gc is not None and gc["status"] == "active" and gc["trashed_at"] is None, (
        f"복구 손자는 active·trashed_at=NULL 이어야 한다(Req 4.2): {gc}"
    )
    assert gc["parent_id"] is None, (
        f"부모 non-active 복구는 루트를 parent_id=NULL 로 root 레벨에 복귀시켜야 한다(6.5): "
        f"관측 parent_id={gc['parent_id']}"
    )
    # 부모(자식)는 단독 복구되지 않고 여전히 trashed(자동 재흡수 없음).
    child = _doc_row(harness, child_id)
    assert child["status"] == "trashed", (
        f"손자 단독 복구는 부모(자식)를 함께 되살리지 않아야 한다(6.5): {child}"
    )


# =============================================================================
# 3) 완전삭제 — 엔진 purge_bundle 위임 · 원자 deleted · 물리 보존 · 타 묶음 불변 (Req 4.3)
# =============================================================================


def test_purge_delegates_atomic_deleted_preserves_and_isolated(
    trash_scenario, harness, engine_access
):
    """editor 완전삭제 → 엔진 `purge_bundle` 위임: 구성원 전체 원자 deleted·물리 보존·타 묶음 불변(Req 4.3).

    루트+자식 묶음을 실제 라우터(`DELETE /trash/{root}`)로 완전삭제한다. s10 은 상태 전이를 엔진에
    위임하므로 결과를 DB·엔진 관찰로 확인한다:

    - **원자 deleted(INV-7)**: 구성원 전체가 함께 status=deleted 종착(부분 전이 없음).
    - **물리 보존(INV-10·4)**: 완전삭제 후에도 두 행이 물리적으로 존재(_doc_row 가 None 아님)·
      `trashed_at` 보존(NULL화 없음).
    - **요청 묶음에만 적용**: 손자 묶음(구성원·trashed_at)이 불변으로 남는다(타 묶음 격리).
    """
    editor = trash_scenario.editor_client
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id

    gc_before = _doc_row(harness, grandchild_id)  # 완전삭제 전 손자 스냅(불변 비교 기준).

    h.purge_bundle_via_api(editor, root_id)  # 실제 라우터 204(엔진 위임, 비가역).

    # (DB) 루트+자식 원자 deleted·물리 보존·trashed_at 보존.
    for doc_id in (root_id, child_id):
        row = _doc_row(harness, doc_id)
        assert row is not None, (
            f"완전삭제는 물리 삭제가 아니라 상태 전환이다 — 행이 존재해야 한다(INV-4): id={doc_id}"
        )
        assert row["status"] == "deleted", (
            f"완전삭제 구성원(id={doc_id})은 deleted 종착이어야 한다(원자성 INV-7·10): {row}"
        )
        assert row["trashed_at"] is not None, (
            f"완전삭제는 trashed_at 을 보존해야 한다(NULL화 없음, INV-10): id={doc_id} {row}"
        )

    # (DB) 손자 묶음은 완전삭제의 영향을 받지 않는다(요청 묶음에만 적용, 타 묶음 격리).
    gc_after = _doc_row(harness, grandchild_id)
    assert gc_after == gc_before, (
        f"완전삭제는 다른 묶음(손자)의 status·trashed_at·parent_id 를 바꾸지 않아야 한다(Req 4.3): "
        f"이전={gc_before} 이후={gc_after}"
    )
    assert gc_after["status"] == "trashed", "손자 묶음은 여전히 trashed 여야 한다(간섭 없음)"

    # (엔진) identify_bundles 에서 루트 묶음은 소멸(deleted 미노출)하고 손자 묶음만 남는다.
    engine_roots = {b.root_document_id for b in l3_helpers.identify_bundles(engine_access, ws_id)}
    assert root_id not in engine_roots and grandchild_id in engine_roots, (
        f"완전삭제 후 엔진 관찰에서 루트 묶음만 소멸하고 손자 묶음은 남아야 한다(Req 4.3): {engine_roots}"
    )
    # (API) 휴지통 목록에서도 루트 묶음 소멸·손자 묶음 잔존.
    listed = _bundle_ids(h.list_trash(editor, ws_id))
    assert root_id not in listed and grandchild_id in listed, (
        f"완전삭제된 루트 묶음은 목록에서 사라지고 손자 묶음은 남아야 한다(Req 4.3): {listed}"
    )


# =============================================================================
# 4) 게이팅 — viewer/비멤버 403 · admin 비멤버 WS bypass (Req 4.4, INV-1·2·3)
# =============================================================================


def test_viewer_and_nonmember_denied_403(trash_scenario):
    """viewer·비멤버는 목록·복구·완전삭제 모두 403(INV-1·2), 묶음 상태 불변(Req 4.4).

    editor 가 삭제한 묶음이 있는 상태에서 viewer(멤버·읽기전용)와 비멤버는 세 연산 전부 role
    게이트에서 403 으로 거부된다. `require_ws_role(EDITOR)`(목록)·`ws_role_for_bundle(EDITOR)`
    (복구·완전삭제) 판정을 재구현 없이 통과시키지 않아야 한다. 거부 후 묶음이 여전히 trashed 로
    남음(상태 변화 없음)을 확인한다.
    """
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    grandchild_id = trash_scenario.grandchild_id

    for label, client in (
        ("viewer", trash_scenario.scenario.viewer_client),
        ("nonmember", trash_scenario.scenario.nonmember_client),
    ):
        assert h.attempt_list_trash(client, ws_id).status_code == 403, (
            f"{label} 휴지통 목록은 403 이어야 한다(INV-2/1, Req 4.4)"
        )
        assert h.attempt_restore_bundle(client, root_id).status_code == 403, (
            f"{label} 묶음 복구는 403 이어야 한다(INV-2/1, Req 4.4)"
        )
        assert h.attempt_purge_bundle(client, grandchild_id).status_code == 403, (
            f"{label} 묶음 완전삭제는 403 이어야 한다(INV-2/1, Req 4.4)"
        )

    # 거부는 상태를 바꾸지 않는다 — 두 묶음 모두 여전히 trashed.
    assert trash_scenario.status_of(root_id) == "trashed", "거부된 복구는 상태를 바꾸지 않아야 한다"
    assert trash_scenario.status_of(grandchild_id) == "trashed", (
        "거부된 완전삭제는 상태를 바꾸지 않아야 한다"
    )


def test_admin_bypass_on_non_member_workspace(trash_scenario):
    """비멤버 admin 은 목록 200·복구 204·완전삭제 204 로 게이트를 bypass 한다(INV-3, Req 4.4).

    `trash_scenario` 의 admin 은 이 워크스페이스의 멤버가 아니지만 어떤 권한 검사로도 차단되지
    않는다(INV-3). 손자 묶음은 복구로, 루트 묶음은 완전삭제로 각각 관측해 두 변경 경로 모두
    bypass 됨을 확인한다.
    """
    admin = trash_scenario.scenario.admin_client
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    grandchild_id = trash_scenario.grandchild_id

    assert h.attempt_list_trash(admin, ws_id).status_code == 200, (
        "비멤버 admin 은 휴지통 목록을 bypass 로 조회할 수 있어야 한다(INV-3)"
    )
    assert h.attempt_restore_bundle(admin, grandchild_id).status_code == 204, (
        "비멤버 admin 은 묶음 복구를 bypass 로 수행할 수 있어야 한다(INV-3)"
    )
    assert h.attempt_purge_bundle(admin, root_id).status_code == 204, (
        "비멤버 admin 은 묶음 완전삭제를 bypass 로 수행할 수 있어야 한다(INV-3)"
    )
    # bypass 로 실제 전이가 일어났음을 DB 로 확인(복구=active, 완전삭제=deleted).
    assert trash_scenario.status_of(grandchild_id) == "active", "admin 복구가 실제 전이돼야 한다"
    assert trash_scenario.status_of(root_id) == "deleted", "admin 완전삭제가 실제 전이돼야 한다"


# =============================================================================
# 5) 404 경계 — 문서 부재 어댑터 404 · 유효 묶음 루트 아님 엔진 404 (Req 4.5)
# =============================================================================


def test_missing_and_invalid_bundle_root_yield_404(trash_scenario):
    """복구·완전삭제 404 두 경계: 문서 부재 → 어댑터 게이트 404, 유효 묶음 루트 아님 → 엔진 404(Req 4.5).

    두 개의 서로 다른 404 원천을 authorized editor(게이트 통과 자격)로 관측한다:

    - **문서 부재(어댑터 단계)**: 존재하지 않는 bundleId 는 묶음→WS 어댑터가 workspace_id 매핑에
      실패해 role 판정에 **앞서** 404 를 낸다(editor 여도 403 아님).
    - **유효 묶음 루트 아님(엔진 단계)**: `child_id` 는 존재하는 trashed 문서지만 루트+자식 묶음의
      **비루트 구성원**이다(부모=루트가 같은 trashed_at 으로 trashed). 어댑터는 문서→WS 매핑에
      성공해 게이트를 통과시키지만, 서비스가 위임한 엔진 primitive 가 유효한 묶음 루트가 아니라며
      404 를 낸다. 두 경계를 복구·완전삭제 각각에서 확인한다.
    """
    editor = trash_scenario.editor_client
    child_id = trash_scenario.child_id  # 존재하는 trashed 비루트 구성원(엔진 단계 404 유도).

    # (어댑터 단계) 문서 부재 bundleId → authorized editor 에게도 404.
    assert h.attempt_restore_bundle(editor, MISSING_BUNDLE_ID).status_code == 404, (
        "미존재 묶음 문서 복구는 어댑터 매핑 실패로 404 여야 한다(Req 4.5)"
    )
    assert h.attempt_purge_bundle(editor, MISSING_BUNDLE_ID).status_code == 404, (
        "미존재 묶음 문서 완전삭제는 어댑터 매핑 실패로 404 여야 한다(Req 4.5)"
    )

    # (엔진 단계) 존재하지만 유효한 묶음 루트가 아닌 id(비루트 구성원) → 게이트 통과 후 엔진 404.
    assert h.attempt_restore_bundle(editor, child_id).status_code == 404, (
        "유효한 묶음 루트가 아닌 id(비루트 구성원) 복구는 엔진 단계에서 404 여야 한다(Req 4.5)"
    )
    assert h.attempt_purge_bundle(editor, child_id).status_code == 404, (
        "유효한 묶음 루트가 아닌 id(비루트 구성원) 완전삭제는 엔진 단계에서 404 여야 한다(Req 4.5)"
    )
    # 엔진 404 는 상태를 바꾸지 않는다 — 묶음이 여전히 trashed(엔진이 전이 전 검증에서 거부).
    assert trash_scenario.status_of(child_id) == "trashed", (
        "유효하지 않은 묶음 루트 요청은 상태를 바꾸지 않아야 한다(엔진 선검증 404)"
    )
