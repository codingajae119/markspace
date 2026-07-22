"""admin override 스위트 — 비멤버 WS bypass·전체 목록 (Task 2.3 / Req 4.1~4.3, INV-3).

`s01` `require_ws_role` resolver 가 요청자의 `AuthContext.is_admin` 을 보고 role 판정
이전에 admin 을 무조건 통과시키는지(admin bypass, docs 2.6, INV-3)를 mock 없이 e2e 로
관찰하는 외부 관찰자 스위트다. 대조 기준은 `ws_scenario` 의 admin 이 **해당 워크스페이스의
멤버가 아니라는** 사실이다(워크스페이스는 owner 사용자가 생성했고 admin 은 멤버로 추가되지
않았다). 따라서 admin 의 통과는 멤버십이 아니라 오로지 admin bypass 로만 설명된다. 게이트가
오작동하면(비멤버 admin 이 차단되면) 단언을 약화시키지 않고 실제 회귀를 표면화한다.

관찰 대상 게이트(`app/workspace/router.py`):
- viewer 게이트 = `GET /workspaces/{id}` → `require_ws_role(VIEWER)`.
- owner 게이트 = `PATCH /workspaces/{id}` · `POST /workspaces/{id}/members`
  → `require_ws_role(OWNER)`.
- 목록 = `GET /workspaces` → admin 은 멤버 스코프에 제한되지 않고 전체를 본다.

단언 그룹:
- **viewer 게이트 bypass(4.1)**: 비멤버 admin 이 `GET /workspaces/{id}` 200. 같은 호출에서
  비-admin 비멤버(`nonmember_client`)는 403 임을 대조로 단언해 200 이 "열린 접근"이 아니라
  admin bypass 때문임을 증명한다(INV-1 비멤버 차단 vs INV-3 admin bypass).
- **owner 게이트 bypass(4.2, INV-3)**: 비멤버 admin 이 `PATCH /workspaces/{id}` 200 이고,
  `POST /workspaces/{id}/members` 로 신규 사용자를 추가해 201(게이트 통과 후 서비스가 실제로
  멤버를 추가) 임을 관찰한다.
- **전체 목록 가시성(4.3)**: admin 의 `GET /workspaces` 가 `Page` 형태이고 자신이 멤버가 아닌
  시나리오 `workspace_id` 를 포함함을 단언한다(멤버 스코프 미제한). 대조로 비-admin 비멤버의
  목록에는 같은 `workspace_id` 가 없음을 단언해 admin 목록이 실제로 전체 스코프임을 증명한다.

각 테스트는 함수 스코프 `ws_scenario` 로 **독립된** 워크스페이스를 받으므로 테스트 간 상태
간섭이 없다.
"""

from tests.integration_L2 import helpers


# --- 관리(owner) 게이트 bypass 대조 (s26 Req 4.1/5.4, INV-3) ------------------------


def test_admin_bypasses_management_gate_on_nonmember_workspace(ws_scenario):
    """관리 게이트 bypass: 비멤버 admin 은 `PATCH /workspaces/{id}` 200, 비-admin 비멤버는 403.

    s26 읽기 전역 개방으로 `GET /workspaces/{id}`(읽기)는 비멤버도 200 이므로 더 이상 admin
    bypass 를 대조로 증명하지 못한다. 따라서 관리(owner 전용) 게이트인 `PATCH /workspaces/{id}`
    로 대조한다: 비멤버 admin 은 owner 게이트를 admin bypass 로 통과해 200 이고(INV-3), 같은
    호출에서 비-admin 비멤버는 403 으로 차단된다(관리 owner 전용, Req 5.4). admin 의 200 이
    열린 접근이 아니라 오직 admin bypass 때문임을 증명한다.
    """
    ws_id = ws_scenario.workspace_id

    admin_resp = helpers.attempt_update_settings(
        ws_scenario.admin_client, ws_id, is_shareable=True
    )
    assert admin_resp.status_code == 200, (
        f"비멤버 admin 은 관리(owner) 게이트를 bypass 로 통과해 200 이어야 한다(4.1, INV-3): "
        f"{admin_resp.status_code} {admin_resp.text}"
    )

    # 대조: 비-admin 비멤버는 같은 관리 게이트에서 403 → 200 은 열린 접근이 아니라 admin bypass.
    nonmember_resp = helpers.attempt_update_settings(
        ws_scenario.nonmember_client, ws_id, is_shareable=True
    )
    assert nonmember_resp.status_code == 403, (
        f"비-admin 비멤버는 관리(owner) 게이트에서 403 으로 차단되어야 한다"
        f"(Req 5.4, admin 200 이 열린 접근이 아님을 증명): "
        f"{nonmember_resp.status_code} {nonmember_resp.text}"
    )


def test_workspace_detail_read_open_to_nonmember(ws_scenario):
    """읽기 전역 개방 대조(s26 Req 3.8): 비멤버 admin·비-admin 비멤버 모두 `GET` 200.

    읽기 경로는 admin bypass 여부와 무관하게 활성 사용자면 200 이다(멤버십 요구 없음). 비멤버
    admin 과 비-admin 비멤버(`nonmember_client`) 모두 `GET /workspaces/{id}` 200 임을 관찰해,
    읽기 게이트가 열려 있음을 관리 게이트 bypass 대조와 분리해 확정한다(Req 3.8·7.2).
    """
    ws_id = ws_scenario.workspace_id

    admin_read = helpers.attempt_get_workspace(ws_scenario.admin_client, ws_id)
    assert admin_read.status_code == 200, (
        f"admin 읽기는 200 이어야 한다: {admin_read.status_code} {admin_read.text}"
    )

    nonmember_read = helpers.attempt_get_workspace(
        ws_scenario.nonmember_client, ws_id
    )
    assert nonmember_read.status_code == 200, (
        f"비-admin 비멤버도 읽기 전역 개방으로 200 이어야 한다(403 아님, Req 3.8): "
        f"{nonmember_read.status_code} {nonmember_read.text}"
    )
    assert nonmember_read.json().get("role") is None, (
        f"비멤버 호출자 관점 role 은 null 이어야 한다(Req 3.5): {nonmember_read.text}"
    )


# --- owner 게이트 bypass (Req 4.2, INV-3) ------------------------------------------


def test_admin_bypasses_owner_gate_on_nonmember_workspace(ws_scenario):
    """owner 게이트 bypass: 비멤버 admin 이 PATCH 200·멤버 추가 201(모든 게이트 bypass, INV-3).

    admin 은 이 워크스페이스의 멤버가 아니지만 owner 요구 게이트(`require_ws_role(OWNER)`)를
    admin bypass 로 통과한다. `PATCH /workspaces/{id}`(설정 변경) 200 과
    `POST /workspaces/{id}/members`(신규 사용자 추가) 201 을 모두 관찰해, viewer 게이트뿐
    아니라 owner 게이트에서도 bypass 가 성립함을 증명한다(4.2). 멤버 추가 대상은 아직 멤버가
    아닌 신규 사용자여서 게이트 통과 후 서비스가 실제로 201 을 반환한다.
    """
    ws_id = ws_scenario.workspace_id

    patch_resp = helpers.attempt_update_settings(
        ws_scenario.admin_client, ws_id, is_shareable=True
    )
    assert patch_resp.status_code == 200, (
        f"비멤버 admin 은 PATCH owner 게이트를 bypass 로 통과해 200 이어야 한다"
        f"(4.2, INV-3): {patch_resp.status_code} {patch_resp.text}"
    )

    # 신규(비멤버) 대상 사용자를 admin 경로로 생성 → 멤버 추가가 실제 201 이 되도록 한다.
    fresh_user_id = helpers.l1_helpers.create_user(
        ws_scenario.admin_client,
        helpers.l1_helpers.unique_login_id("t"),
        name="대상",
    )
    add_resp = helpers.attempt_add_member(
        ws_scenario.admin_client, ws_id, fresh_user_id, "member"
    )
    assert add_resp.status_code == 201, (
        f"비멤버 admin 은 멤버 추가 owner 게이트를 bypass 로 통과하고 서비스가 멤버를 "
        f"추가해 201 이어야 한다(4.2, INV-3): {add_resp.status_code} {add_resp.text}"
    )


# --- 전체 목록 가시성 (Req 4.3) -----------------------------------------------------


def test_admin_list_is_not_member_scoped(ws_scenario):
    """전체 목록: `GET /workspaces` 가 호출자가 멤버가 아닌 workspace_id 를 포함한다(4.3).

    목록 읽기 전역 개방 이후 목록은 admin·비-admin 모두 멤버 스코프에 제한되지 않는다. 응답이
    `Page` 형태(`items`·`total`)이고 멤버가 아닌 시나리오 `workspace_id` 가 `items` 에 나타남을
    admin 과 비-admin 비멤버 **양쪽에서** 단언한다. 즉 가시성은 전역이며, 권한 차이는 목록 포함
    여부가 아니라 각 항목의 `role`(비멤버는 null)과 쓰기 게이트로만 표현된다.
    """
    ws_id = ws_scenario.workspace_id

    admin_resp = ws_scenario.admin_client.get("/workspaces")
    assert admin_resp.status_code == 200, (
        f"admin 목록 조회는 200 이어야 한다(4.3): "
        f"{admin_resp.status_code} {admin_resp.text}"
    )
    admin_page = admin_resp.json()
    assert "items" in admin_page and "total" in admin_page, (
        f"목록 응답은 Page 형태(items·total)여야 한다(s01 Base Schemas): {admin_page}"
    )
    admin_ws_ids = {item["id"] for item in admin_page["items"]}
    assert ws_id in admin_ws_ids, (
        f"admin 목록은 멤버 스코프에 제한되지 않아 비멤버 workspace_id={ws_id} 를 포함해야 "
        f"한다(4.3): {admin_page}"
    )

    # 비-admin 비멤버 목록도 동일하게 이 워크스페이스를 포함한다(목록 읽기 전역 개방).
    nonmember_resp = ws_scenario.nonmember_client.get("/workspaces")
    assert nonmember_resp.status_code == 200, (
        f"비멤버 목록 조회도 200 이어야 한다: "
        f"{nonmember_resp.status_code} {nonmember_resp.text}"
    )
    nonmember_page = nonmember_resp.json()
    nonmember_items = {item["id"]: item for item in nonmember_page["items"]}
    assert ws_id in nonmember_items, (
        f"비-admin 비멤버 목록도 멤버가 아닌 workspace_id={ws_id} 를 포함해야 한다"
        f"(목록 읽기 전역 개방): {nonmember_page}"
    )
    assert nonmember_items[ws_id]["role"] is None, (
        f"비멤버 항목의 role 은 null 이어야 한다(가시성은 전역, 권한은 멤버십에서만 산출): "
        f"{nonmember_items[ws_id]}"
    )
