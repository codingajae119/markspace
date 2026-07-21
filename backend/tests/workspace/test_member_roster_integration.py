"""멤버 로스터 조회 엔드포인트 게이팅·anti-enumeration 통합 테스트 (Task 3.1).

마이그레이션된 DB + 부팅 앱(:func:`ws_harness`)에서 owner-gated 조회 엔드포인트
``GET /workspaces/{id}/members`` 를 mock 없이 진짜 ASGI 요청·세션 쿠키 인증으로
검증한다(design.md §Testing Strategy → Integration Tests, §System Flows → 로스터 조회
게이팅, §Security Considerations).

이 엔드포인트는 task 2.2 에서 이미 커밋되어 통과하므로 본 파일은 **이미 배포된 동작을
검증하는 커버리지 task** 다(RED→GREEN 아님, assignable 통합 테스트와 동일 성격). 대신
게이팅이 trivially 통과가 아니라 실질 판정됨(예: editor·viewer 가 실제 role 로 등록되었음에도
진짜 403)을 HTTP 경계에서 단언한다. no-op 게이트라면 editor/viewer/비-멤버/미인증/미존재 WS
케이스가 모두 200 을 받아 이 파일의 단언들이 실패하므로 vacuous 통과가 아니다.

게이팅은 s23 assignable 과 **동일**하다(둘 다 ``require_ws_role(Role.OWNER)`` 부착):
owner→200, editor→403, viewer→403, 비-멤버→403, admin(비-owner)→200(INV-3 override, 요청자
owner 여부와 무관), 미인증(세션 없음·무효)→401, 미존재 WS→403(404 아님, anti-enumeration).

검증 대상(tasks.md 3.1 + design.md):
- 게이팅 매트릭스: owner→200, editor→403, viewer→403, 비-멤버→403, admin(비-owner)→200,
  미인증→401 (Req 2.1·2.2·2.3·2.5).
- 무효 세션 쿠키(변조)→401 (Req 2.1, 미인증 경계 세분).
- 존재하지 않는 워크스페이스→403(≠404, 존재 노출 안 함, anti-enumeration) (Req 2.4).

NOTE: 로스터 divergence(비활성·삭제·owner 포함)·narrow 봉투(4-필드)·pagination 케이스는
task 3.2 가 이 파일에 **추가**한다(본 task 3.1 은 게이팅 + anti-enumeration 만 소유한다).
"""


def _create_workspace(client, name: str = "로스터 공간") -> int:
    """인증 클라이언트로 ``POST /workspaces`` 를 태워 201 을 단언하고 생성된 id 를 반환한다.

    생성자는 s05 계약상 owner 멤버로 자동 등록된다(게이팅 매트릭스의 owner 근거).
    """
    resp = client.post("/workspaces", json={"name": name})
    assert resp.status_code == 201, f"생성 201 이어야 한다: {resp.status_code} {resp.text}"
    return resp.json()["id"]


def _add_member(owner_client, ws_id: int, user_id: int, role: str):
    """owner(또는 admin) 클라이언트로 멤버를 추가하고 응답을 그대로 반환한다."""
    return owner_client.post(
        f"/workspaces/{ws_id}/members", json={"user_id": user_id, "role": role}
    )


def _get_members(client, ws_id: int, *, limit=None, offset=None):
    """``GET /workspaces/{id}/members`` 를 (선택적 쿼리와 함께) 호출한다."""
    params = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return client.get(f"/workspaces/{ws_id}/members", params=params)


# --- 1. 게이팅 매트릭스 (Req 2.1·2.2·2.3·2.5) --------------------------------


def test_gating_matrix_owner_admin_pass_others_rejected(ws_harness):
    """owner·admin→200, editor·viewer·비멤버→403, 미인증→401 (Req 2.1·2.2·2.3·2.5).

    게이팅이 trivially 통과가 아니라 실질 판정임을 증명한다: editor·viewer 는 실제 role 로
    등록되었음에도 OWNER 미달로 진짜 403 을 받고, owner·admin(비-owner 멤버)만 200 을 받는다.
    admin override 는 요청자가 해당 WS 의 owner 인지와 무관하다(INV-3).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "mr-owner", name="오너")
    editor_id = ws_harness.create_user(admin, "mr-editor", name="에디터")
    viewer_id = ws_harness.create_user(admin, "mr-viewer", name="뷰어")
    ws_harness.create_user(admin, "mr-nonmember", name="비멤버")

    owner = ws_harness.login("mr-owner", "ws-member-pass-123")
    editor = ws_harness.login("mr-editor", "ws-member-pass-123")
    viewer = ws_harness.login("mr-viewer", "ws-member-pass-123")
    nonmember = ws_harness.login("mr-nonmember", "ws-member-pass-123")

    ws_id = _create_workspace(owner, "게이팅 공간")
    # editor·viewer 를 실제 role 로 등록 → 게이트가 실제 role 로 판정하게 만든다.
    assert _add_member(owner, ws_id, editor_id, "editor").status_code == 201
    assert _add_member(owner, ws_id, viewer_id, "viewer").status_code == 201

    # owner ≥ OWNER → 200 (Req 2.5 의 대비군: 정상 owner 는 통과).
    r_owner = _get_members(owner, ws_id)
    assert r_owner.status_code == 200, f"owner 는 200: {r_owner.text}"
    assert set(r_owner.json().keys()) == {"items", "total"}

    # editor·viewer 는 OWNER 미달 → 진짜 403 (trivial 통과 아님, Req 2.2).
    r_editor = _get_members(editor, ws_id)
    assert r_editor.status_code == 403, f"editor 는 403: {r_editor.text}"
    assert r_editor.json()["code"] == "forbidden"
    r_viewer = _get_members(viewer, ws_id)
    assert r_viewer.status_code == 403, f"viewer 는 403: {r_viewer.text}"
    assert r_viewer.json()["code"] == "forbidden"

    # 비멤버(로그인했으나 멤버 아님) → 403 (Req 2.3).
    r_non = _get_members(nonmember, ws_id)
    assert r_non.status_code == 403, f"비멤버는 403: {r_non.text}"
    assert r_non.json()["code"] == "forbidden"

    # admin(비-owner 멤버) → override 로 200 — 요청자 owner 여부와 무관 (Req 2.5, INV-3).
    r_admin = _get_members(admin, ws_id)
    assert r_admin.status_code == 200, f"admin override 는 200: {r_admin.text}"
    assert set(r_admin.json().keys()) == {"items", "total"}

    # 미인증(세션 없음) → 401 (Req 2.1).
    anon = ws_harness.new_client()
    r_anon = _get_members(anon, ws_id)
    assert r_anon.status_code == 401, f"미인증은 401: {r_anon.text}"
    assert r_anon.json()["code"] == "unauthenticated"


def test_invalid_session_cookie_returns_401(ws_harness):
    """무효 세션 쿠키(변조)로도 401 이다 (Req 2.1, 미인증 경계 세분)."""
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "mr-owner2", name="오너")
    owner = ws_harness.login("mr-owner2", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "무효세션 공간")

    bad = ws_harness.new_client()
    bad.cookies.set(ws_harness.session_cookie_name, "not-a-valid-session-token")
    r = _get_members(bad, ws_id)
    assert r.status_code == 401, f"무효 세션은 401: {r.status_code} {r.text}"
    assert r.json()["code"] == "unauthenticated"


# --- 2. 존재하지 않는 워크스페이스 → 403 (anti-enumeration, Req 2.4) ----------


def test_nonexistent_workspace_returns_403_not_404(ws_harness):
    """존재하지 않는 워크스페이스 조회는 403(비-멤버 게이트) — 404 로 존재 노출 안 함 (Req 2.4).

    로그인한 non-admin 사용자가 존재하지 않는 id 를 조회하면 게이트 단계에서 비-멤버 →
    403 이어야 한다. 404 였다면 워크스페이스 존재 여부가 열거 가능해진다(anti-enumeration 위반).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "mr-probe", name="탐침")
    prober = ws_harness.login("mr-probe", "ws-member-pass-123")

    missing_ws_id = 9_999_999
    r = _get_members(prober, missing_ws_id)
    assert r.status_code == 403, (
        f"존재하지 않는 워크스페이스는 403 이어야 한다(404 아님): {r.status_code} {r.text}"
    )
    assert r.json()["code"] == "forbidden"
    assert r.status_code != 404, "404 는 존재를 노출하므로 금지(anti-enumeration)"
