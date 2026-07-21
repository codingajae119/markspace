"""L2 워크스페이스 헬퍼 스모크 테스트 (Task 1.2 관찰 가능한 완료 기준 / Req 1.4·3.1).

Task 1.2 가 추가하는 워크스페이스 시나리오 헬퍼(``tests/integration_L2/helpers.py``)가
**부팅된 s05 결합 런타임의 실제 라우트**를 태워 시나리오를 구성함을 end-to-end 로 증명한다.

증명 시나리오(모두 실제 세션·실제 라우트, mock 없음):

1. admin 이 owner/editor/viewer 사용자를 L1 계정 헬퍼로 생성하고 각자 세션으로 로그인한다
   (재사용: :mod:`tests.integration_L1.helpers` 의 ``create_user``·``harness.login``).
2. owner 가 :func:`~tests.integration_L2.helpers.create_workspace` 로 워크스페이스를 만든다.
3. owner 가 :func:`~tests.integration_L2.helpers.add_member` 로 editor·viewer 를 지정 role 로
   멤버 추가한다.
4. owner·editor·viewer 세 role 클라이언트가 각자 세션으로 ``GET /workspaces/{id}`` 200 을
   받는다(:func:`~tests.integration_L2.helpers.attempt_get_workspace`).

이 스모크가 통과하면 후속 스위트(2.2~2.6)가 이 헬퍼 위에서 role별 실제 세션 e2e 를 구성할
수 있음이 보장된다.
"""

from tests.integration_L1 import helpers as l1_helpers
from tests.integration_L2 import helpers as l2_helpers


def test_helpers_compose_workspace_reachable_by_each_role(harness):
    """헬퍼로 owner 가 WS 를 만들고 editor·viewer 를 추가하면 각 role 이 자기 세션으로 200."""
    admin_client = harness.login_admin()

    # 1. owner/editor/viewer 사용자 생성 + 로그인 — L1 계정 헬퍼 재사용(중복 정의 없음).
    owner_login = l1_helpers.unique_login_id("owner")
    l1_helpers.create_user(admin_client, owner_login, name="오너")
    owner_client = harness.login(owner_login, l1_helpers.DEFAULT_PASSWORD)

    editor_login = l1_helpers.unique_login_id("editor")
    editor_user_id = l1_helpers.create_user(admin_client, editor_login, name="에디터")
    editor_client = harness.login(editor_login, l1_helpers.DEFAULT_PASSWORD)

    viewer_login = l1_helpers.unique_login_id("viewer")
    viewer_user_id = l1_helpers.create_user(admin_client, viewer_login, name="뷰어")
    viewer_client = harness.login(viewer_login, l1_helpers.DEFAULT_PASSWORD)

    # 2. owner 가 L2 헬퍼로 워크스페이스 생성(201 내부 단언, id 반환).
    ws_id = l2_helpers.create_workspace(owner_client, "L2 헬퍼 스모크 워크스페이스")
    assert isinstance(ws_id, int) and ws_id > 0

    # 3. owner 가 L2 헬퍼로 두 사용자를 member 로 추가(201 내부 단언, MemberRead 반환).
    #    s26 2단계 모델: 비-owner 멤버 role 은 member 하나뿐(구 editor/viewer 통합).
    editor_member = l2_helpers.add_member(owner_client, ws_id, editor_user_id, "member")
    assert editor_member["role"] == "member"
    assert editor_member["workspace_id"] == ws_id
    assert editor_member["user_id"] == editor_user_id

    viewer_member = l2_helpers.add_member(owner_client, ws_id, viewer_user_id, "member")
    assert viewer_member["role"] == "member"

    # 4. 세 role 클라이언트가 각자 세션으로 GET /workspaces/{id} 200.
    for role, client in (
        ("owner", owner_client),
        ("editor", editor_client),
        ("viewer", viewer_client),
    ):
        resp = l2_helpers.attempt_get_workspace(client, ws_id)
        assert resp.status_code == 200, (
            f"{role} 세션으로 GET /workspaces/{ws_id} 200 이어야 한다: "
            f"{resp.status_code} {resp.text}"
        )
        assert resp.json()["id"] == ws_id
