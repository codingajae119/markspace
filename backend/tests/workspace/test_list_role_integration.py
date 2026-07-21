"""GET /workspaces 목록 응답의 호출자 role 조달 통합 테스트 (s24 Task 4.1).

마이그레이션된 DB + 부팅 앱(:func:`ws_harness`, conftest 정의)에서 `GET /workspaces` 가
호출자 관점의 멤버십 role 을 단일 목록 응답으로 실어 보내는 실동작을 진짜 ASGI 요청·세션
쿠키 인증으로 검증한다(mock 없음). design.md §Testing Strategy → Integration Tests
("GET /workspaces 비-admin: role 존재 + 기존 필드 무변경 superset, 단일 응답 / admin: 멤버
WS role + 비멤버 WS role null") + §System Flows "목록 role 조달 (Backend)" 를 커버한다.

두 개의 검증 축:

1. **비-admin(Req 1.1·1.4·1.5)**: 사용자가 owner 인 WS 와 editor/viewer 로 초대된 WS 를
   가진 상태에서 단일 `GET /workspaces` 응답의 각 item 이 (a) 호출자의 실제 멤버십 role 을
   담은 `role` 키를 갖고, (b) 기존 WorkspaceRead 필드(id·created_at·updated_at·name·
   is_shareable·trash_retention_days)를 타입까지 그대로 유지하며(superset), (c) 워크스페이스별
   추가 조회 없이 하나의 응답으로 제공됨을 관찰한다.
2. **admin(Req 1.2·1.3)**: admin 이 **viewer 로만** 소속된 WS 는 role 이 "viewer" 로 조달되어
   admin 상승이 없음(Req 1.2, INV-3), admin 이 비멤버인 WS 는 role 이 null 임(Req 1.3)을
   admin 전체 조회(`list_all`) 경로에서 관찰한다.

RED 의미(1.1 이전 대비): pre-1.1 `WorkspaceRead` 는 `role` 키가 아예 없었으므로
``item["role"]`` 접근이 KeyError 로 실패하고, `role` 을 admin 여부로 상승시키면 admin-viewer
단언(role == "viewer")이 "owner"/상승값으로 깨진다 — 각 단언은 role 부재·오값·상승에
민감하다(무의미한 통과 아님).

DB 미가용 시 하네스가 그대로 실패한다(``pytest.skip`` 을 쓰지 않는다 — 미검증을 통과로
오인 방지).
"""

from app.models import User

# WorkspaceRead 가 목록 item 에서 노출해야 하는 정확한 키 집합(가산 role 포함).
# 기존 필드 무변경(superset) + role 가산을 exact-set 으로 강제한다.
WORKSPACE_READ_KEYS = {
    "id",
    "created_at",
    "updated_at",
    "name",
    "is_shareable",
    "trash_retention_days",
    "role",
}

_DEFAULT_PW = "ws-member-pass-123"


def _create_workspace(client, name: str) -> int:
    """인증 클라이언트로 ``POST /workspaces`` 를 태워 201 을 단언하고 생성된 id 를 반환한다."""
    resp = client.post("/workspaces", json={"name": name})
    assert resp.status_code == 201, f"생성 201 이어야 한다: {resp.status_code} {resp.text}"
    return resp.json()["id"]


def _add_member(owner_client, ws_id: int, user_id: int, role: str) -> None:
    """owner 인증 클라이언트로 대상 사용자를 지정 role 멤버로 등록한다(201 내부 단언)."""
    resp = owner_client.post(
        f"/workspaces/{ws_id}/members", json={"user_id": user_id, "role": role}
    )
    assert resp.status_code == 201, (
        f"멤버 추가 201 이어야 한다: {resp.status_code} {resp.text}"
    )


def _items_by_id(page: dict) -> dict[int, dict]:
    """Page 응답의 items 를 id→item 매핑으로 인덱싱한다(순서 비의존 조회용)."""
    return {item["id"]: item for item in page["items"]}


def _admin_user_id(ws_harness) -> int:
    """시드된 admin 사용자의 id 를 신규 세션으로 조회한다(SETUP — admin 을 멤버로 초대하기 위함)."""
    session = ws_harness.session_local()
    try:
        admin = (
            session.query(User)
            .filter_by(login_id=ws_harness.admin_login_id)
            .one()
        )
        return admin.id
    finally:
        session.close()


# --- 1. 비-admin: 각 item 에 실제 role + 기존 필드 무변경 superset + 단일 응답 (Req 1.1·1.4·1.5) ---


def test_non_admin_list_carries_caller_role_per_workspace(ws_harness):
    """비-admin 목록: owner WS 는 role=owner, 초대된 WS 는 초대 role 을 단일 응답에 담는다.

    (a) 사용자 U 가 WS_own 을 생성 → owner 로 등록됨. (b) 별도 owner O 가 WS_editor·WS_viewer
    를 만들어 U 를 각각 editor·viewer 로 초대. (c) U 로 로그인해 단 한 번의 `GET /workspaces`
    → 세 WS 항목이 모두 반환되고 각 item 의 `role` 이 U 의 실제 멤버십 role 과 일치함을
    관찰한다(owner/editor/viewer). role 은 호출자 관점이므로 owner O 가 만든 WS 라도 U 에겐
    editor/viewer 로 보인다(Req 1.1).
    """
    admin = ws_harness.login_admin()
    u_id = ws_harness.create_user(admin, "lr-user-1", name="목록사용자")
    ws_harness.create_user(admin, "lr-owner-1", name="초대오너")

    # U 가 자기 WS 를 생성 → owner.
    user = ws_harness.login("lr-user-1", _DEFAULT_PW)
    ws_own = _create_workspace(user, "내 소유 공간")

    # 별도 owner O 가 두 WS 를 만들어 U 를 editor·viewer 로 초대.
    owner = ws_harness.login("lr-owner-1", _DEFAULT_PW)
    ws_editor = _create_workspace(owner, "에디터 초대 공간")
    ws_viewer = _create_workspace(owner, "뷰어 초대 공간")
    _add_member(owner, ws_editor, u_id, "editor")
    _add_member(owner, ws_viewer, u_id, "viewer")

    # 단일 GET /workspaces 로 U 의 모든 WS 와 role 을 조달(추가 요청 없음, Req 1.4).
    resp = user.get("/workspaces")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    page = resp.json()
    items = _items_by_id(page)

    # U 는 정확히 세 WS 의 멤버(owner O 소유라도 U 가 비멤버인 WS 는 목록에 없음).
    assert set(items.keys()) == {ws_own, ws_editor, ws_viewer}, (
        f"비-admin 은 자신이 멤버인 WS 만 봐야 한다: 관측={sorted(items.keys())}"
    )

    # 각 item 의 role 이 U 의 실제 멤버십 role 과 일치(Req 1.1) — role 부재면 KeyError 로 실패.
    expected_role = {ws_own: "owner", ws_editor: "editor", ws_viewer: "viewer"}
    for ws_id, want in expected_role.items():
        assert items[ws_id]["role"] == want, (
            f"WS {ws_id} 의 role 은 호출자 멤버십 role({want})이어야 한다: "
            f"관측={items[ws_id].get('role')!r}"
        )

    # 기존 필드 무변경(superset) — 정확히 계약 키 집합 + 타입 계약(Req 1.5).
    for ws_id, item in items.items():
        assert set(item.keys()) == WORKSPACE_READ_KEYS, (
            f"목록 item 은 기존 WorkspaceRead 필드 + role 만 가져야 한다(superset·초과 금지): "
            f"관측={sorted(item.keys())} 기대={sorted(WORKSPACE_READ_KEYS)}"
        )
        assert isinstance(item["id"], int)
        assert isinstance(item["name"], str)
        assert isinstance(item["is_shareable"], bool)
        assert isinstance(item["trash_retention_days"], int)
        assert isinstance(item["created_at"], str), (
            "created_at 은 직렬화된 타임스탬프여야 한다"
        )
        # updated_at 은 nullable(생성 직후 None)이지만 키 자체는 항상 존재해야 한다.
        assert "updated_at" in item


def test_non_admin_role_delivered_in_single_response(ws_harness):
    """단일 `GET /workspaces` 응답만으로 role 이 조달됨(워크스페이스별 후속 조회 불요, Req 1.4).

    owner 인 사용자가 두 WS 를 만든 뒤 한 번의 목록 호출로 모든 item 이 role 을 담아 오는지
    확인한다. role 이 개별 상세(`GET /workspaces/{id}`) 없이 목록 payload 안에서 제공됨을
    관찰하는 것이 요지다(별도 라운드트립 없음).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "lr-single-1", name="단일응답사용자")
    user = ws_harness.login("lr-single-1", _DEFAULT_PW)
    ws_a = _create_workspace(user, "단일 A")
    ws_b = _create_workspace(user, "단일 B")

    resp = user.get("/workspaces")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    items = _items_by_id(resp.json())

    # 두 WS 모두 하나의 응답 안에서 role 을 담고 있어야 한다(추가 GET 불요).
    for ws_id in (ws_a, ws_b):
        assert items[ws_id]["role"] == "owner", (
            f"owner 가 만든 WS 는 목록 응답에서 role=owner 여야 한다: "
            f"관측={items[ws_id].get('role')!r}"
        )


# --- 2. admin: 멤버 WS role + 비멤버 WS role null + admin 상승 없음 (Req 1.2·1.3) ------


def test_admin_list_reflects_membership_role_without_elevation(ws_harness):
    """admin 전체 조회: viewer 로 소속된 WS 는 role=viewer(상승 없음), 비멤버 WS 는 role=null.

    (a) 비-admin owner O 가 WS_member·WS_nonmember 를 생성. (b) O 가 admin 을 WS_member 의
    **viewer** 로 초대(관리자를 낮은 role 로 소속시킴). (c) admin 으로 로그인 → `GET /workspaces`
    는 admin 전체 스캔(`list_all`)으로 두 WS 를 모두 반환. (d) WS_member 의 role 이 "owner"
    로 상승되지 않고 admin 의 실제 멤버십 role 인 "viewer" 임(Req 1.2, INV-3), WS_nonmember 의
    role 이 null 임(Req 1.3)을 관찰한다.

    핵심(무의미 통과 방지): admin 은 is_admin=True 이지만 role 필드는 멤버십에서만 산출되므로
    WS_member 는 viewer, WS_nonmember 는 null 이어야 한다. role 을 admin 으로 상승시키는 회귀는
    이 단언(viewer/null)을 깨뜨린다.
    """
    admin = ws_harness.login_admin()
    admin_id = _admin_user_id(ws_harness)
    ws_harness.create_user(admin, "lr-owner-adm", name="관리자초대오너")

    # 비-admin owner O 가 두 WS 를 생성(O 가 owner).
    owner = ws_harness.login("lr-owner-adm", _DEFAULT_PW)
    ws_member = _create_workspace(owner, "관리자-viewer 소속 공간")
    ws_nonmember = _create_workspace(owner, "관리자 비소속 공간")

    # O 가 admin 을 WS_member 의 viewer 로 초대(낮은 role 소속 — 상승 없음 단언의 전제).
    _add_member(owner, ws_member, admin_id, "viewer")

    # admin 으로 로그인 → 전체 스캔이라 두 WS 모두 목록에 존재.
    resp = admin.get("/workspaces")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    items = _items_by_id(resp.json())
    assert ws_member in items, "admin 전체 조회는 소속 WS 를 포함해야 한다"
    assert ws_nonmember in items, "admin 전체 조회는 비소속 WS 도 포함해야 한다(list_all)"

    # 소속 WS: admin 의 실제 role(viewer)로 조달 — admin 상승 없음(Req 1.2, INV-3).
    assert items[ws_member]["role"] == "viewer", (
        f"admin 이 viewer 로 소속된 WS 는 role=viewer 여야 한다(owner 로 상승 금지): "
        f"관측={items[ws_member].get('role')!r}"
    )

    # 비소속 WS: role null(멤버십 없음, Req 1.3).
    assert items[ws_nonmember]["role"] is None, (
        f"admin 이 비멤버인 WS 는 role=null 이어야 한다(멤버십 없음): "
        f"관측={items[ws_nonmember].get('role')!r}"
    )

    # 비소속 WS 라도 role 키 자체는 존재해야 한다(가산 optional, 키 항상 직렬화).
    assert "role" in items[ws_nonmember], (
        "비멤버 WS 도 role 키는 존재하고 값만 null 이어야 한다(exact-set 계약)"
    )
    # 두 item 모두 exact-set 계약 유지.
    for ws_id in (ws_member, ws_nonmember):
        assert set(items[ws_id].keys()) == WORKSPACE_READ_KEYS, (
            f"admin 목록 item 도 WorkspaceRead 계약을 따라야 한다: "
            f"관측={sorted(items[ws_id].keys())}"
        )
