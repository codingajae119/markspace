"""s14 발급·토글·게이트·재발급 통합 테스트 (Task 4.1 / design §Testing Strategy
「발급·토글·게이트·재발급 seam」, Req 1.1, 1.4, 2.1, 2.2, 2.3, 2.6, 4.1, 4.2, 4.3, 7.1, 7.2).

마이그레이션된 실제 MySQL 테스트 DB + s14 공유 라우터가 조립된 부팅 앱(`app.main.create_app`,
task 3.3) 위에서 mock 없이 발급·토글·공개 렌더의 실제 seam 을 검증한다. 하네스·워크스페이스
시나리오·문서 트리는 `tests/sharing/conftest.py`(L3 체인 재사용)에서 온다. 부팅 앱이므로
게이트(`workspace.is_shareable`)는 s05 `PATCH /workspaces/{id}`(owner)로, active 문서는 s07
`POST /workspaces/{id}/documents`(editor, `doc_tree_scenario`)로 실제 라우트에서 준비한다.

검증 시나리오 그룹(design §Testing Strategy 발급·토글·게이트·재발급 seam):

1. **해피 패스 + 토글 토큰 유지(Req 1.1·4.1·4.2·4.3)**: 게이트 on 의 active 문서에 editor 가
   발급→`GET /public/{token}` 200→토글 off→동일 토큰 404→토글 on→동일 토큰 200. 토글이 재발급
   통일 원칙(INV-8)의 유일한 상태 기반 예외로 **토큰을 유지**함을 토글 전 구간에서 단언한다.
2. **게이트 off(Req 1.1)**: 게이트 off 워크스페이스에서 발급 409; 발급 후 게이트를 끄면 활성화
   토글도 409(활성화가 게이트 off 에서 거부됨을 클린 케이스로 증명).
3. **멤버십 게이팅(Req 2.2·2.3·2.6, INV-1·2·3)**: viewer 403·editor 통과·비인증 401·admin
   비멤버 bypass 200·문서 미존재 404. 공유 권한이 문서별 개별 권한 없이 WS 단위 resolver 로만
   게이팅됨(INV-1)을 WS 내 다중 문서로 증명한다.
4. **계약 형태(Req 7.1·7.2)**: 발급/토글 응답이 `ShareLinkRead`(`TimestampedRead` 상속) 규약을,
   오류 본문이 s01 `ErrorResponse`(code/message) 규약을 따르고, 공개 응답이 내부 필드
   (`workspace_id`·`created_by`·`sort_order`·`status`·`parent_id`)를 노출하지 않음을 단언한다.

제약: 애플리케이션 코드·다른 spec 자산을 수정하지 않는다(통합 테스트만 추가). DB 미가용·부팅
실패는 스킵이 아니라 실패다(하네스가 오류 전파). 공유 테스트 DB 오염 방지는 하네스 격리에 의존.
"""

from tests.integration_L2 import helpers as l2_helpers


def _enable_gate(scenario) -> None:
    """워크스페이스 `is_shareable` 게이트를 owner 세션으로 켠다(s05 `PATCH /workspaces/{id}`).

    `doc_tree_scenario` 의 워크스페이스는 게이트 OFF 로 시작하므로, 발급/활성화가 가능하려면
    실제 owner 라우트로 게이트를 켜야 한다(s14 는 게이트를 소유하지 않고 관측만 하므로 s05
    라우트로 준비한다).
    """
    l2_helpers.update_settings(
        scenario.owner_client, scenario.workspace_id, is_shareable=True
    )


def _disable_gate(scenario) -> None:
    """워크스페이스 `is_shareable` 게이트를 owner 세션으로 끈다(s05 라우트)."""
    l2_helpers.update_settings(
        scenario.owner_client, scenario.workspace_id, is_shareable=False
    )


# --- 1. 해피 패스 + 토글 토큰 유지(Req 1.1·4.1·4.2·4.3, INV-8 예외) -----------------


def test_issue_render_toggle_preserves_token(doc_tree_scenario, harness):
    """게이트 on active 문서: 발급→공개 200→토글 off→404→토글 on→200, 토큰 전 구간 유지."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id
    anon = harness.new_client()  # 공개 경로는 인증이 없어 로그인하지 않은 클라이언트로 접근.

    # 발급(editor) → 200 + ShareLinkRead(활성·토큰·share_url).
    issue = editor.post(f"/documents/{doc_id}/share")
    assert issue.status_code == 200, issue.text
    body = issue.json()
    token = body["token"]
    assert body["document_id"] == doc_id
    assert body["is_enabled"] is True
    assert body["share_url"] == f"/public/{token}"
    assert isinstance(body["id"], int)
    assert body["created_at"], "created_at 이 채워져야 한다"

    # 공개 렌더(활성 링크) → 200 + 문서 트리(root = 공유 문서).
    rendered = anon.get(f"/public/{token}")
    assert rendered.status_code == 200, rendered.text
    assert rendered.json()["root"]["id"] == doc_id

    # 토글 off → 200, is_enabled false, 토큰 유지.
    off = editor.patch(f"/documents/{doc_id}/share", json={"is_enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["is_enabled"] is False
    assert off.json()["token"] == token, "토글 off 는 토큰을 유지해야 한다"

    # 동일 토큰 공개 접근 → 404(비활성 링크 접근 차단).
    blocked = anon.get(f"/public/{token}")
    assert blocked.status_code == 404
    assert blocked.json()["code"] == "not_found"

    # 토글 on → 200, is_enabled true, **여전히 동일 토큰**(재발급 아님, INV-8 예외).
    on = editor.patch(f"/documents/{doc_id}/share", json={"is_enabled": True})
    assert on.status_code == 200, on.text
    assert on.json()["is_enabled"] is True
    assert on.json()["token"] == token, "토글 on 은 새 토큰을 만들지 않는다(토큰 유지)"

    # 동일 토큰 재접근 → 200(토큰이 살아 있어 되살아남 — 토글만이 상태 기반 예외).
    restored = anon.get(f"/public/{token}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["root"]["id"] == doc_id


# --- 2. 게이트 off(Req 1.1) ---------------------------------------------------------


def test_issue_rejected_when_gate_off_409(doc_tree_scenario):
    """게이트 off 워크스페이스에서 발급 요청은 409 conflict(게이트 통과 후 서비스가 거부)."""
    # doc_tree_scenario 는 게이트 OFF 로 시작한다(플립하지 않음).
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    resp = editor.post(f"/documents/{doc_id}/share")

    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "conflict"


def test_activation_rejected_when_gate_off_409(doc_tree_scenario):
    """게이트 on 에서 발급→토글 off→게이트 off→활성화 토글은 409(게이트 off 활성화 거부)."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    # 게이트 on 에서 발급(활성 링크).
    issue = editor.post(f"/documents/{doc_id}/share")
    assert issue.status_code == 200, issue.text

    # 토글 off 는 게이트·status 무관하게 항상 허용(토큰 유지).
    off = editor.patch(f"/documents/{doc_id}/share", json={"is_enabled": False})
    assert off.status_code == 200, off.text

    # 게이트 off 로 전환한 뒤 활성화 토글 → 409(게이트 off 활성화 불가).
    _disable_gate(scenario)
    activate = editor.patch(
        f"/documents/{doc_id}/share", json={"is_enabled": True}
    )
    assert activate.status_code == 409, activate.text
    assert activate.json()["code"] == "conflict"


# --- 3. 멤버십 게이팅(Req 2.2·2.3·2.6, INV-1·2·3) ----------------------------------


def test_viewer_issue_and_toggle_forbidden_403(doc_tree_scenario):
    """viewer 는 게이트 on active 문서에서도 발급·토글이 403 forbidden(editor 미충족, INV-2)."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    viewer = scenario.viewer_client
    doc_id = doc_tree_scenario.root_id

    issue = viewer.post(f"/documents/{doc_id}/share")
    assert issue.status_code == 403
    assert issue.json()["code"] == "forbidden"

    toggle = viewer.patch(f"/documents/{doc_id}/share", json={"is_enabled": False})
    assert toggle.status_code == 403
    assert toggle.json()["code"] == "forbidden"


def test_editor_toggle_passes(doc_tree_scenario):
    """editor 는 발급 후 토글(off·on) 모두 통과한다(editor 이상 게이트 통과)."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    assert editor.post(f"/documents/{doc_id}/share").status_code == 200

    off = editor.patch(f"/documents/{doc_id}/share", json={"is_enabled": False})
    assert off.status_code == 200, off.text
    on = editor.patch(f"/documents/{doc_id}/share", json={"is_enabled": True})
    assert on.status_code == 200, on.text


def test_unauthenticated_issue_and_toggle_401(doc_tree_scenario, harness):
    """비인증(세션 없음) 발급·토글은 401 unauthenticated(s01 get_current_user, INV-2)."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    doc_id = doc_tree_scenario.root_id
    anon = harness.new_client()  # 로그인하지 않은 신규 클라이언트.

    issue = anon.post(f"/documents/{doc_id}/share")
    assert issue.status_code == 401
    assert issue.json()["code"] == "unauthenticated"

    toggle = anon.patch(f"/documents/{doc_id}/share", json={"is_enabled": False})
    assert toggle.status_code == 401
    assert toggle.json()["code"] == "unauthenticated"


def test_admin_nonmember_bypasses_to_issue_200(doc_tree_scenario):
    """admin 은 이 워크스페이스 비멤버여도 발급 게이트를 bypass 한다(INV-3)."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    admin = scenario.admin_client  # 시드 admin 은 이 WS 의 멤버가 아니다.
    doc_id = doc_tree_scenario.root_id

    resp = admin.post(f"/documents/{doc_id}/share")

    assert resp.status_code == 200, resp.text
    assert resp.json()["is_enabled"] is True


def test_nonexistent_document_issue_and_toggle_404(doc_tree_scenario):
    """미존재 문서 id 로의 발급·토글은 문서→WS 어댑터가 판정 전에 404 로 거부한다."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    missing_id = 999_999_999  # 어떤 문서에도 매핑되지 않는 id.

    issue = editor.post(f"/documents/{missing_id}/share")
    assert issue.status_code == 404
    assert issue.json()["code"] == "not_found"

    toggle = editor.patch(
        f"/documents/{missing_id}/share", json={"is_enabled": False}
    )
    assert toggle.status_code == 404
    assert toggle.json()["code"] == "not_found"


def test_sharing_gated_by_ws_resolver_not_per_document(doc_tree_scenario):
    """공유 권한은 문서별 개별 권한 없이 WS 단위 resolver 로만 게이팅된다(INV-1).

    editor 멤버십 하나로 WS 내 root/child/grandchild 어떤 문서든 발급 가능하고, viewer 는 같은
    WS 의 어떤 문서에도 발급할 수 없다 — 문서별 grant 가 존재하지 않음을 증명한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    viewer = scenario.viewer_client
    all_docs = (
        doc_tree_scenario.root_id,
        doc_tree_scenario.child_id,
        doc_tree_scenario.grandchild_id,
    )

    # editor: WS 단위 role 하나로 모든 문서 발급 통과(문서별 개별 권한 불요).
    for doc_id in all_docs:
        resp = editor.post(f"/documents/{doc_id}/share")
        assert resp.status_code == 200, (doc_id, resp.text)

    # viewer: 같은 WS 의 어떤 문서에도 발급 거부(WS 단위 거부, 문서별 예외 없음).
    for doc_id in all_docs:
        resp = viewer.post(f"/documents/{doc_id}/share")
        assert resp.status_code == 403, (doc_id, resp.text)


# --- 4. 계약 형태(Req 7.1·7.2) -----------------------------------------------------


def test_share_link_read_contract_shape(doc_tree_scenario):
    """발급 응답이 `ShareLinkRead`(`TimestampedRead` 상속) 규약을 따르고 내부 컬럼을 노출 안 함."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    resp = editor.post(f"/documents/{doc_id}/share")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # ShareLinkRead 필수 필드(id·created_at 은 TimestampedRead 상속).
    for key in ("id", "document_id", "token", "is_enabled", "share_url", "created_at"):
        assert key in body, f"{key} 누락: {body}"
    assert isinstance(body["id"], int)
    assert isinstance(body["document_id"], int) and body["document_id"] == doc_id
    assert isinstance(body["token"], str) and body["token"]
    assert body["is_enabled"] is True
    assert body["share_url"] == f"/public/{body['token']}"
    # share_link 테이블에 updated_at 컬럼이 없어 상속 필드는 null 로 직렬화된다.
    assert body.get("updated_at") is None
    # 내부/무관 필드 비노출.
    for internal in ("workspace_id", "created_by", "password_hash", "status"):
        assert internal not in body, f"내부 필드 {internal} 노출: {body}"


def test_error_bodies_follow_s01_error_response(doc_tree_scenario):
    """발급/토글 오류 본문이 s01 `ErrorResponse`(code/message) 규약을 따른다(409·403·404)."""
    scenario = doc_tree_scenario.scenario
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    # 게이트 off 발급 → 409 conflict.
    conflict = editor.post(f"/documents/{doc_id}/share")
    assert conflict.status_code == 409, conflict.text
    cbody = conflict.json()
    assert {"code", "message"}.issubset(cbody.keys())
    assert cbody["code"] == "conflict"
    assert isinstance(cbody["message"], str) and cbody["message"]

    # 게이트 on 후 viewer 발급 → 403 forbidden.
    _enable_gate(scenario)
    forbidden = scenario.viewer_client.post(f"/documents/{doc_id}/share")
    assert forbidden.status_code == 403
    fbody = forbidden.json()
    assert {"code", "message"}.issubset(fbody.keys())
    assert fbody["code"] == "forbidden"
    assert isinstance(fbody["message"], str) and fbody["message"]

    # 미존재 문서 발급 → 404 not_found.
    not_found = editor.post("/documents/999999999/share")
    assert not_found.status_code == 404
    nbody = not_found.json()
    assert {"code", "message"}.issubset(nbody.keys())
    assert nbody["code"] == "not_found"


def test_public_render_omits_internal_fields(doc_tree_scenario, harness):
    """공개 응답 노드가 최소 노출(id·title·content_html·children)만 담고 내부 필드를 노출 안 함."""
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    issue = editor.post(f"/documents/{doc_id}/share")
    assert issue.status_code == 200, issue.text
    token = issue.json()["token"]

    anon = harness.new_client()
    rendered = anon.get(f"/public/{token}")
    assert rendered.status_code == 200, rendered.text
    root = rendered.json()["root"]
    assert root["id"] == doc_id

    # root + 모든 하위 노드가 정확히 최소 필드만 노출(내부 필드 완전 배제).
    _INTERNAL = {"workspace_id", "created_by", "sort_order", "status", "parent_id"}

    def _assert_minimal(node: dict) -> None:
        assert set(node.keys()) == {"id", "title", "content_html", "children"}, (
            f"공개 노드가 최소 필드만 노출해야 한다: {sorted(node.keys())}"
        )
        for field in _INTERNAL:
            assert field not in node, f"내부 필드 {field} 노출: {node}"
        for child in node["children"]:
            _assert_minimal(child)

    _assert_minimal(root)
    # 문서 트리(root→child→grandchild)가 공개 렌더에 동적으로 포함됨을 함께 확인.
    assert root["children"], "active 하위(child)가 공개 트리에 포함되어야 한다"
