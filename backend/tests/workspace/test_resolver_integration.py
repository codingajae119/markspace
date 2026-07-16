"""권한 resolver 실동작 및 워크스페이스·멤버십 왕복 통합 테스트 (Task 4.1).

마이그레이션된 DB + 부팅 앱(:func:`ws_harness`)에서 s01 권한 resolver 가 s05 가 채운
``workspace_member`` 데이터를 실제 판정 근거로 삼는지를 진짜 ASGI 요청·세션 쿠키 인증으로
검증한다(design.md §Testing Strategy → Integration Tests, §System Flows). mock 없이
``POST /auth/login`` → ``POST /workspaces`` → ``POST .../members`` → ``PATCH/GET/DELETE``
전 결선을 하나의 앱 컨텍스트에서 흘린다.

핵심 성공 기준(요구): 멤버십 생성 **전**에는 admin 만, 생성 **후**에는 실제 role 로
게이팅됨 — 즉 resolver 가 admin-only 에서 실제-role 판정으로 전환됨을 관찰한다
(Req 4.2·4.3·4.4·4.5·4.6·4.7, INV-1·2·3). 아울러 생성 owner화(1.1)·viewer/editor 상세
읽기(1.5)·멤버 오류(3.2·3.3)·삭제 캐스케이드(2.5) 왕복을 함께 단언한다.

주의: 비어 있지 않은 워크스페이스 삭제→409(2.7)는 문서 도입(s07) 이후 s08(L3)에서
검증하므로 여기서 작성하지 않는다(task note).
"""

from datetime import datetime

from app.models import Workspace, WorkspaceMember

# resolver 실동작을 증명하는 OWNER 게이트 변경 라우트(PATCH /workspaces/{id}). owner·admin 만
# 통과하고 editor/viewer/비멤버는 403 이 되어야 한다.
_OWNER_MUTATION = {"name": "변경-시도"}


def _create_workspace(client, name: str = "내 워크스페이스") -> int:
    """인증 클라이언트로 ``POST /workspaces`` 를 태워 201 을 단언하고 생성된 id 를 반환한다."""
    resp = client.post("/workspaces", json={"name": name})
    assert resp.status_code == 201, f"생성 201 이어야 한다: {resp.status_code} {resp.text}"
    return resp.json()["id"]


def _add_member(owner_client, ws_id: int, user_id: int, role: str):
    """owner(또는 admin) 클라이언트로 멤버를 추가하고 응답을 그대로 반환(상태 미단언)."""
    return owner_client.post(
        f"/workspaces/{ws_id}/members", json={"user_id": user_id, "role": role}
    )


def _seed_bare_workspace(harness) -> int:
    """멤버가 하나도 없는 워크스페이스를 ORM 으로 직접 시드하고 그 id 를 반환한다.

    "휴면(dormant) → 실동작" 대비(scenario 6)를 위해, POST /workspaces 가 자동 등록하는
    owner 멤버조차 없는 완전한 빈 워크스페이스를 만든다(멤버십 데이터가 채워지기 전 상태).
    """
    session = harness.session_local()
    try:
        ws = Workspace(
            name="휴면-워크스페이스",
            is_shareable=False,
            trash_retention_days=30,
            created_at=datetime.utcnow(),
        )
        session.add(ws)
        session.commit()
        return ws.id
    finally:
        session.close()


def _member_row(harness, ws_id: int, user_id: int):
    """신규 세션으로 (ws_id, user_id) 멤버십 행을 조회한다(커밋된 실제 상태 관찰용)."""
    session = harness.session_local()
    try:
        return (
            session.query(WorkspaceMember)
            .filter_by(workspace_id=ws_id, user_id=user_id)
            .one_or_none()
        )
    finally:
        session.close()


# --- 1. 생성 owner화 (Req 1.1) -------------------------------------------------


def test_create_registers_requester_as_owner(ws_harness):
    """POST /workspaces → 201, 요청자가 owner role 멤버로 자동 등록된다 (Req 1.1)."""
    admin = ws_harness.login_admin()
    owner_id = ws_harness.create_user(admin, "owner-1", name="오너")
    owner = ws_harness.login("owner-1", "ws-member-pass-123")

    resp = owner.post("/workspaces", json={"name": "협업 공간"})
    assert resp.status_code == 201, f"{resp.status_code} {resp.text}"
    body = resp.json()
    assert body["name"] == "협업 공간"
    assert body["is_shareable"] is False  # 생성 기본값(Req 1.2 정합).
    ws_id = body["id"]

    # 신규 세션으로 커밋된 멤버십 행을 직접 관찰: owner role 로 등록되어 있어야 한다.
    row = _member_row(ws_harness, ws_id, owner_id)
    assert row is not None, "요청자 멤버십 행이 존재해야 한다"
    assert row.role == "owner", "요청자는 owner role 로 등록되어야 한다"


# --- 2. resolver 실동작 게이팅 (Req 4.2–4.7, INV-1·2·3) ------------------------


def test_owner_gate_lets_owner_and_admin_only(ws_harness):
    """OWNER 게이트: owner·admin 만 통과, editor/viewer/비멤버 403, 미인증 401 (INV-1·2·3)."""
    admin_client = ws_harness.login_admin()
    owner_id = ws_harness.create_user(admin_client, "owner-2", name="오너")
    editor_id = ws_harness.create_user(admin_client, "editor-2", name="에디터")
    viewer_id = ws_harness.create_user(admin_client, "viewer-2", name="뷰어")
    ws_harness.create_user(admin_client, "nonmember-2", name="비멤버")

    owner = ws_harness.login("owner-2", "ws-member-pass-123")
    editor = ws_harness.login("editor-2", "ws-member-pass-123")
    viewer = ws_harness.login("viewer-2", "ws-member-pass-123")
    nonmember = ws_harness.login("nonmember-2", "ws-member-pass-123")

    ws_id = _create_workspace(owner, "게이팅 공간")
    # owner 가 editor/viewer 를 실제 role 로 등록 → resolver 판정 근거가 채워진다.
    assert _add_member(owner, ws_id, editor_id, "editor").status_code == 201
    assert _add_member(owner, ws_id, viewer_id, "viewer").status_code == 201

    def patch(client):
        return client.patch(f"/workspaces/{ws_id}", json=_OWNER_MUTATION)

    # owner ≥ OWNER → 통과.
    assert patch(owner).status_code == 200
    # editor·viewer 는 OWNER 미달 → 403 (INV-1·2).
    r_editor = patch(editor)
    assert r_editor.status_code == 403, f"editor 는 403 이어야 한다: {r_editor.text}"
    assert r_editor.json()["code"] == "forbidden"
    r_viewer = patch(viewer)
    assert r_viewer.status_code == 403, f"viewer 는 403 이어야 한다: {r_viewer.text}"
    assert r_viewer.json()["code"] == "forbidden"
    # 비멤버(로그인했으나 멤버 아님) → 403 (Req 4.4).
    r_non = patch(nonmember)
    assert r_non.status_code == 403, f"비멤버는 403 이어야 한다: {r_non.text}"
    assert r_non.json()["code"] == "forbidden"
    # admin(비멤버) → bypass 통과 (INV-3, Req 4.5).
    assert patch(admin_client).status_code == 200
    # 미인증(로그인 없음) → 401 (Req 4.4 경계, get_current_user).
    anon = ws_harness.new_client()
    r_anon = anon.patch(f"/workspaces/{ws_id}", json=_OWNER_MUTATION)
    assert r_anon.status_code == 401, f"미인증은 401 이어야 한다: {r_anon.text}"
    assert r_anon.json()["code"] == "unauthenticated"

    # owner_id 는 생성 시 owner 로 등록되어 있어야 함(게이팅 근거 재확인).
    assert _member_row(ws_harness, ws_id, owner_id).role == "owner"


# --- 3. viewer/editor 상세 읽기 (Req 1.5) -------------------------------------


def test_viewer_and_editor_can_read_detail(ws_harness):
    """editor·viewer 세션은 VIEWER 게이트를 충족해 GET /workspaces/{id} → 200 (Req 1.5)."""
    admin = ws_harness.login_admin()
    editor_id = ws_harness.create_user(admin, "editor-3", name="에디터")
    viewer_id = ws_harness.create_user(admin, "viewer-3", name="뷰어")
    ws_harness.create_user(admin, "owner-3", name="오너")

    owner = ws_harness.login("owner-3", "ws-member-pass-123")
    editor = ws_harness.login("editor-3", "ws-member-pass-123")
    viewer = ws_harness.login("viewer-3", "ws-member-pass-123")

    ws_id = _create_workspace(owner, "상세 읽기 공간")
    assert _add_member(owner, ws_id, editor_id, "editor").status_code == 201
    assert _add_member(owner, ws_id, viewer_id, "viewer").status_code == 201

    # editor(≥ viewer) → 200.
    r_editor = editor.get(f"/workspaces/{ws_id}")
    assert r_editor.status_code == 200, f"editor 상세는 200: {r_editor.text}"
    assert r_editor.json()["id"] == ws_id
    # viewer(= viewer) → 200.
    r_viewer = viewer.get(f"/workspaces/{ws_id}")
    assert r_viewer.status_code == 200, f"viewer 상세는 200: {r_viewer.text}"
    assert r_viewer.json()["id"] == ws_id


# --- 4. 멤버 추가 오류 (Req 3.2, 3.3) -----------------------------------------


def test_member_add_conflict_and_not_found(ws_harness):
    """중복 멤버 추가→409(3.2), 미존재 사용자 추가→404(3.3)."""
    admin = ws_harness.login_admin()
    editor_id = ws_harness.create_user(admin, "editor-4", name="에디터")
    ws_harness.create_user(admin, "owner-4", name="오너")

    owner = ws_harness.login("owner-4", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "오류 공간")

    # 최초 추가는 성공.
    assert _add_member(owner, ws_id, editor_id, "editor").status_code == 201
    # 동일 사용자 재추가 → 409 conflict (Req 3.2).
    dup = _add_member(owner, ws_id, editor_id, "viewer")
    assert dup.status_code == 409, f"중복 멤버는 409: {dup.text}"
    assert dup.json()["code"] == "conflict"
    # 존재하지 않는 user_id → 404 not_found (Req 3.3).
    missing = _add_member(owner, ws_id, 9_999_999, "editor")
    assert missing.status_code == 404, f"미존재 사용자는 404: {missing.text}"
    assert missing.json()["code"] == "not_found"


# --- 5. 삭제 왕복 (Req 2.5) ---------------------------------------------------


def test_delete_removes_workspace_and_all_memberships(ws_harness):
    """owner DELETE → 204, 워크스페이스·멤버십 행 모두 제거된다 (Req 2.5)."""
    admin = ws_harness.login_admin()
    editor_id = ws_harness.create_user(admin, "editor-5", name="에디터")
    owner_id = ws_harness.create_user(admin, "owner-5", name="오너")

    owner = ws_harness.login("owner-5", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "삭제 공간")
    assert _add_member(owner, ws_id, editor_id, "editor").status_code == 201

    # 삭제 전: 워크스페이스·2개 멤버십(owner 자동 + editor)이 존재.
    assert _member_row(ws_harness, ws_id, owner_id) is not None
    assert _member_row(ws_harness, ws_id, editor_id) is not None

    resp = owner.delete(f"/workspaces/{ws_id}")
    assert resp.status_code == 204, f"삭제는 204: {resp.status_code} {resp.text}"

    # 신규 세션으로 캐스케이드 관찰: 워크스페이스 행과 모든 멤버십이 사라져야 한다.
    session = ws_harness.session_local()
    try:
        assert session.get(Workspace, ws_id) is None, "워크스페이스 행이 제거되어야 한다"
        remaining = (
            session.query(WorkspaceMember).filter_by(workspace_id=ws_id).count()
        )
        assert remaining == 0, "워크스페이스의 모든 멤버십이 제거되어야 한다"
    finally:
        session.close()


# --- 6. "휴면 → 실동작" 대비 (관찰 가능 완료 기준) -----------------------------


def test_resolver_switches_from_admin_only_to_real_role(ws_harness):
    """멤버십 생성 전에는 admin 만, 생성 후에는 실제 role 로 게이팅됨을 대비로 증명한다.

    핵심 성공 기준(Req 4.7·INV-3): resolver 가 admin-only(휴면)에서 실제-role 판정으로
    전환된다. 완전한 빈 워크스페이스에서 (a) 비멤버 non-admin 은 403·admin 은 통과 →
    (b) 그 사용자를 owner 로 추가 → (c) 같은 사용자가 이제 통과.
    """
    admin = ws_harness.login_admin()
    user_id = ws_harness.create_user(admin, "dormant-user", name="휴면대상")
    user = ws_harness.login("dormant-user", "ws-member-pass-123")

    ws_id = _seed_bare_workspace(ws_harness)  # 멤버 0개(휴면 상태).

    def patch(client):
        return client.patch(f"/workspaces/{ws_id}", json=_OWNER_MUTATION)

    # (a) 멤버십 생성 전: 비멤버 non-admin → 403, admin(bypass) → 200.
    before = patch(user)
    assert before.status_code == 403, f"휴면 상태 비멤버는 403: {before.text}"
    assert before.json()["code"] == "forbidden"
    assert patch(admin).status_code == 200, "휴면 상태에서도 admin 은 통과해야 한다(admin-only)"

    # (b) admin(비멤버, OWNER 게이트 bypass)이 대상 사용자를 owner 로 추가 → 멤버십 데이터 채움.
    added = _add_member(admin, ws_id, user_id, "owner")
    assert added.status_code == 201, f"멤버 추가 201: {added.text}"
    assert _member_row(ws_harness, ws_id, user_id).role == "owner"

    # (c) 멤버십 생성 후: 같은 사용자가 이제 실제 owner role 로 통과 → resolver 전환 증명.
    after = patch(user)
    assert after.status_code == 200, (
        f"멤버십 생성 후 실제 role 로 통과해야 한다(admin-only→real-role 전환): {after.text}"
    )
