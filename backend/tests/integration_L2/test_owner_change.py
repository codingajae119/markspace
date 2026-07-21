"""admin 소유권 변경 스위트 — 새 owner 권한·owner 부재 복구·403·404 (Task 2.4 / Req 5.1~5.4).

`s01` 카탈로그 행 9(`POST /admin/workspaces/{id}/owner`)의 admin 소유권 변경(upsert-to-owner)
동작과 `s01` 권한 resolver(`require_ws_role(OWNER)`)의 **결합**을 mock 없이 e2e 로 관찰하는
외부 관찰자 스위트다. 부팅된 실 앱(`app.main.create_app`, s05 라우터 조립)의 실 라우트를 실제
서명 쿠키 세션으로 태운다.

관찰 대상:
- **소유권 변경 게이트** = `POST /admin/workspaces/{id}/owner` → `require_admin`(admin 전용).
- **owner 게이트** = `PATCH /workspaces/{id}` → `require_ws_role(OWNER)`(새 owner 권한 확인용).

소유권 변경 계약(upsert-to-owner): 대상이 기존 멤버면 role 을 owner 로 승격하고, 비멤버면
owner 로 신규 등록한다. 기존 owner 는 유지된다(복수 owner 허용).

단언 그룹:
- **새 owner 권한 반영(5.1)**: 변경 전 editor 는 owner 게이트에서 403 → admin 이 editor 를
  새 owner 로 지정 → editor 자신의 세션이 owner 게이트 200. 변경이 실제로 권한을 부여했음을
  before/after 대조로 증명한다.
- **단독 owner 보호 + co-owner 승격(하드 불변식, 5.2)**: admin 조차 단독 owner 를 제거할 수 없다
  (409). admin 이 소유권 변경으로 다른 사용자를 co-owner 로 승격하면(upsert-to-owner) 새 owner 가
  권한을 획득하고, 이제 owner 가 둘이 되어 원래 owner 를 제거해도 워크스페이스에 owner 가 남는다.
  워크스페이스가 항상 최소 1명의 owner 를 유지함을 관찰한다.
- **비-admin 거부(5.3)**: 워크스페이스 owner 조차 소유권 변경 게이트에서 403(게이트는 owner
  게이트가 아니라 `require_admin`). 비멤버 비-admin 도 403.
- **not_found(5.4)**: 미존재 워크스페이스·미존재 대상 사용자 모두 404.

각 테스트는 함수 스코프 `ws_scenario` 로 독립 워크스페이스를 받으므로 테스트 간 상태 간섭이 없다.
"""

from tests.integration_L2 import helpers


# --- 새 owner 권한 반영 (Req 5.1) ---------------------------------------------------


def test_owner_change_grants_owner_permission(ws_scenario):
    """새 owner 권한 반영: 변경 전 editor 403 → 소유권 변경 → editor 세션이 owner 게이트 200.

    변경 이전 editor 는 owner 요구 게이트(`PATCH /workspaces/{id}`)에서 403 으로 거부됨을 먼저
    단언해, 이후의 200 이 소유권 변경 덕분임을 증명한다. admin 이 editor 를 새 owner 로 지정
    (upsert: 기존 editor 멤버의 role 을 owner 로 승격)한 뒤 editor **자신의** 세션이 같은
    owner 게이트를 200 으로 통과함을 관찰한다(5.1).
    """
    ws_id = ws_scenario.workspace_id

    # 변경 전 대조: editor 는 owner 게이트에서 403(아직 editor role).
    before = helpers.attempt_update_settings(
        ws_scenario.editor_client, ws_id, is_shareable=True
    )
    assert before.status_code == 403, (
        f"변경 전 editor 는 owner 게이트에서 403 이어야 한다(권한 부여 대조 기준): "
        f"{before.status_code} {before.text}"
    )
    assert before.json().get("code") == "forbidden", (
        f"403 응답의 code 는 'forbidden' 이어야 한다(s01 에러 모델): {before.text}"
    )

    # admin 이 editor 를 새 owner 로 지정(upsert-to-owner) → 200.
    result = helpers.change_owner(
        ws_scenario.admin_client, ws_id, ws_scenario.editor_user_id
    )
    assert result["id"] == ws_id, (
        f"소유권 변경 응답은 대상 워크스페이스의 WorkspaceRead 여야 한다: {result}"
    )

    # 변경 후: editor 자신의 세션이 owner 게이트를 200 으로 통과(권한 획득).
    after = helpers.attempt_update_settings(
        ws_scenario.editor_client, ws_id, is_shareable=True
    )
    assert after.status_code == 200, (
        f"소유권 변경 후 새 owner(editor) 는 자신의 세션으로 owner 게이트를 200 으로 통과해야 "
        f"한다(5.1): {after.status_code} {after.text}"
    )


# --- 단독 owner 보호 + co-owner 승격 (하드 불변식, Req 5.2) --------------------------


def test_sole_owner_protected_until_coowner_promoted(ws_scenario):
    """단독 owner 보호: admin 조차 단독 owner 제거 불가(409) → co-owner 승격 후 원래 owner 제거 가능.

    워크스페이스가 항상 최소 1명의 owner 를 유지하는 하드 불변식을 관찰한다. admin 은 owner 게이트를
    bypass 하지만 서비스 계층의 단독 owner 가드가 owner/admin 구분 없이 적용되므로, 단독 owner
    제거는 409 로 거부된다. admin 이 소유권 변경(upsert-to-owner)으로 viewer 를 co-owner 로 승격하면
    권한을 획득하고, 이제 owner 가 둘이 되어 원래 owner 를 제거해도 viewer 가 owner 로 남는다.
    """
    ws_id = ws_scenario.workspace_id

    # 단독 owner 제거 시도 → admin 이어도 409(하드 불변식, 서비스 계층 가드).
    blocked = helpers.attempt_remove_member(
        ws_scenario.admin_client, ws_id, ws_scenario.owner_user_id
    )
    assert blocked.status_code == 409, (
        f"단독 owner 제거는 admin 이어도 409 로 거부되어야 한다(하드 불변식): "
        f"{blocked.status_code} {blocked.text}"
    )
    assert blocked.json().get("code") == "conflict", (
        f"409 응답의 code 는 'conflict' 여야 한다(s01 에러 모델): {blocked.text}"
    )

    # 대조: 아직 viewer 는 owner 게이트에서 403(co-owner 승격 전).
    before = helpers.attempt_update_settings(
        ws_scenario.viewer_client, ws_id, is_shareable=True
    )
    assert before.status_code == 403, (
        f"co-owner 승격 전 viewer 는 owner 게이트에서 403 이어야 한다(권한 부여 대조 기준): "
        f"{before.status_code} {before.text}"
    )

    # admin 이 viewer 를 co-owner 로 승격(upsert-to-owner) → 200. 이제 owner 가 둘.
    helpers.change_owner(ws_scenario.admin_client, ws_id, ws_scenario.viewer_user_id)

    # 새 owner(viewer) 자신의 세션이 owner 게이트를 200 으로 통과(권한 획득).
    after = helpers.attempt_update_settings(
        ws_scenario.viewer_client, ws_id, is_shareable=True
    )
    assert after.status_code == 200, (
        f"co-owner 로 승격된 viewer 는 owner 게이트를 200 으로 통과해야 한다(5.2): "
        f"{after.status_code} {after.text}"
    )

    # owner 가 둘이 된 지금은 원래 owner 를 제거할 수 있다(단독 owner 아님) → 204.
    now_removable = helpers.attempt_remove_member(
        ws_scenario.admin_client, ws_id, ws_scenario.owner_user_id
    )
    assert now_removable.status_code == 204, (
        f"co-owner 가 존재하면 원래 owner 제거는 허용되어야 한다(단독 owner 아님): "
        f"{now_removable.status_code} {now_removable.text}"
    )

    # 불변식 유지: 워크스페이스에는 여전히 viewer 가 owner 로 남아 있다.
    still_owner = helpers.attempt_update_settings(
        ws_scenario.viewer_client, ws_id, is_shareable=False
    )
    assert still_owner.status_code == 200, (
        f"원래 owner 제거 후에도 남은 owner(viewer) 는 owner 게이트를 통과해야 한다"
        f"(최소 1 owner 유지): {still_owner.status_code} {still_owner.text}"
    )


# --- 비-admin 거부 (Req 5.3) --------------------------------------------------------


def test_owner_change_forbidden_for_non_admin(ws_scenario):
    """비-admin 거부: 워크스페이스 owner·비멤버 비-admin 모두 소유권 변경 게이트에서 403(5.3).

    소유권 변경 게이트는 owner 게이트가 아니라 `require_admin`(시스템 admin 전용)이다. 따라서
    워크스페이스의 **owner** 조차 자신의 세션으로는 소유권을 바꿀 수 없다(403). 일반 비멤버
    비-admin(`nonmember_client`)도 동일하게 403 이다. 두 비-admin 호출 모두 차단됨을 관찰해
    게이트가 워크스페이스 role 이 아니라 시스템 admin 자격을 요구함을 증명한다.
    """
    ws_id = ws_scenario.workspace_id

    # 워크스페이스 owner 조차 소유권 변경은 admin 전용 게이트에서 403.
    owner_resp = helpers.attempt_change_owner(
        ws_scenario.owner_client, ws_id, ws_scenario.editor_user_id
    )
    assert owner_resp.status_code == 403, (
        f"워크스페이스 owner 라도 비-admin 이므로 소유권 변경 게이트에서 403 이어야 한다"
        f"(5.3, require_admin): {owner_resp.status_code} {owner_resp.text}"
    )
    assert owner_resp.json().get("code") == "forbidden", (
        f"403 응답의 code 는 'forbidden' 이어야 한다(s01 에러 모델): {owner_resp.text}"
    )

    # 일반 비멤버 비-admin 도 동일하게 403.
    nonmember_resp = helpers.attempt_change_owner(
        ws_scenario.nonmember_client, ws_id, ws_scenario.editor_user_id
    )
    assert nonmember_resp.status_code == 403, (
        f"비멤버 비-admin 도 소유권 변경 게이트에서 403 이어야 한다(5.3, require_admin): "
        f"{nonmember_resp.status_code} {nonmember_resp.text}"
    )


# --- not_found (Req 5.4) ------------------------------------------------------------


def test_owner_change_not_found_for_missing_workspace_or_user(ws_scenario):
    """not_found: 미존재 워크스페이스·미존재 대상 사용자 모두 404(5.4).

    admin 이 (1) 존재하지 않는 워크스페이스 id 로, (2) 존재하는 워크스페이스이나 존재하지 않는
    대상 사용자 id 로 소유권 변경을 시도하면 각각 404 not_found 로 거부됨을 관찰한다. admin
    게이트(`require_admin`)는 통과하되 서비스가 대상 리소스 부재를 404 로 판정함을 증명한다.
    """
    ws_id = ws_scenario.workspace_id
    missing_id = 999999999

    # (1) 미존재 워크스페이스.
    ws_resp = helpers.attempt_change_owner(
        ws_scenario.admin_client, missing_id, ws_scenario.editor_user_id
    )
    assert ws_resp.status_code == 404, (
        f"미존재 워크스페이스로 소유권 변경은 404 여야 한다(5.4): "
        f"{ws_resp.status_code} {ws_resp.text}"
    )
    assert ws_resp.json().get("code") == "not_found", (
        f"404 응답의 code 는 'not_found' 여야 한다(s01 에러 모델): {ws_resp.text}"
    )

    # (2) 존재하는 워크스페이스, 미존재 대상 사용자.
    user_resp = helpers.attempt_change_owner(
        ws_scenario.admin_client, ws_id, missing_id
    )
    assert user_resp.status_code == 404, (
        f"미존재 대상 사용자로 소유권 변경은 404 여야 한다(5.4): "
        f"{user_resp.status_code} {user_resp.text}"
    )
    assert user_resp.json().get("code") == "not_found", (
        f"404 응답의 code 는 'not_found' 여야 한다(s01 에러 모델): {user_resp.text}"
    )
