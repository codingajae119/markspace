"""워크스페이스 설정 스위트 — is_shareable·retention·기본값·admin bypass (Task 2.6 / Req 7.1~7.4).

owner·admin 이 워크스페이스 설정을 변경하면 s01 ⊕ s05 실 결합 상태에 반영되는지, 그리고
새로 생성된 워크스페이스의 기본값이 s01 `Settings` 계약과 일치하는지를 mock 없이 e2e 로
관찰하는 외부 관찰자 스위트다. 후속 계층(휴지통 s10·공유 s14)이 소비할 설정 계약이 이번
계층에서 성립함을 보장한다.

관찰 대상(s05 소유 동작, 기본 retention 은 s01 `Settings`):
- `PATCH /workspaces/{id}` 로 `is_shareable` 변경 → 이후 `GET /workspaces/{id}` 에 반영(7.1).
- `PATCH /workspaces/{id}` 로 `trash_retention_days` 양의 정수 변경 → 반영, 0 이하 → 422(7.2).
- admin 이 자신이 멤버가 아닌 워크스페이스의 설정을 변경 → 성공(7.3, INV-3).
- `POST /workspaces` 응답 기본값: `is_shareable=false`, `trash_retention_days`=s01 기본값(7.4).

각 테스트는 함수 스코프 `ws_scenario` 로 **독립된** 워크스페이스를 받으므로 테스트 간 상태
간섭이 없다. 기본값 기대치는 리터럴이 아니라 실행 중인 s01 `get_settings()` 에서 파생해,
같은 config.yml 로 부팅된 SUT 의 실제 기본값과 대조하는 참 계약 검증을 유지한다.
"""

from app.config import get_settings

from tests.integration_L2 import helpers


# --- is_shareable 반영 (Req 7.1) ---------------------------------------------------


def test_owner_toggle_is_shareable_round_trips(ws_scenario):
    """owner 가 `is_shareable` 를 변경하면 이후 GET 에 양방향으로 반영된다(7.1).

    owner 가 `PATCH /workspaces/{id}` 로 `is_shareable=True` 로 바꾸면 이후
    `GET /workspaces/{id}` 가 갱신된 값을 반환해야 한다. 다시 False 로 뒤집어 재조회해
    양방향 왕복(True→GET True, False→GET False)이 모두 실제 결합 상태에 반영됨을 관찰한다.
    """
    ws_id = ws_scenario.workspace_id

    # True 로 변경 → 응답 즉시 반영 + 별도 GET 재조회 반영.
    updated = helpers.update_settings(ws_scenario.owner_client, ws_id, is_shareable=True)
    assert updated["is_shareable"] is True, (
        f"PATCH 응답의 is_shareable 은 True 여야 한다(7.1): {updated}"
    )
    get_true = helpers.attempt_get_workspace(ws_scenario.owner_client, ws_id)
    assert get_true.status_code == 200, (
        f"설정 변경 후 GET 은 200 이어야 한다(7.1): "
        f"{get_true.status_code} {get_true.text}"
    )
    assert get_true.json()["is_shareable"] is True, (
        f"GET 재조회는 갱신된 is_shareable=True 를 반환해야 한다(7.1): {get_true.text}"
    )

    # 다시 False 로 뒤집어 반대 방향 왕복도 반영됨을 확인.
    helpers.update_settings(ws_scenario.owner_client, ws_id, is_shareable=False)
    get_false = helpers.attempt_get_workspace(ws_scenario.owner_client, ws_id)
    assert get_false.status_code == 200, (
        f"설정 재변경 후 GET 은 200 이어야 한다(7.1): "
        f"{get_false.status_code} {get_false.text}"
    )
    assert get_false.json()["is_shareable"] is False, (
        f"GET 재조회는 갱신된 is_shareable=False 를 반환해야 한다(7.1): {get_false.text}"
    )


# --- trash_retention_days 반영 + 경계 (Req 7.2) ------------------------------------


def test_owner_sets_positive_retention_is_reflected(ws_scenario):
    """owner 가 `trash_retention_days` 를 양의 정수로 변경하면 GET 에 반영된다(7.2).

    `PATCH /workspaces/{id}` 로 `trash_retention_days=7` 을 설정하면 응답과 이후
    `GET /workspaces/{id}` 재조회가 모두 7 을 반환해야 한다.
    """
    ws_id = ws_scenario.workspace_id

    updated = helpers.update_settings(
        ws_scenario.owner_client, ws_id, trash_retention_days=7
    )
    assert updated["trash_retention_days"] == 7, (
        f"PATCH 응답의 trash_retention_days 는 7 이어야 한다(7.2): {updated}"
    )
    read_back = helpers.attempt_get_workspace(ws_scenario.owner_client, ws_id)
    assert read_back.status_code == 200, (
        f"설정 변경 후 GET 은 200 이어야 한다(7.2): "
        f"{read_back.status_code} {read_back.text}"
    )
    assert read_back.json()["trash_retention_days"] == 7, (
        f"GET 재조회는 갱신된 trash_retention_days=7 을 반환해야 한다(7.2): "
        f"{read_back.text}"
    )


def test_owner_nonpositive_retention_is_rejected_422(ws_scenario):
    """owner 가 `trash_retention_days` 를 0 이하로 변경하면 422 로 거부되고 미영속(7.2).

    0 과 음수(-5)를 각각 시도해 모두 422 `validation_error` 이고 비어있지 않은
    `field_errors` 를 반환함을 단언한다. 거부된 뒤 GET 재조회가 값이 바뀌지 않았음을
    확인해(먼저 유효값 7 로 고정한 뒤 거부 시도) 실패 요청이 아무것도 영속하지 않음을 증명한다.
    """
    ws_id = ws_scenario.workspace_id

    # 먼저 유효한 값 7 로 고정해, 거부 이후 값이 그대로 7 임을 대조할 기준을 만든다.
    helpers.update_settings(ws_scenario.owner_client, ws_id, trash_retention_days=7)

    for bad_value in (0, -5):
        resp = helpers.attempt_update_settings(
            ws_scenario.owner_client, ws_id, trash_retention_days=bad_value
        )
        assert resp.status_code == 422, (
            f"trash_retention_days={bad_value} 는 422 로 거부되어야 한다(7.2): "
            f"{resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body["code"] == "validation_error", (
            f"422 응답의 code 는 validation_error 여야 한다(7.2): {resp.text}"
        )
        assert body.get("field_errors"), (
            f"422 응답은 비어있지 않은 field_errors 를 포함해야 한다(7.2): {resp.text}"
        )

    # 거부 이후에도 값은 앞서 고정한 7 그대로 — 실패 요청이 아무것도 영속하지 않았다.
    read_back = helpers.attempt_get_workspace(ws_scenario.owner_client, ws_id)
    assert read_back.status_code == 200, (
        f"거부 후 GET 은 200 이어야 한다(7.2): {read_back.status_code} {read_back.text}"
    )
    assert read_back.json()["trash_retention_days"] == 7, (
        f"거부된 요청은 값을 바꾸지 않아 trash_retention_days 는 7 그대로여야 한다(7.2): "
        f"{read_back.text}"
    )


# --- 설정 경로 admin bypass (Req 7.3, INV-3) ---------------------------------------


def test_admin_updates_settings_of_nonmember_workspace(ws_scenario):
    """비멤버 admin 이 워크스페이스 설정을 변경하면 성공한다(7.3, INV-3).

    admin 은 이 워크스페이스의 멤버가 아니지만(owner 가 생성) `PATCH /workspaces/{id}` 의
    owner 게이트를 admin bypass 로 통과해 200 이어야 한다. 대조로 비-admin 비멤버
    (`nonmember_client`)는 같은 PATCH 에서 403 으로 차단됨을 단언해, admin 의 200 이 열린
    접근이 아니라 오직 admin bypass 때문임을 증명한다(INV-1 비멤버 차단 vs INV-3 bypass).
    """
    ws_id = ws_scenario.workspace_id

    admin_updated = helpers.update_settings(
        ws_scenario.admin_client, ws_id, is_shareable=True
    )
    assert admin_updated["is_shareable"] is True, (
        f"비멤버 admin 의 설정 변경 응답은 is_shareable=True 여야 한다(7.3, INV-3): "
        f"{admin_updated}"
    )

    # 대조: 비-admin 비멤버는 같은 owner 게이트에서 403 → admin 200 은 bypass 임을 증명.
    nonmember_resp = helpers.attempt_update_settings(
        ws_scenario.nonmember_client, ws_id, is_shareable=True
    )
    assert nonmember_resp.status_code == 403, (
        f"비-admin 비멤버는 설정 변경 owner 게이트에서 403 으로 차단되어야 한다"
        f"(INV-1, admin 200 이 열린 접근이 아님을 증명): "
        f"{nonmember_resp.status_code} {nonmember_resp.text}"
    )


# --- 생성 기본값 = s01 Settings (Req 7.4) ------------------------------------------


def test_new_workspace_defaults_match_s01_settings(ws_scenario):
    """새 워크스페이스 기본값이 s01 `Settings` 계약과 일치한다(7.4).

    새 워크스페이스를 생성하면 `POST /workspaces` 응답 기본값이 `is_shareable=false` 이고
    `trash_retention_days` 가 s01 `Settings.default_trash_retention_days` 여야 한다. 기대
    기본값은 리터럴이 아니라 실행 중인 `get_settings()` 에서 파생해(SUT 와 동일 config.yml),
    실제 s01 기본값과 대조하는 참 계약 검증을 유지한다.
    """
    expected_default = get_settings().default_trash_retention_days

    resp = helpers.attempt_create_workspace(ws_scenario.owner_client, "기본값 검증")
    assert resp.status_code == 201, (
        f"워크스페이스 생성은 201 이어야 한다(7.4): {resp.status_code} {resp.text}"
    )
    body = resp.json()
    assert body["is_shareable"] is False, (
        f"새 워크스페이스 기본 is_shareable 은 False 여야 한다(7.4): {body}"
    )
    assert body["trash_retention_days"] == expected_default, (
        f"새 워크스페이스 기본 trash_retention_days 는 s01 Settings 기본값"
        f"({expected_default})과 일치해야 한다(7.4): {body}"
    )
