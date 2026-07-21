"""권한 경계 스위트 — 2단계 role(owner/member)·읽기 전역 개방·관리 owner 전용
(Task 2.2 재편 / s26 Req 3.5·3.8·5.1·5.2·5.4·7.2).

`s01` `require_ws_role` resolver 가 `s05` 가 채운 **실제 workspace_member 데이터** 위에서 2단계
위계(owner > member)를 계약대로 판정하고, 읽기 경로(워크스페이스 상세)는 멤버십과 무관하게
전역 개방됨을 mock 없이 e2e 로 관찰하는 외부 관찰자 스위트다. 각 role 은 자신의 세션 쿠키를
유지하는 **독립 클라이언트**로 실제 라우트를 태우며(`ws_scenario` 픽스처), 상태 코드를 그대로
단언한다. 게이트가 오작동하면 단언을 약화시키지 않고 실제 회귀를 표면화한다.

관찰 대상 게이트(`app/workspace/router.py`):
- 읽기(전역 개방) = `GET /workspaces/{id}` → 활성 사용자면 멤버십과 무관하게 200(s26 Req 3.5·3.8·
  7.2). role 필드는 호출자 관점(비멤버면 null)으로 채워진다.
- owner 게이트 = `PATCH /workspaces/{id}` · `POST /workspaces/{id}/members` ·
  `DELETE /workspaces/{id}/members/{uid}` → `require_ws_role(OWNER)`.

단언 그룹:
- **읽기 전역 개방(3.5·3.8·7.2)**: owner/member/비멤버 활성 사용자 모두 `GET /workspaces/{id}`
  200(비멤버도 403 아님). owner/member 는 role 이 각각 "owner"/"member", 비멤버는 role=null.
- **owner 게이트 매트릭스(5.1·5.2·5.4)**: PATCH·멤버 추가·멤버 제거 각각에서 owner 는 통과,
  member·비멤버는 403(관리 owner 전용).
- **member 는 편집 가능·관리 불가(4.x·5.4)**: member 가 읽기는 200 이되 owner 게이트(관리)는
  403 으로 거부됨을 한 테스트에서 대조로 관찰(구 3단계 "중간 위계"의 2단계 재표현).

각 테스트는 함수 스코프 `ws_scenario` 로 **독립된** 워크스페이스를 받으므로 테스트 간 상태
간섭이 없다. 멤버 제거의 owner 성공 케이스는 다른 단언이 의존하는 멤버를 건드리지 않도록
일회용 사용자를 새로 추가한 뒤 제거하는 방식으로 관찰한다.
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


# --- 읽기 전역 개방 (s26 Req 3.5·3.8·7.2) -------------------------------------------


def test_workspace_detail_read_is_globally_open(ws_scenario):
    """읽기 전역 개방(`GET /workspaces/{id}`): owner/member/비멤버 활성 사용자 모두 200.

    s26 읽기 전역 개방(Req 3.8·7.2)으로 워크스페이스 상세 읽기는 멤버십과 무관하게 활성
    사용자면 200 이다(비멤버도 403 이 아니라 200). role 필드는 호출자 관점으로 채워진다(Req 3.5):
    owner→"owner"·member→"member"·비멤버→null.
    """
    ws_id = ws_scenario.workspace_id

    owner_resp = helpers.attempt_get_workspace(ws_scenario.owner_client, ws_id)
    assert owner_resp.status_code == 200, (
        f"owner 는 상세 읽기 200 이어야 한다(3.8): {owner_resp.status_code} {owner_resp.text}"
    )
    assert owner_resp.json().get("role") == "owner", (
        f"owner 호출자 관점 role 은 'owner' 여야 한다(3.5): {owner_resp.text}"
    )

    member_resp = helpers.attempt_get_workspace(ws_scenario.editor_client, ws_id)
    assert member_resp.status_code == 200, (
        f"member 는 상세 읽기 200 이어야 한다(3.8): "
        f"{member_resp.status_code} {member_resp.text}"
    )
    assert member_resp.json().get("role") == "member", (
        f"member 호출자 관점 role 은 'member' 여야 한다(3.5): {member_resp.text}"
    )

    # 비멤버 활성 사용자 2명(viewer·nonmember) 모두 200 이고 role=null(3.5·3.8) — 헤드라인 전환.
    for label, client in (
        ("viewer(비멤버)", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
    ):
        resp = helpers.attempt_get_workspace(client, ws_id)
        assert resp.status_code == 200, (
            f"{label} 활성 사용자는 상세 읽기 전역 개방으로 200 이어야 한다(403 아님, 3.8): "
            f"{resp.status_code} {resp.text}"
        )
        assert resp.json().get("role") is None, (
            f"{label} 호출자 관점 role 은 null 이어야 한다(3.5): {resp.text}"
        )


# --- owner 게이트 매트릭스 — PATCH 설정 (s26 Req 5.1·5.4) ----------------------------


def test_owner_gate_patch_settings_matrix(ws_scenario):
    """owner 게이트(`PATCH /workspaces/{id}`): owner 200, member·비멤버 403.

    유효한 본문(`is_shareable=True`)을 보내 owner SUCCESS 가 검증 422 가 아닌 실제 200 이
    되도록 한다(5.1). member 는 관리 owner 전용 게이트에서 403(5.4), 비멤버도 403.
    """
    ws_id = ws_scenario.workspace_id

    resp = helpers.attempt_update_settings(
        ws_scenario.owner_client, ws_id, is_shareable=True
    )
    assert resp.status_code == 200, (
        f"owner 는 PATCH owner 게이트를 통과해 200 이어야 한다(5.1): "
        f"{resp.status_code} {resp.text}"
    )

    for label, client in (
        ("member", ws_scenario.editor_client),
        ("viewer(비멤버)", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
    ):
        resp = helpers.attempt_update_settings(client, ws_id, is_shareable=True)
        assert resp.status_code == 403, (
            f"{label} 는 PATCH owner 게이트에서 403 으로 거부되어야 한다"
            f"(관리 owner 전용, 5.4): {resp.status_code} {resp.text}"
        )


# --- owner 게이트 매트릭스 — 멤버 추가 (s26 Req 5.2·5.4) -----------------------------


def test_owner_gate_member_add_matrix(ws_scenario):
    """owner 게이트(`POST /workspaces/{id}/members`): owner 201, member·비멤버 403.

    owner SUCCESS 가 실제 201 이 되도록 아직 멤버가 아닌 신규 사용자를 대상으로 추가한다(5.2).
    member·비멤버는 owner 게이트가 서비스 본문보다 먼저 판정되어 대상 존재 여부와 무관하게
    403 으로 거부된다(5.4) — 거부 케이스는 하나의 일회용 대상 id 를 공유해도 무방하다.
    """
    ws_id = ws_scenario.workspace_id

    # 거부 케이스용 일회용 대상(게이트가 서비스 이전에 판정하므로 대상 존재는 결과에 무관).
    denied_target_id = _fresh_target_user_id(ws_scenario)
    for label, client in (
        ("member", ws_scenario.editor_client),
        ("viewer(비멤버)", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
    ):
        resp = helpers.attempt_add_member(client, ws_id, denied_target_id, "member")
        assert resp.status_code == 403, (
            f"{label} 는 멤버 추가 owner 게이트에서 403 으로 거부되어야 한다"
            f"(관리 owner 전용, 5.4): {resp.status_code} {resp.text}"
        )

    # owner SUCCESS 는 아직 멤버가 아닌 별도 신규 사용자로 실제 201 을 관찰한다.
    success_target_id = _fresh_target_user_id(ws_scenario)
    resp = helpers.attempt_add_member(
        ws_scenario.owner_client, ws_id, success_target_id, "member"
    )
    assert resp.status_code == 201, (
        f"owner 는 멤버 추가 owner 게이트를 통과해 201 이어야 한다(5.2): "
        f"{resp.status_code} {resp.text}"
    )


# --- owner 게이트 매트릭스 — 멤버 제거 (s26 Req 5.2·5.4) -----------------------------


def test_owner_gate_member_remove_matrix(ws_scenario):
    """owner 게이트(`DELETE /workspaces/{id}/members/{uid}`): owner 204, member·비멤버 403.

    거부 케이스는 기존 member 멤버를 대상으로 member·비멤버가 제거를 시도해 403 을 관찰한다
    (게이트가 서비스보다 먼저 판정되므로 실제 제거는 일어나지 않는다, 5.4). owner SUCCESS 는
    다른 단언이 의존하는 멤버를 건드리지 않도록 일회용 사용자를 owner 가 새로 추가한 뒤
    제거해 실제 204 를 관찰한다(5.2).
    """
    ws_id = ws_scenario.workspace_id

    # 거부 케이스: 기존 member 멤버(editor) 제거 시도 → 게이트에서 403(실제 제거 미발생).
    for label, client in (
        ("member", ws_scenario.editor_client),
        ("viewer(비멤버)", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
    ):
        resp = helpers.attempt_remove_member(
            client, ws_id, ws_scenario.editor_user_id
        )
        assert resp.status_code == 403, (
            f"{label} 는 멤버 제거 owner 게이트에서 403 으로 거부되어야 한다"
            f"(관리 owner 전용, 5.4): {resp.status_code} {resp.text}"
        )

    # owner SUCCESS: 일회용 사용자를 추가한 뒤 owner 가 제거해 실제 204 를 관찰한다.
    throwaway_id = _fresh_target_user_id(ws_scenario)
    helpers.add_member(ws_scenario.owner_client, ws_id, throwaway_id, "member")
    resp = helpers.attempt_remove_member(ws_scenario.owner_client, ws_id, throwaway_id)
    assert resp.status_code == 204, (
        f"owner 는 멤버 제거 owner 게이트를 통과해 204 이어야 한다(5.2): "
        f"{resp.status_code} {resp.text}"
    )


# --- member 는 편집 가능·관리 불가 (s26 Req 4.x·5.4) --------------------------------


def test_member_can_read_but_not_manage(ws_scenario):
    """member 대조: 읽기(`GET`)는 200 이되 관리(`PATCH`, owner 게이트)는 403(4.x·5.4).

    구 3단계의 "editor 중간 위계"를 2단계로 재표현한다. member 는 `GET /workspaces/{id}`(읽기
    전역 개방)를 200 으로 통과하되 `PATCH /workspaces/{id}`(관리 owner 전용)는 403 으로 거부됨을
    함께 단언한다. 이로써 member 가 읽기·편집은 가능하나 관리(owner)는 불가함을 증명한다.
    """
    ws_id = ws_scenario.workspace_id
    member = ws_scenario.editor_client

    read_gate = helpers.attempt_get_workspace(member, ws_id)
    assert read_gate.status_code == 200, (
        f"member 는 읽기 전역 개방으로 200 이어야 한다(3.8): "
        f"{read_gate.status_code} {read_gate.text}"
    )

    manage_gate = helpers.attempt_update_settings(member, ws_id, is_shareable=True)
    assert manage_gate.status_code == 403, (
        f"member 는 관리 owner 게이트에서 403 으로 거부되어야 한다(owner 미만, 5.4): "
        f"{manage_gate.status_code} {manage_gate.text}"
    )
