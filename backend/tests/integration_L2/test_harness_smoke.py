"""L2 하네스 스모크 테스트 (Task 1.1 관찰 가능한 완료 기준 / Req 1.1·1.2·1.3·1.4).

L2 하네스(``harness`` 재사용 + ``ws_scenario`` 신규)가 **s05 라우트가 조립된 실제 결합
런타임** 위에서 다음을 실제로 제공함을 end-to-end 로 증명한다:

1. admin 세션 클라이언트가 ``GET /workspaces`` 에서 200 을 받는다(s05 워크스페이스
   라우트가 부팅 앱에 노출됨 + admin 세션 유지 경로 증명).
2. ``ws_scenario`` 픽스처가 구성한 워크스페이스가 알려진 id 를 가지며, owner·editor·viewer
   세 role 클라이언트가 각자 세션으로 ``GET /workspaces/{id}`` 에 200 으로 접근 가능하다
   (editor·viewer 멤버가 지정 role 로 실제 구성되어 resolver 가 실제 멤버십 데이터로
   판정함을 증명).

이 스모크가 통과하면 후속 스위트(2.2~2.6)가 이 하네스 위에서 role별 실제 세션 e2e 를
구성할 수 있음이 보장된다.
"""


def test_admin_lists_workspaces(ws_scenario):
    """admin 세션 클라이언트가 GET /workspaces 200 (s05 라우트 노출 + admin 세션 증명)."""
    resp = ws_scenario.admin_client.get("/workspaces")

    assert resp.status_code == 200, (
        f"admin 세션으로 GET /workspaces 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    # s01 Page[T] 규약(items·total)을 따른다.
    assert "items" in body and "total" in body


def test_composed_workspace_reachable_by_each_role(ws_scenario):
    """구성된 워크스페이스가 알려진 id 를 가지며 owner·editor·viewer 가 각자 세션으로 200."""
    ws_id = ws_scenario.workspace_id
    assert isinstance(ws_id, int) and ws_id > 0

    for role, client in (
        ("owner", ws_scenario.owner_client),
        ("editor", ws_scenario.editor_client),
        ("viewer", ws_scenario.viewer_client),
    ):
        resp = client.get(f"/workspaces/{ws_id}")
        assert resp.status_code == 200, (
            f"{role} 세션으로 GET /workspaces/{ws_id} 200 이어야 한다: "
            f"{resp.status_code} {resp.text}"
        )
        assert resp.json()["id"] == ws_id
