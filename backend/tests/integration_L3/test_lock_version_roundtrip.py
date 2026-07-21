"""잠금→저장 왕복·권한 게이팅 통합 스위트 — s09 잠금/버전 e2e (Task 4.1 / s09 Req 1·2·3·4·5·7,
design §Testing Strategy → Integration Tests(잠금→저장 왕복 / 권한 게이팅 / 취소·강제해제 흐름)).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕**s09**) + **실제 세션 쿠키** 위에서 s09
잠금/버전 5개 라우트(카탈로그 행 24~28)를 mock 없이 관찰한다. 판정은 s05 가 채운 실제
`workspace_member` 데이터 위에서 s01 `require_ws_role` resolver 가 수행하고, `/documents/{id}/*`
는 s07 문서→WS 어댑터가 문서 id 로 workspace_id 를 추출해 위임한다. 게이트가 오작동하면 단언을
약화시키지 않고 실제 회귀(s09 서비스 / s01 resolver / s07 어댑터 / s05 멤버십 데이터)를 그대로
표면화한다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다.

`ws_scenario`(L3 conftest 재-export) 는 role별 독립 세션 클라이언트를, `doc_tree_scenario` 는
editor 가 만든 실제 문서 트리를 제공한다. INV-9(잠금 최대 1인) 충돌·이전 관측을 위해 두 번째
editor(B)를 admin 생성 + owner 멤버 추가 + 로그인으로 실제 provision 한다.
"""

from tests.integration_L1 import helpers as l1_helpers

# 인증되었으나(자격 무관) 대상 문서가 존재하지 않을 때 어댑터의 매핑-실패(→404)를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999


def _provision_member(scenario, harness, *, role: str, prefix: str):
    """admin 이 사용자를 만들고 owner 가 지정 role 로 멤버 추가한 뒤 그 자격으로 로그인한다.

    INV-9 충돌 시나리오에 필요한 두 번째 editor(B) 등을 실제 라우트로 provision 하는 setup
    헬퍼다(L2 conftest `_create_and_login` + owner 멤버 추가 관용 재현). (user_id, 인증 client)
    를 반환하며 client 는 자신의 세션 쿠키를 유지한다.
    """
    login_id = l1_helpers.unique_login_id(prefix)
    user_id = l1_helpers.create_user(
        scenario.admin_client, login_id, l1_helpers.DEFAULT_PASSWORD, name=prefix
    )
    member_resp = scenario.owner_client.post(
        f"/workspaces/{scenario.workspace_id}/members",
        json={"user_id": user_id, "role": role},
    )
    assert member_resp.status_code == 201, (
        f"{role} 멤버 추가 201 이어야 한다: "
        f"{member_resp.status_code} {member_resp.text}"
    )
    client = harness.login(login_id, l1_helpers.DEFAULT_PASSWORD)
    return user_id, client


def _versions_total(client, document_id: int) -> int:
    """`GET /documents/{id}/versions` 로 버전 개수(`total`)를 관측한다(성공 200 단언)."""
    resp = client.get(f"/documents/{document_id}/versions")
    assert resp.status_code == 200, (
        f"버전 목록 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()["total"]


# =============================================================================
# 1) 잠금→저장 왕복 + INV-9 (핵심) — Req 1.1·1.2·2.1·2.2·2.3·2.6, INV-9
# =============================================================================


def test_lock_save_roundtrip_and_inv9_lock_transfer(doc_tree_scenario, harness):
    """editor A 잠금 → editor B 409 → A 저장(버전 생성·해제) → B 잠금 성공(INV-9 이전) 왕복.

    핵심 시나리오: 한 문서 잠금은 최대 1인(INV-9)이 `lock_user_id` 단일 컬럼으로 강제되며, A 가
    저장으로 잠금을 해제하면 B 가 이어서 획득할 수 있다(이전 가능). 저장 응답은 본문 없는
    `DocumentVersionRead`(id·document_id·created_by==A·created_at)이고, 저장된 본문은 s07
    `GET /documents/{id}`(content=현재 버전 본문)로 관측된다.
    """
    scenario = doc_tree_scenario.scenario
    doc_id = doc_tree_scenario.root_id
    editor_a = doc_tree_scenario.editor_client
    editor_a_id = scenario.editor_user_id

    # editor B 를 실제로 provision(admin 생성 + owner 가 editor 멤버 추가 + 로그인).
    editor_b_id, editor_b = _provision_member(
        scenario, harness, role="member", prefix="editorB"
    )
    assert editor_b_id != editor_a_id, "두 editor 는 서로 다른 사용자여야 한다(INV-9 충돌 관측)"

    # (1) editor A 가 잠금 획득 → 200 + DocumentLockRead(요청자·획득 시각).
    lock_a = editor_a.post(f"/documents/{doc_id}/lock")
    assert lock_a.status_code == 200, (
        f"editor A 잠금 획득 200 이어야 한다(1.1): {lock_a.status_code} {lock_a.text}"
    )
    lock_body = lock_a.json()
    assert lock_body["document_id"] == doc_id, "잠금 응답 document_id 는 대상 문서여야 한다"
    assert lock_body["lock_user_id"] == editor_a_id, (
        "잠금 보유자는 요청자 A 여야 한다(INV-9 단일 근거)"
    )
    assert lock_body["lock_acquired_at"], "획득 시각(lock_acquired_at)이 기록되어야 한다(1.1)"

    # (2) editor B 가 잠금 시도 → 409(다른 사용자가 편집 중, INV-9).
    lock_b_conflict = editor_b.post(f"/documents/{doc_id}/lock")
    assert lock_b_conflict.status_code == 409, (
        f"타인 잠금 문서 편집 시작은 409 여야 한다(1.2, INV-9): "
        f"{lock_b_conflict.status_code} {lock_b_conflict.text}"
    )

    # (3) editor A 가 저장 → 200 + DocumentVersionRead(본문 없는 메타데이터, created_by==A).
    save_a = editor_a.post(f"/documents/{doc_id}/save", json={"content": "# hello"})
    assert save_a.status_code == 200, (
        f"잠금 보유자 저장은 200 이어야 한다(2.1): {save_a.status_code} {save_a.text}"
    )
    version = save_a.json()
    assert isinstance(version["id"], int) and version["id"] > 0, "새 버전 식별자가 있어야 한다"
    assert version["document_id"] == doc_id, "버전은 대상 문서에 속해야 한다"
    assert version["created_by"] == editor_a_id, "저장자(created_by)는 요청자 A 여야 한다(2.1)"
    assert version["created_at"], "저장 시각(created_at)이 있어야 한다(2.6)"
    assert "content" not in version, (
        "DocumentVersionRead 는 본문(content)을 노출하지 않는다(5.3, 메타데이터 전용)"
    )

    # (4) 저장된 본문이 현재 버전으로 갱신되었음을 s07 GET /documents/{id} 로 관측(current_version 갱신, 2.2).
    got = editor_a.get(f"/documents/{doc_id}")
    assert got.status_code == 200, f"문서 조회 200: {got.status_code} {got.text}"
    assert got.json()["content"] == "# hello", (
        "저장 후 현재 본문이 새 버전으로 갱신되어야 한다(2.2, current_version_id)"
    )

    # (5) 저장한 버전이 목록에 나타난다(무한 보관·최신순, 5.1·5.4).
    versions = editor_a.get(f"/documents/{doc_id}/versions")
    assert versions.status_code == 200, (
        f"버전 목록 200: {versions.status_code} {versions.text}"
    )
    page = versions.json()
    assert page["total"] >= 1, "저장 후 버전이 최소 1개 존재해야 한다(5.1)"
    assert version["id"] in {item["id"] for item in page["items"]}, (
        "저장한 버전이 목록에 포함되어야 한다(5.4)"
    )

    # (6) A 의 저장으로 잠금이 해제되었으므로 editor B 가 이제 잠금을 획득할 수 있다(INV-9 이전 가능, 2.3).
    lock_b_ok = editor_b.post(f"/documents/{doc_id}/lock")
    assert lock_b_ok.status_code == 200, (
        f"저장으로 해제된 뒤 editor B 잠금 획득은 200 이어야 한다(INV-9 이전, 2.3): "
        f"{lock_b_ok.status_code} {lock_b_ok.text}"
    )
    assert lock_b_ok.json()["lock_user_id"] == editor_b_id, (
        "이전된 잠금 보유자는 B 여야 한다(INV-9 최대 1인)"
    )


# =============================================================================
# 2) 권한 게이팅 (s05 멤버십; INV-1·2·3) — Req 1.5·3.5·4.2·5.5, 7.3
# =============================================================================


def test_lock_save_cancel_gate_viewer_denied_editor_admin_pass(ws_scenario):
    """lock/save/cancel(EDITOR 게이트): viewer 403(INV-2)·editor 통과·admin bypass(INV-3).

    문서가 미잠금인 동안 viewer 의 lock/save/cancel 은 role 게이트에서 403(충돌 이전에 판정).
    editor 는 잠금·저장으로 통과하고(EDITOR 이상), 비멤버 admin 은 잠금·취소로 게이트를 bypass
    한다(INV-3). 저장·취소가 잠금을 해제하므로 액터 간 순서를 조정해 충돌을 피한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    doc = editor.post(
        f"/workspaces/{ws_id}/documents", json={"title": "게이트대상"}
    ).json()
    doc_id = doc["id"]

    # (viewer 거부, INV-2) 문서 미잠금 상태에서 세 변경 연산 모두 403 (게이트 판정, 충돌 아님).
    assert editor.get(f"/documents/{doc_id}").status_code == 200  # 미잠금 확인용 조회
    viewer = ws_scenario.viewer_client
    assert viewer.post(f"/documents/{doc_id}/lock").status_code == 403, "viewer lock 403(INV-2)"
    assert viewer.post(
        f"/documents/{doc_id}/save", json={"content": "x"}
    ).status_code == 403, "viewer save 403(INV-2)"
    assert viewer.post(f"/documents/{doc_id}/cancel").status_code == 403, "viewer cancel 403(INV-2)"

    # (editor 통과) 잠금 → 저장(해제)로 EDITOR 게이트 통과를 확인한다.
    assert editor.post(f"/documents/{doc_id}/lock").status_code == 200, "editor lock 통과(3.1)"
    assert editor.post(
        f"/documents/{doc_id}/save", json={"content": "editor본문"}
    ).status_code == 200, "editor save 통과(2.1)"

    # (admin bypass, INV-3) 비멤버 admin 이 잠금 → 취소(해제)로 EDITOR 게이트를 bypass 한다.
    admin = ws_scenario.admin_client
    assert admin.post(f"/documents/{doc_id}/lock").status_code == 200, "admin lock bypass(INV-3)"
    assert admin.post(f"/documents/{doc_id}/cancel").status_code == 204, "admin cancel bypass(INV-3)"


def test_force_unlock_gate_owner_admin_pass_editor_viewer_denied(ws_scenario):
    """force-unlock(OWNER 게이트): owner·admin 통과·editor 403(OWNER 미만)·viewer 403(4.2, INV-1·3).

    강제 해제는 OWNER 이상만 통과한다. editor 는 EDITOR 이지만 OWNER 미만이라 403, viewer 도
    403 이다. owner 는 통과(잠긴 문서 해제), admin 은 비멤버라도 bypass 로 통과(멱등 no-op).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    doc = editor.post(
        f"/workspaces/{ws_id}/documents", json={"title": "강제해제게이트"}
    ).json()
    doc_id = doc["id"]

    # editor 가 잠가 방치된 잠금을 만든다(강제 해제 대상).
    assert editor.post(f"/documents/{doc_id}/lock").status_code == 200

    # (거부) editor 는 OWNER 미만이라 403, viewer 도 403 (게이트 판정).
    assert editor.post(f"/documents/{doc_id}/force-unlock").status_code == 403, (
        "editor 는 OWNER 미만이라 force-unlock 403 이어야 한다(4.2)"
    )
    assert ws_scenario.viewer_client.post(
        f"/documents/{doc_id}/force-unlock"
    ).status_code == 403, "viewer force-unlock 403(4.2, INV-1·2)"

    # (통과) owner 가 editor 의 잠금을 강제 해제한다(204).
    assert ws_scenario.owner_client.post(
        f"/documents/{doc_id}/force-unlock"
    ).status_code == 204, "owner force-unlock 통과(4.1)"

    # (admin bypass) 이미 해제된 문서라도 비멤버 admin 이 멱등 성공으로 게이트를 bypass 한다(4.3, INV-3).
    assert ws_scenario.admin_client.post(
        f"/documents/{doc_id}/force-unlock"
    ).status_code == 204, "admin force-unlock bypass·멱등(4.3, INV-3)"


def test_versions_read_open_to_all_active_users_unauthenticated_401(ws_scenario, harness):
    """versions(읽기 전역 개방): 비멤버·admin 모두 200·미인증 401(s26 Req 3.3·3.8·7.2, 5.5).

    버전 이력 읽기는 s26 개방으로 활성 사용자면 멤버십과 무관하게 200 이다(빈 이력도 200 Page).
    비멤버 활성 사용자(viewer·nonmember)도 200 이며(더 이상 403 아님), 미인증(세션 없는 신규
    client)만 s01 get_current_user 가 401 로 거부한다.
    """
    ws_id = ws_scenario.workspace_id
    doc = ws_scenario.editor_client.post(
        f"/workspaces/{ws_id}/documents", json={"title": "버전게이트"}
    ).json()
    doc_id = doc["id"]

    # (개방) member·비멤버·admin 모두 버전 이력 200(빈 이력도 Page) — 읽기 전역 개방.
    for label, client in (
        ("member", ws_scenario.editor_client),
        ("viewer(비멤버)", ws_scenario.viewer_client),
        ("nonmember", ws_scenario.nonmember_client),
        ("admin", ws_scenario.admin_client),
    ):
        assert client.get(
            f"/documents/{doc_id}/versions"
        ).status_code == 200, f"{label} 버전 이력 읽기 200(전역 개방, 3.8)"

    # (미인증) 세션 없는 신규 client → 401(s01 get_current_user).
    anon = harness.new_client()
    assert anon.get(f"/documents/{doc_id}/versions").status_code == 401, (
        "미인증 요청은 401 이어야 한다(세션 없음)"
    )


# =============================================================================
# 3) 어댑터 게이팅 / 미존재 문서 → 404 — Req 1.6, 3.6, design §LockVersionRouter 게이트
# =============================================================================


def test_missing_document_maps_to_404_before_role_judgment(ws_scenario):
    """미존재 문서의 잠금·버전(및 저장)은 fully-authorized owner 에게도 404(어댑터 매핑 실패, 1.6).

    `/documents/{id}/*` 는 s07 문서→WS 어댑터가 문서 id→workspace_id 매핑에 실패하면 role 판정에
    **앞서** 404 를 낸다 — owner(게이트 통과 자격)로 호출해도 문서가 없으면 403 이 아니라 404 다.
    잠금·버전을 최소로 하되 저장까지 확인한다.
    """
    owner = ws_scenario.owner_client
    assert owner.post(f"/documents/{MISSING_DOCUMENT_ID}/lock").status_code == 404, (
        "미존재 문서 lock 은 authorized owner 에게도 404 여야 한다(어댑터 매핑 실패, 1.6)"
    )
    assert owner.get(f"/documents/{MISSING_DOCUMENT_ID}/versions").status_code == 404, (
        "미존재 문서 versions 는 authorized owner 에게도 404 여야 한다(어댑터 매핑 실패)"
    )
    assert owner.post(
        f"/documents/{MISSING_DOCUMENT_ID}/save", json={"content": "x"}
    ).status_code == 404, "미존재 문서 save 도 404 여야 한다(role 판정 이전)"


# =============================================================================
# 4) 취소·강제해제는 버전 없이 잠금만 해제 — Req 3.1·3.4·4.1, design §취소·강제해제 흐름
# =============================================================================


def test_cancel_releases_lock_without_creating_version(doc_tree_scenario):
    """editor A 취소 → 잠금 해제(A 재잠금 가능)·버전 미생성(3.1·3.4).

    저장 없이 취소하면 잠금만 풀리고 어떤 `document_version` 도 만들어지지 않는다. 취소 전후
    버전 개수가 동일하고, 해제되었으므로 A 가 다시 잠글 수 있음을 확인한다.
    """
    doc_id = doc_tree_scenario.child_id
    editor_a = doc_tree_scenario.editor_client

    before = _versions_total(editor_a, doc_id)

    assert editor_a.post(f"/documents/{doc_id}/lock").status_code == 200, "A 잠금 획득 200"
    assert editor_a.post(f"/documents/{doc_id}/cancel").status_code == 204, (
        "취소는 204(잠금 해제, 3.1)"
    )

    after = _versions_total(editor_a, doc_id)
    assert after == before, "취소는 어떤 버전도 만들지 않는다(버전 개수 불변, 3.4)"

    # 해제되었으므로 A 가 다시 잠글 수 있다(취소가 실제 잠금을 풀었음).
    assert editor_a.post(f"/documents/{doc_id}/lock").status_code == 200, (
        "취소로 해제된 뒤 A 재잠금 200(잠금이 실제로 풀렸음)"
    )


def test_force_unlock_releases_lock_without_creating_version(doc_tree_scenario):
    """editor A 잠금 → owner 강제 해제 → 잠금 해제(A 재잠금 가능)·미저장 변경분 폐기·버전 미생성(4.1).

    A 가 잠근 문서를 owner 가 강제 해제하면 A 의 미저장 변경분은 폐기되고(새 버전 없음) 잠금이
    풀린다. 강제 해제 전후 버전 개수가 동일하고, A 가 다시 잠글 수 있음을 확인한다.
    """
    scenario = doc_tree_scenario.scenario
    doc_id = doc_tree_scenario.grandchild_id
    editor_a = doc_tree_scenario.editor_client
    owner = scenario.owner_client

    before = _versions_total(editor_a, doc_id)

    assert editor_a.post(f"/documents/{doc_id}/lock").status_code == 200, "A 잠금 획득 200"
    assert owner.post(f"/documents/{doc_id}/force-unlock").status_code == 204, (
        "owner 강제 해제 204(4.1)"
    )

    after = _versions_total(editor_a, doc_id)
    assert after == before, "강제 해제는 어떤 버전도 만들지 않는다(변경분 폐기, 4.1)"

    # 해제되었으므로 A 가 다시 잠글 수 있다(강제 해제가 실제 잠금을 풀었음).
    assert editor_a.post(f"/documents/{doc_id}/lock").status_code == 200, (
        "강제 해제로 풀린 뒤 A 재잠금 200(잠금이 실제로 풀렸음)"
    )
