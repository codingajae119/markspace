"""L2 워크스페이스 시나리오 헬퍼 — 실제 라우트 호출의 얇은 래퍼 (Task 1.2 / Req 1.4, 3.1).

후속 스위트(권한 경계 2.2 · admin override 2.3 · 소유권 변경 2.4 · 계정상태↔멤버십 2.5 ·
설정 2.6)가 워크스페이스 생성→멤버 구성→role 전이→소유권 변경→설정 변경 같은 cross-spec
시나리오를 간결하게 표현하도록, s05 워크스페이스 + s03 admin override 의 **실제** 엔드포인트를
호출하는 얇은 래퍼를 모은다. mock 이 아니라 부팅된 앱(`app.main.create_app`, s05 라우터 조립)
의 실 라우트를 태운다.

## 설계 규칙 (음성 경로 가능성 보존 — L1 helpers.py 관용 반영)
- **attempt 계열** (:func:`attempt_create_workspace`·:func:`attempt_add_member`·
  :func:`attempt_change_role`·:func:`attempt_remove_member`·:func:`attempt_change_owner`·
  :func:`attempt_update_settings`·:func:`attempt_get_workspace`): 후속 스위트가 같은 래퍼로
  성공(2xx)과 실패(403/404/409/422)를 **둘 다** 단언해야 하므로 **응답 객체를 그대로 반환하고
  상태를 내부에서 단언하지 않는다**. 각 스위트가 원시 URL 을 중복하지 않고 role별로 통과·거부·
  admin bypass 를 관찰한다.
- **setup 계열** (:func:`create_workspace`·:func:`add_member`·:func:`change_role`·
  :func:`remove_member`·:func:`change_owner`·:func:`update_settings`): 시나리오 준비상 항상
  성공하는 단계이므로 성공 상태를 내부에서 단언하고 유용한 값(생성 id, 파싱된 MemberRead/
  WorkspaceRead dict)을 돌려주어 시나리오 코드를 읽기 쉽게 한다. 내부적으로 대응하는 attempt
  래퍼를 재사용한다(URL·바디 단일 정의).

## L1 계정 헬퍼 재사용 (중복 정의 금지)
계정 생성·로그인·상태 전이(비활동/삭제) 헬퍼는 **정의하지 않고** s04 L1 에서 그대로 쓴다.
스위트는 ``from tests.integration_L1 import helpers as l1_helpers`` 로 ``create_user``·
``unique_login_id``·``set_active``·``set_deleted``·``DEFAULT_PASSWORD`` 등을 얻고, 로그인은
``harness.login``/``harness.login_admin`` 을 쓴다. 편의를 위해 이 모듈도 L1 계정 헬퍼를
:data:`l1_helpers` 로 재-export 한다(중복 **정의**가 아닌 참조).

엔드포인트 계약 (s01 단일 소스):
- ``POST /workspaces`` body ``{"name"}`` (VIEWER+ 인증) → 201 ``WorkspaceRead`` (요청자 owner 자동 등록)
- ``GET /workspaces/{id}`` (VIEWER+) → 200 ``WorkspaceRead``
- ``PATCH /workspaces/{id}`` body ``{name?, is_shareable?, trash_retention_days?}`` (OWNER)
  → 200 ``WorkspaceRead`` / retention ≤ 0 → 422
- ``POST /workspaces/{id}/members`` body ``{"user_id", "role"}`` (OWNER) → 201 ``MemberRead``
  / 미존재 사용자 404 / 이미 멤버 409
- ``PATCH /workspaces/{id}/members/{uid}`` body ``{"role"}`` (OWNER) → 200 ``MemberRead``
  / 멤버십 없음 404
- ``DELETE /workspaces/{id}/members/{uid}`` (OWNER) → 204
- ``POST /admin/workspaces/{id}/owner`` body ``{"new_owner_user_id"}`` (admin) → 200
  ``WorkspaceRead`` (upsert-to-owner) / 미존재 ws·user 404 / 비-admin 403
"""

from fastapi.testclient import TestClient
from httpx import Response

# L1 계정 헬퍼 재-export (중복 정의가 아니라 참조 — create_user/login/상태 전이 재사용).
from tests.integration_L1 import helpers as l1_helpers

__all__ = [
    "l1_helpers",
    "attempt_create_workspace",
    "create_workspace",
    "attempt_get_workspace",
    "attempt_update_settings",
    "update_settings",
    "attempt_add_member",
    "add_member",
    "attempt_change_role",
    "change_role",
    "attempt_remove_member",
    "remove_member",
    "attempt_change_owner",
    "change_owner",
]


# --- 워크스페이스 생성 / 조회 / 설정 -------------------------------------------------


def attempt_create_workspace(client: TestClient, name: str) -> Response:
    """``POST /workspaces`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — 스위트가 인증(201)·비인증(401) 등을 선택적으로 단언한다. ``client`` 는
    호출자의 role 세션(인증된 :class:`TestClient`).
    """
    return client.post("/workspaces", json={"name": name})


def create_workspace(client: TestClient, name: str) -> int:
    """owner 세션으로 워크스페이스를 만든다. SETUP — 201 을 단언하고 생성 id(int) 반환.

    요청자는 s05 계약상 owner 멤버로 자동 등록된다.
    """
    resp = attempt_create_workspace(client, name)
    assert resp.status_code == 201, (
        f"워크스페이스 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()["id"]


def attempt_get_workspace(client: TestClient, workspace_id: int) -> Response:
    """``GET /workspaces/{id}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — VIEWER+ 는 200, 비멤버는 거부됨을 스위트가 각각 단언한다.
    """
    return client.get(f"/workspaces/{workspace_id}")


def attempt_update_settings(
    client: TestClient, workspace_id: int, **fields: object
) -> Response:
    """``PATCH /workspaces/{id}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — ``fields`` 는 ``name``/``is_shareable``/``trash_retention_days`` 의
    부분집합. OWNER 는 200, 비-owner 는 거부, retention ≤ 0 은 422 를 스위트가 단언한다.
    """
    return client.patch(f"/workspaces/{workspace_id}", json=fields)


def update_settings(
    client: TestClient, workspace_id: int, **fields: object
) -> dict:
    """owner 세션으로 설정을 갱신한다. SETUP — 200 을 단언하고 파싱된 WorkspaceRead 반환."""
    resp = attempt_update_settings(client, workspace_id, **fields)
    assert resp.status_code == 200, (
        f"워크스페이스 설정 갱신 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


# --- 멤버십 (추가 / role 변경 / 제거) ------------------------------------------------


def attempt_add_member(
    client: TestClient, workspace_id: int, user_id: int, role: str
) -> Response:
    """``POST /workspaces/{id}/members`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — OWNER 는 201, 미존재 사용자 404, 이미 멤버 409, 비-owner 거부를
    스위트가 각각 단언한다. ``role`` 은 ``"owner"``/``"editor"``/``"viewer"``.
    """
    return client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": user_id, "role": role},
    )


def add_member(
    client: TestClient, workspace_id: int, user_id: int, role: str
) -> dict:
    """owner 세션으로 멤버를 추가한다. SETUP — 201 을 단언하고 파싱된 MemberRead 반환."""
    resp = attempt_add_member(client, workspace_id, user_id, role)
    assert resp.status_code == 201, (
        f"멤버 추가 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_change_role(
    client: TestClient, workspace_id: int, user_id: int, role: str
) -> Response:
    """``PATCH /workspaces/{id}/members/{uid}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — OWNER 는 200, 멤버십 없음 404, 비-owner 거부를 스위트가 각각 단언한다.
    """
    return client.patch(
        f"/workspaces/{workspace_id}/members/{user_id}",
        json={"role": role},
    )


def change_role(
    client: TestClient, workspace_id: int, user_id: int, role: str
) -> dict:
    """owner 세션으로 멤버 role 을 변경한다. SETUP — 200 을 단언하고 파싱된 MemberRead 반환."""
    resp = attempt_change_role(client, workspace_id, user_id, role)
    assert resp.status_code == 200, (
        f"멤버 role 변경 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_remove_member(
    client: TestClient, workspace_id: int, user_id: int
) -> Response:
    """``DELETE /workspaces/{id}/members/{uid}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — OWNER 는 204, 비-owner 거부를 스위트가 각각 단언한다.
    """
    return client.delete(f"/workspaces/{workspace_id}/members/{user_id}")


def remove_member(client: TestClient, workspace_id: int, user_id: int) -> None:
    """owner 세션으로 멤버를 제거한다. SETUP — 204 를 단언한다(반환값 없음)."""
    resp = attempt_remove_member(client, workspace_id, user_id)
    assert resp.status_code == 204, (
        f"멤버 제거 204 이어야 한다: {resp.status_code} {resp.text}"
    )


# --- 소유권 변경 (admin override) ---------------------------------------------------


def attempt_change_owner(
    admin_client: TestClient, workspace_id: int, new_owner_user_id: int
) -> Response:
    """``POST /admin/workspaces/{id}/owner`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — admin 은 200(upsert-to-owner), 미존재 ws·user 404, 비-admin 403 을
    스위트가 각각 단언한다. ``admin_client`` 는 admin 세션 클라이언트.
    """
    return admin_client.post(
        f"/admin/workspaces/{workspace_id}/owner",
        json={"new_owner_user_id": new_owner_user_id},
    )


def change_owner(
    admin_client: TestClient, workspace_id: int, new_owner_user_id: int
) -> dict:
    """admin 세션으로 소유권을 변경한다. SETUP — 200 을 단언하고 파싱된 WorkspaceRead 반환.

    s05 계약상 새 owner 가 기존 멤버면 role 을 owner 로 승격, 비멤버면 owner 로 신규 등록한다
    (upsert-to-owner).
    """
    resp = attempt_change_owner(admin_client, workspace_id, new_owner_user_id)
    assert resp.status_code == 200, (
        f"소유권 변경 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()
