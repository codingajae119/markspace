"""휴지통 권한 게이팅 통합 스위트 — s10 접근 경계 e2e (Task 4.1 / s10 Req 1.7·1.8·2.5·3.4·
5.1·5.2·5.3·5.5·6.3, INV-1·2·3, design §Testing Strategy → Integration Tests(권한 게이팅),
§TrashRouter API Contract, §Error Handling).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕**s10**) + **실제 세션 쿠키** 위에서 s10
휴지통 3개 라우트의 게이트를 mock 없이 관찰한다. 판정은 s05 가 채운 실제 `workspace_member`
데이터 위에서 s01 `require_ws_role` resolver 가 수행하고, `/trash/{bundleId}/*` 는 s10 묶음→WS
어댑터(`ws_role_for_bundle`)가 묶음 루트 문서 id 로 workspace_id 를 추출해 위임한다. 휴지통
권한은 **워크스페이스 단위**(문서·묶음별 개별 권한 없음, INV-1)이므로 editor B 가 editor A 의
삭제분 묶음을 목록·복구·완전삭제할 수 있음을 검증한다(Req 1.6/5). 게이트가 오작동하면 단언을
약화시키지 않고 실제 회귀(s10 어댑터 / s01 resolver / s05 멤버십 데이터)를 그대로 표면화한다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다.

`ws_scenario`(L3 conftest 재-export) 는 role별 독립 세션 클라이언트를 제공한다. WS 단위 권한
관측을 위해 두 번째 editor(B)를 admin 생성 + owner 멤버 추가 + 로그인으로 실제 provision 한다.
"""

from tests.integration_L1 import helpers as l1_helpers
from tests.integration_L3 import helpers

# 인증되었으나 대상 묶음 문서가 존재하지 않을 때 어댑터의 매핑-실패(→404)를 관측하기 위한 미존재 id.
MISSING_BUNDLE_ID = 999_999_999
# 존재하지 않는 워크스페이스 — require_ws_role 게이트가 비멤버로 판정(403, anti-enumeration).
MISSING_WORKSPACE_ID = 999_999_999


def _provision_member(scenario, harness, *, role: str, prefix: str):
    """admin 이 사용자를 만들고 owner 가 지정 role 로 멤버 추가한 뒤 그 자격으로 로그인한다.

    WS 단위 권한 시나리오에 필요한 두 번째 editor(B)를 실제 라우트로 provision 하는 setup
    헬퍼다(L2 conftest `_create_and_login` + owner 멤버 추가 관용 재현). (user_id, 인증 client)
    를 반환하며 client 는 자신의 세션 쿠키를 유지한다.
    """
    login_id = l1_helpers.unique_login_id(prefix)
    user_id = l1_helpers.create_user(
        scenario.admin_client, login_id, l1_helpers.DEFAULT_PASSWORD, name=prefix
    )
    member_resp = scenario.owner_client.post(
        f"/workspaces/{scenario.workspace_id}/members",
        json={"user_id": user_id, "role": role},
    )
    assert member_resp.status_code == 201, (
        f"{role} 멤버 추가 201 이어야 한다: {member_resp.status_code} {member_resp.text}"
    )
    client = harness.login(login_id, l1_helpers.DEFAULT_PASSWORD)
    return user_id, client


def _assert_error_response_shape(body: object) -> None:
    """관측된 에러 본문이 s01 `ErrorResponse` 형태를 따르는지 강제한다(Req 6.3).

    최소 계약(s01 §Errors): 문자열 `code`·`message` 키를 가지며 `field_errors` 키가 존재하고
    (직렬화 시 항상 포함, 값은 리스트 또는 null) 존재하면 리스트다(`{code, message, field_errors}`).
    """
    assert isinstance(body, dict), f"ErrorResponse 본문은 JSON 객체여야 한다: {body!r}"
    assert isinstance(body.get("code"), str), (
        f"ErrorResponse.code 는 문자열이어야 한다(s01 §Errors 드리프트): {body!r}"
    )
    assert isinstance(body.get("message"), str), (
        f"ErrorResponse.message 는 문자열이어야 한다(s01 §Errors 드리프트): {body!r}"
    )
    assert "field_errors" in body, (
        f"ErrorResponse 는 field_errors 키를 노출해야 한다(존재 시 리스트): {body!r}"
    )
    if body["field_errors"] is not None:
        assert isinstance(body["field_errors"], list), (
            f"ErrorResponse.field_errors 가 존재하면 리스트여야 한다: {body!r}"
        )


def _trashed_bundle(scenario, *, title: str) -> int:
    """editor A 가 문서를 만들고 삭제해 trashed 묶음을 만든 뒤 그 bundle_id(=문서 id)를 반환한다.

    자식이 없는 단일 문서이므로 삭제 시 자기 자신만 담긴 묶음이 된다(bundle_id = 문서 id).
    """
    doc = helpers.create_document(scenario.editor_client, scenario.workspace_id, title)
    helpers.delete_document(scenario.editor_client, doc["id"])
    return doc["id"]


def _listed_bundle_ids(client, workspace_id: int) -> set[int]:
    """`GET /workspaces/{id}/trash` 를 태워 200 을 단언하고 노출된 bundle_id 집합을 반환한다."""
    resp = client.get(f"/workspaces/{workspace_id}/trash")
    assert resp.status_code == 200, (
        f"휴지통 목록 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return {item["bundle_id"] for item in resp.json()["items"]}


# =============================================================================
# 1) viewer 거부 (INV-2) — Req 1.7·2.5·3.4·5.2·6.3
# =============================================================================


def test_viewer_denied_on_list_restore_purge(ws_scenario):
    """viewer 는 휴지통 목록·복구·완전삭제 모두 403 + code=forbidden(INV-2, Req 1.7·2.5·3.4).

    editor A 가 삭제한 묶음이 존재하는 상태에서 viewer 는 세 연산 전부 role 게이트에서 403 로
    거부된다(묶음 상태 변화 없음). 응답은 s01 `ErrorResponse` 규약을 따른다(Req 6.3).
    """
    ws_id = ws_scenario.workspace_id
    bundle_id = _trashed_bundle(ws_scenario, title="viewer거부대상")
    viewer = ws_scenario.viewer_client

    list_resp = viewer.get(f"/workspaces/{ws_id}/trash")
    assert list_resp.status_code == 403, (
        f"viewer 휴지통 목록은 403 이어야 한다(INV-2, Req 1.7): "
        f"{list_resp.status_code} {list_resp.text}"
    )
    assert list_resp.json()["code"] == "forbidden", "viewer 목록 거부 code=forbidden(Req 6.3)"
    _assert_error_response_shape(list_resp.json())

    restore_resp = viewer.post(f"/trash/{bundle_id}/restore")
    assert restore_resp.status_code == 403, (
        f"viewer 묶음 복구는 403 이어야 한다(INV-2, Req 2.5): "
        f"{restore_resp.status_code} {restore_resp.text}"
    )
    assert restore_resp.json()["code"] == "forbidden", "viewer 복구 거부 code=forbidden"

    purge_resp = viewer.delete(f"/trash/{bundle_id}")
    assert purge_resp.status_code == 403, (
        f"viewer 묶음 완전삭제는 403 이어야 한다(INV-2, Req 3.4): "
        f"{purge_resp.status_code} {purge_resp.text}"
    )
    assert purge_resp.json()["code"] == "forbidden", "viewer 완전삭제 거부 code=forbidden"


# =============================================================================
# 2) editor 통과 — 본인 삭제분 외 묶음 포함(WS 단위 권한, INV-1) — Req 5.1·2.6·3.x
# =============================================================================


def test_second_editor_can_list_restore_purge_others_bundles(ws_scenario, harness):
    """editor B(비-삭제자)가 editor A 의 삭제분 묶음을 목록·복구·완전삭제한다(WS 단위, INV-1).

    휴지통 권한은 워크스페이스 단위이므로(문서·묶음별 개별 권한 없음, Req 5.6/INV-1), A 가
    삭제한 묶음을 B 가 목록에서 보고(Req 1.6) 복구(Req 2.6)·완전삭제(204)할 수 있다. B 는 admin
    생성 + owner 가 editor 로 멤버 추가한 실제 두 번째 editor 다.
    """
    ws_id = ws_scenario.workspace_id
    editor_b_id, editor_b = _provision_member(
        ws_scenario, harness, role="editor", prefix="editorB"
    )
    assert editor_b_id != ws_scenario.editor_user_id, "두 editor 는 서로 다른 사용자여야 한다"

    # editor A 가 두 묶음을 만든다: 하나는 B 복구용, 하나는 B 완전삭제용.
    bundle_restore = _trashed_bundle(ws_scenario, title="B복구대상")
    bundle_purge = _trashed_bundle(ws_scenario, title="B완전삭제대상")

    # (목록) editor B 가 A 의 삭제분 묶음 전체를 본다(본인 삭제분 아님에도, Req 1.6/5).
    listed = _listed_bundle_ids(editor_b, ws_id)
    assert {bundle_restore, bundle_purge} <= listed, (
        f"editor B 는 A 의 삭제분 묶음을 목록에서 봐야 한다(WS 단위, Req 1.6): {listed}"
    )

    # (복구) editor B 가 A 의 묶음을 복구한다 → 204 (WS editor 권한만으로 충분, Req 2.6).
    assert editor_b.post(f"/trash/{bundle_restore}/restore").status_code == 204, (
        "editor B 는 A 의 삭제분 묶음을 복구할 수 있어야 한다(WS 단위 권한, Req 2.6)"
    )
    # (완전삭제) editor B 가 A 의 다른 묶음을 완전삭제한다 → 204.
    assert editor_b.delete(f"/trash/{bundle_purge}").status_code == 204, (
        "editor B 는 A 의 삭제분 묶음을 완전삭제할 수 있어야 한다(WS 단위 권한)"
    )


# =============================================================================
# 3) admin bypass (INV-3) — Req 5.3
# =============================================================================


def test_admin_bypass_on_list_restore_purge(ws_scenario):
    """비멤버 admin 은 휴지통 목록 200·복구 204·완전삭제 204 로 게이트를 bypass 한다(INV-3, Req 5.3).

    admin 은 이 워크스페이스의 멤버가 아니지만 어떤 권한 검사로도 차단되지 않는다(INV-3). 복구·
    완전삭제 각각 별도 묶음을 대상으로 해 두 경로를 모두 관측한다.
    """
    ws_id = ws_scenario.workspace_id
    admin = ws_scenario.admin_client
    bundle_restore = _trashed_bundle(ws_scenario, title="admin복구대상")
    bundle_purge = _trashed_bundle(ws_scenario, title="admin완전삭제대상")

    assert admin.get(f"/workspaces/{ws_id}/trash").status_code == 200, (
        "비멤버 admin 은 휴지통 목록을 bypass 로 조회할 수 있어야 한다(INV-3)"
    )
    assert admin.post(f"/trash/{bundle_restore}/restore").status_code == 204, (
        "비멤버 admin 은 묶음 복구를 bypass 로 수행할 수 있어야 한다(INV-3)"
    )
    assert admin.delete(f"/trash/{bundle_purge}").status_code == 204, (
        "비멤버 admin 은 묶음 완전삭제를 bypass 로 수행할 수 있어야 한다(INV-3)"
    )


# =============================================================================
# 4) 미인증 401 (Req 5.5) + 미존재 묶음 404 (Req 2.3/3.5) + 미존재 WS(Req 1.8)
# =============================================================================


def test_unauthenticated_denied_401_on_all_endpoints(ws_scenario, harness):
    """세션 없는 요청은 휴지통 목록·복구·완전삭제 모두 401 + code=unauthenticated(Req 5.5).

    미인증(세션 쿠키 없는 신규 client)은 role 판정·어댑터 매핑에 앞서 s01 `get_current_user`
    가 401 을 산출한다(묶음 문서 존재 여부와 무관).
    """
    ws_id = ws_scenario.workspace_id
    bundle_id = _trashed_bundle(ws_scenario, title="미인증대상")
    anon = harness.new_client()  # 로그인하지 않은 익명 client(세션 쿠키 없음).

    list_resp = anon.get(f"/workspaces/{ws_id}/trash")
    assert list_resp.status_code == 401, (
        f"미인증 목록은 401 이어야 한다(Req 5.5): {list_resp.status_code} {list_resp.text}"
    )
    assert list_resp.json()["code"] == "unauthenticated", "미인증 목록 code=unauthenticated"

    restore_resp = anon.post(f"/trash/{bundle_id}/restore")
    assert restore_resp.status_code == 401, (
        f"미인증 복구는 401 이어야 한다(Req 5.5): {restore_resp.status_code} {restore_resp.text}"
    )
    assert restore_resp.json()["code"] == "unauthenticated", "미인증 복구 code=unauthenticated"

    purge_resp = anon.delete(f"/trash/{bundle_id}")
    assert purge_resp.status_code == 401, (
        f"미인증 완전삭제는 401 이어야 한다(Req 5.5): {purge_resp.status_code} {purge_resp.text}"
    )
    assert purge_resp.json()["code"] == "unauthenticated", "미인증 완전삭제 code=unauthenticated"


def test_missing_bundle_document_maps_to_404_before_role_judgment(ws_scenario):
    """미존재 묶음 문서의 복구·완전삭제는 authorized editor 에게도 404 + code=not_found(Req 2.3·3.5).

    `/trash/{bundleId}/*` 는 s10 묶음→WS 어댑터가 묶음 루트 문서 id→workspace_id 매핑에 실패하면
    role 판정에 **앞서** 404 를 낸다 — editor(게이트 통과 자격)로 호출해도 문서가 없으면 403 이
    아니라 404 다. 응답은 s01 `ErrorResponse` 규약을 따른다(Req 6.3).
    """
    editor = ws_scenario.editor_client

    restore_resp = editor.post(f"/trash/{MISSING_BUNDLE_ID}/restore")
    assert restore_resp.status_code == 404, (
        f"미존재 묶음 복구는 authorized editor 에게도 404 여야 한다(어댑터 매핑 실패, Req 2.3): "
        f"{restore_resp.status_code} {restore_resp.text}"
    )
    assert restore_resp.json()["code"] == "not_found", "미존재 묶음 복구 code=not_found(Req 6.3)"
    _assert_error_response_shape(restore_resp.json())

    purge_resp = editor.delete(f"/trash/{MISSING_BUNDLE_ID}")
    assert purge_resp.status_code == 404, (
        f"미존재 묶음 완전삭제는 authorized editor 에게도 404 여야 한다(어댑터 매핑 실패, Req 3.5): "
        f"{purge_resp.status_code} {purge_resp.text}"
    )
    assert purge_resp.json()["code"] == "not_found", "미존재 묶음 완전삭제 code=not_found"


def test_nonexistent_workspace_list_yields_403_not_404(ws_scenario):
    """존재하지 않는 워크스페이스 휴지통 목록은 비멤버 editor 에게 403(404 아님) — Req 1.8 정합.

    tasks.md §Implementation Notes(3.1, Req 1.8 정합 갭): `GET /workspaces/{id}/trash` 는
    `require_ws_role(EDITOR)` 게이트로만 판정하므로(존재 선검사 없음) 존재하지 않는 워크스페이스는
    404 가 아니라 **403**(비멤버 처리)을 낸다. 이는 워크스페이스 존재를 비멤버에게 노출하지 않는
    anti-enumeration 관점에서 옳으며 s07 `GET /workspaces/{id}/documents` 와 동일하다(L3 통과).
    따라서 여기서는 404 가 아니라 403 을 단언한다(design §Error Handling 표의 404 는 게이트 구조상
    도달 불가; s11(L4) 재검증 항목).
    """
    # editor A 는 실제 워크스페이스의 editor 멤버이지만 존재하지 않는 워크스페이스의 비멤버다.
    resp = ws_scenario.editor_client.get(f"/workspaces/{MISSING_WORKSPACE_ID}/trash")
    assert resp.status_code == 403, (
        f"존재하지 않는 워크스페이스 휴지통 목록은 403(비멤버 처리)이어야 한다(Req 1.8 정합): "
        f"{resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "forbidden", "미존재 WS 목록 거부 code=forbidden(anti-enumeration)"
