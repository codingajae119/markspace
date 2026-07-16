"""권한 경계 스위트 — role 위계·viewer 읽기전용·비멤버 차단 (Task 2.2 / Req 3.1~3.5).

`s01` `require_ws_role` resolver 가 `s05` 가 채운 **실제 workspace_member 데이터** 위에서
owner ≥ editor ≥ viewer 위계를 계약대로 판정하는지를 mock 없이 e2e 로 관찰하는 외부 관찰자
스위트다. 각 role 은 자신의 세션 쿠키를 유지하는 **독립 클라이언트**로 실제 라우트를 태우며
(`ws_scenario` 픽스처가 admin 경로로 사용자를 생성·로그인하고 owner 가 워크스페이스를
구성한 상태), 상태 코드를 그대로 단언한다. 게이트가 오작동하면 단언을 약화시키지 않고 실제
회귀를 표면화한다(체크포인트는 원인 spec s01/s05 의 수정을 유발할 뿐 우회하지 않는다).

관찰 대상 게이트(`app/workspace/router.py`):
- viewer 게이트 = `GET /workspaces/{id}` → `require_ws_role(VIEWER)`.
- owner 게이트 = `PATCH /workspaces/{id}` · `POST /workspaces/{id}/members` ·
  `DELETE /workspaces/{id}/members/{uid}` → `require_ws_role(OWNER)`.
resolver 는 비멤버에 대해 role 을 판정하지 못하므로(None) 403 으로 거부된다.

단언 그룹:
- **viewer 게이트 매트릭스(3.1·3.3)**: owner/editor/viewer 모두 200, 비멤버 403(INV-1).
- **owner 게이트 매트릭스(3.2·3.3·3.4)**: PATCH·멤버 추가·멤버 제거 각각에서 owner 는 통과,
  editor·viewer·비멤버는 403(INV-2 viewer 읽기 전용, 위계 owner ≥ editor).
- **editor 중간 위계(3.5)**: editor 가 viewer 게이트는 통과하되 owner 게이트는 거부됨을 한
  테스트에서 대조로 관찰(위계상 viewer 보다 높고 owner 보다 낮음).

각 테스트는 함수 스코프 `ws_scenario` 로 **독립된** 워크스페이스를 받으므로 테스트 간 상태
간섭이 없다. 멤버 제거의 owner 성공 케이스는 다른 단언이 의존하는 editor·viewer 를 건드리지
않도록 일회용 사용자를 새로 추가한 뒤 제거하는 방식으로 관찰한다.
"""

from tests.integration_L2 import helpers


def _fresh_target_user_id(ws_scenario) -> int:
    """이 워크스페이스의 비멤버인 신규 대상 사용자를 admin 경로로 생성해 id 를 반환한다.

    멤버 추가/제거 게이트를 관찰할 때 owner SUCCESS 케이스가 실제 201/204 가 되도록 아직
    멤버가 아닌 사용자 id 가 필요하다. L1 `create_user`(201 단언)·`unique_login_id`(공유 테스트
    DB 충돌 회피)를 재사용한다.
    """
    login_id = helpers.l1_helpers.unique_login_id("target")
    return helpers.l1_helpers.create_user(
        ws_scenario.admin_client, login_id, helpers.l1_helpers.DEFAULT_PASSWORD, name="대상"
    )


# --- viewer 게이트 매트릭스 (Req 3.1·3.3, INV-1) ------------------------------------


def test_viewer_gate_allows_all_members_and_blocks_nonmember(ws_scenario):
    """viewer 게이트(`GET /workspaces/{id}`): owner/editor/viewer 200, 비멤버 403.

    `require_ws_role(VIEWER)` 는 owner(3)·editor(2)·viewer(1) 모두 위계를 충족하므로 세 role
    의 독립 세션 모두 200 을 받아야 한다(3.1). 비멤버는 resolver 가 role 을 판정하지 못해
    403 으로 거부된다(3.3, INV-1 비멤버 접근 차단).
    """
    ws_id = ws_scenario.workspace_id

    for label, client in (
        ("owner", ws_scenario.owner_client),
        ("editor", ws_scenario.editor_client),
        ("viewer", ws_scenario.viewer_client),
    ):
        resp = helpers.attempt_get_workspace(client, ws_id)
        assert resp.status_code == 200, (
            f"{label} 는 viewer 게이트를 통과해 200 이어야 한다(3.1): "
            f"{resp.status_code} {resp.text}"
        )

    resp = helpers.attempt_get_workspace(ws_scenario.nonmember_client, ws_id)
    assert resp.status_code == 403, (
        f"비멤버는 viewer 게이트에서 403 으로 차단되어야 한다(3.3, INV-1): "
        f"{resp.status_code} {resp.text}"
    )


# --- owner 게이트 매트릭스 — PATCH 설정 (Req 3.2·3.3·3.4, INV-2) --------------------


def test_owner_gate_patch_settings_matrix(ws_scenario):
    """owner 게이트(`PATCH /workspaces/{id}`): owner 200, editor·viewer·비멤버 403.

    유효한 본문(`is_shareable=True`)을 보내 owner SUCCESS 가 검증 422 가 아닌 실제 200 이
    되도록 한다(3.4). editor·viewer 는 위계 미달로 403(3.2, INV-2 viewer 읽기 전용,
    owner ≥ editor), 비멤버는 role 미판정으로 403(3.3).
    """
    ws_id = ws_scenario.workspace_id

    resp = helpers.attempt_update_settings(
        ws_scenario.owner_client, ws_id, is_shareable=True
    )
    assert resp.status_code == 200, (
        f"owner 는 PATCH owner 게이트를 통과해 200 이어야 한다(3.4): "
        f"{resp.status_code} {resp.text}"
    )

    for label, client in (
        ("editor", ws_scenario.editor_client),
        ("viewer", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
    ):
        resp = helpers.attempt_update_settings(client, ws_id, is_shareable=True)
        assert resp.status_code == 403, (
            f"{label} 는 PATCH owner 게이트에서 403 으로 거부되어야 한다"
            f"(3.2/3.3, INV-2): {resp.status_code} {resp.text}"
        )


# --- owner 게이트 매트릭스 — 멤버 추가 (Req 3.2·3.3·3.4) ----------------------------


def test_owner_gate_member_add_matrix(ws_scenario):
    """owner 게이트(`POST /workspaces/{id}/members`): owner 201, editor·viewer·비멤버 403.

    owner SUCCESS 가 실제 201 이 되도록 아직 멤버가 아닌 신규 사용자를 대상으로 추가한다(3.4).
    editor·viewer·비멤버는 owner 게이트가 서비스 본문보다 먼저 판정되어 대상 존재 여부와
    무관하게 403 으로 거부된다(3.2/3.3) — 거부 케이스는 하나의 일회용 대상 id 를 공유해도
    무방하다.
    """
    ws_id = ws_scenario.workspace_id

    # 거부 케이스용 일회용 대상(게이트가 서비스 이전에 판정하므로 대상 존재는 결과에 무관).
    denied_target_id = _fresh_target_user_id(ws_scenario)
    for label, client in (
        ("editor", ws_scenario.editor_client),
        ("viewer", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
    ):
        resp = helpers.attempt_add_member(client, ws_id, denied_target_id, "viewer")
        assert resp.status_code == 403, (
            f"{label} 는 멤버 추가 owner 게이트에서 403 으로 거부되어야 한다"
            f"(3.2/3.3): {resp.status_code} {resp.text}"
        )

    # owner SUCCESS 는 아직 멤버가 아닌 별도 신규 사용자로 실제 201 을 관찰한다.
    success_target_id = _fresh_target_user_id(ws_scenario)
    resp = helpers.attempt_add_member(
        ws_scenario.owner_client, ws_id, success_target_id, "viewer"
    )
    assert resp.status_code == 201, (
        f"owner 는 멤버 추가 owner 게이트를 통과해 201 이어야 한다(3.4): "
        f"{resp.status_code} {resp.text}"
    )


# --- owner 게이트 매트릭스 — 멤버 제거 (Req 3.2·3.3·3.4) ----------------------------


def test_owner_gate_member_remove_matrix(ws_scenario):
    """owner 게이트(`DELETE /workspaces/{id}/members/{uid}`): owner 204, editor·viewer·비멤버 403.

    거부 케이스는 기존 viewer 멤버를 대상으로 editor·viewer·비멤버가 제거를 시도해 403 을
    관찰한다(게이트가 서비스보다 먼저 판정되므로 실제 제거는 일어나지 않는다, 3.2/3.3).
    owner SUCCESS 는 다른 단언이 의존하는 멤버를 건드리지 않도록 일회용 사용자를 owner 가
    새로 추가한 뒤 제거해 실제 204 를 관찰한다(3.4).
    """
    ws_id = ws_scenario.workspace_id

    # 거부 케이스: 기존 viewer 멤버 제거 시도 → 게이트에서 403(실제 제거 미발생).
    for label, client in (
        ("editor", ws_scenario.editor_client),
        ("viewer", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
    ):
        resp = helpers.attempt_remove_member(
            client, ws_id, ws_scenario.viewer_user_id
        )
        assert resp.status_code == 403, (
            f"{label} 는 멤버 제거 owner 게이트에서 403 으로 거부되어야 한다"
            f"(3.2/3.3): {resp.status_code} {resp.text}"
        )

    # owner SUCCESS: 일회용 사용자를 추가한 뒤 owner 가 제거해 실제 204 를 관찰한다.
    throwaway_id = _fresh_target_user_id(ws_scenario)
    helpers.add_member(ws_scenario.owner_client, ws_id, throwaway_id, "viewer")
    resp = helpers.attempt_remove_member(ws_scenario.owner_client, ws_id, throwaway_id)
    assert resp.status_code == 204, (
        f"owner 는 멤버 제거 owner 게이트를 통과해 204 이어야 한다(3.4): "
        f"{resp.status_code} {resp.text}"
    )


# --- editor 중간 위계 (Req 3.5) ----------------------------------------------------


def test_editor_is_middle_of_hierarchy(ws_scenario):
    """editor 중간 위계: viewer 게이트 통과 + owner 게이트 거부를 한 테스트에서 대조 관찰(3.5).

    editor 가 `GET /workspaces/{id}`(viewer 게이트)는 200 으로 통과하되
    `PATCH /workspaces/{id}`(owner 게이트)는 403 으로 거부됨을 함께 단언한다. 이로써 editor 가
    위계상 viewer 보다 높고(viewer 게이트 통과) owner 보다 낮은(owner 게이트 거부) 중간 등급
    으로 판정됨을 증명한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    viewer_gate = helpers.attempt_get_workspace(editor, ws_id)
    assert viewer_gate.status_code == 200, (
        f"editor 는 viewer 게이트를 통과해 200 이어야 한다(viewer 보다 높음, 3.5): "
        f"{viewer_gate.status_code} {viewer_gate.text}"
    )

    owner_gate = helpers.attempt_update_settings(editor, ws_id, is_shareable=True)
    assert owner_gate.status_code == 403, (
        f"editor 는 owner 게이트에서 403 으로 거부되어야 한다(owner 보다 낮음, 3.5): "
        f"{owner_gate.status_code} {owner_gate.text}"
    )
