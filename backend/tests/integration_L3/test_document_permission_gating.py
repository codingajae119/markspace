"""문서 권한 게이팅 스위트 — role 위계·비멤버 차단·admin bypass·문서→WS 어댑터 (Task 2.2 /
Req 3.1·3.2·3.3·3.4·3.5·3.6, design §DocumentPermissionGatingSuite).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕**s07**) + **실제 세션 쿠키** 위에서 문서 라우트의
권한 게이팅을 mock 없이 e2e 로 관찰한다. 판정은 `s05` 가 채운 **실제 `workspace_member` 데이터**
위에서 `s01` `require_ws_role` resolver 가 수행하며, `/documents/{id}` 계열은 `s07` 문서→WS
어댑터가 문서 id 로 workspace_id 를 추출해 resolver 에 위임한다. 게이트가 오작동하면 단언을
약화시키지 않고 실제 회귀(s01 resolver / s07 어댑터 / s05 멤버십 데이터 경계)를 그대로 표면화한다.

`ws_scenario` 픽스처(L3 conftest 가 L2 에서 재-export)가 role별 **독립 세션 클라이언트**를 제공한다:
owner(WS 생성자, owner ≥ EDITOR)·editor(EDITOR 멤버)·viewer(VIEWER 멤버)·nonmember(로그인했으나
이 WS 비멤버)·admin(시드 admin, 이 WS **비멤버** — bypass 관찰용). 각 함수는 함수 스코프로 독립된
워크스페이스를 받으므로 테스트 간 상태 간섭이 없다. 문서 라우트 호출은 L3 `helpers` 의 `attempt_*`
래퍼(상태 미단언, 응답 그대로 반환)로 통과(2xx)·거부(403/404)를 **둘 다** 단언한다.

스위트 구조 — Requirement 3 의 role × operation 매트릭스:
- **그룹 1 editor 게이트(변경: 생성·수정·이동·삭제)**: owner·editor 통과(3.1)·viewer 403(3.2, INV-2
  읽기 전용)·비멤버 403(3.4, INV-1). 삭제는 파괴적이므로 성공 액터마다 새 문서를 만들고, viewer·
  비멤버 거부는 문서가 아직 active 인 상태에서 관측한다.
- **그룹 2 viewer 게이트(조회: 상세·목록)**: owner·editor·viewer 통과(3.3)·비멤버 403(3.4, INV-1).
- **그룹 3 admin bypass(3.5, INV-3)**: 비멤버 admin 이 6개 연산(조회·목록·생성·수정·이동·삭제) 전부
  접근 성공(게이트 자체를 bypass).
- **그룹 4 문서→WS 어댑터(3.6)**: 미존재 문서는 fully-authorized owner 에게도 role 판정에 앞서 404
  (어댑터 매핑 실패), 존재 문서 + 권한 미충족은 403(어댑터가 resolver 위계·admin bypass 를
  재구현하지 않고 위임함).
"""

from uuid import uuid4

from tests.integration_L3 import helpers

# 인증되었으나(자격 무관) 대상이 존재하지 않을 때 어댑터의 매핑-실패(→404)를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999


def _title(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


# =============================================================================
# 그룹 1: editor 게이트 (변경: 생성·수정·이동·삭제) — 3.1·3.2·3.4 (INV-1·2)
#   매트릭스: owner 통과 · editor 통과 · viewer 403 · nonmember 403
# =============================================================================


def test_create_gate_role_matrix(ws_scenario):
    """생성 게이트(EDITOR): owner·editor 통과(3.1)·viewer 403(3.2, INV-2)·비멤버 403(3.4, INV-1).

    ``POST /workspaces/{id}/documents`` 는 경로 workspace_id 로 직접 게이트된다. owner(owner ≥
    EDITOR)·editor 는 201 로 통과하고, viewer 는 변경 거부(INV-2 읽기 전용) 403, 비멤버는 비멤버
    차단(INV-1) 403 이다.
    """
    ws_id = ws_scenario.workspace_id

    owner_ok = helpers.attempt_create_document(
        ws_scenario.owner_client, ws_id, _title("owner생성")
    )
    assert owner_ok.status_code == 201, (
        f"owner(≥EDITOR)는 생성 게이트를 통과해야 한다(3.1): "
        f"{owner_ok.status_code} {owner_ok.text}"
    )

    editor_ok = helpers.attempt_create_document(
        ws_scenario.editor_client, ws_id, _title("editor생성")
    )
    assert editor_ok.status_code == 201, (
        f"editor 는 생성 게이트를 통과해야 한다(3.1): "
        f"{editor_ok.status_code} {editor_ok.text}"
    )

    viewer_denied = helpers.attempt_create_document(
        ws_scenario.viewer_client, ws_id, _title("viewer생성")
    )
    assert viewer_denied.status_code == 403, (
        f"viewer 변경 거부(INV-2, 3.2): {viewer_denied.status_code} {viewer_denied.text}"
    )

    nonmember_denied = helpers.attempt_create_document(
        ws_scenario.nonmember_client, ws_id, _title("비멤버생성")
    )
    assert nonmember_denied.status_code == 403, (
        f"비멤버 차단(INV-1, 3.4): "
        f"{nonmember_denied.status_code} {nonmember_denied.text}"
    )


def test_patch_gate_role_matrix(ws_scenario):
    """수정 게이트(EDITOR): owner·editor 통과(3.1)·viewer 403(3.2, INV-2)·비멤버 403(3.4, INV-1).

    editor 가 만든 대상 문서를 각 role 세션으로 ``PATCH /documents/{id}`` 한다. 대상은 존재하므로
    거부는 404(어댑터 매핑 실패)가 아니라 role 미충족 403 이다(존재 문서 + 권한 미충족 → 403).
    """
    ws_id = ws_scenario.workspace_id
    doc = helpers.create_document(ws_scenario.editor_client, ws_id, _title("수정대상"))
    doc_id = doc["id"]

    owner_ok = helpers.attempt_patch_title(
        ws_scenario.owner_client, doc_id, _title("owner수정")
    )
    assert owner_ok.status_code == 200, (
        f"owner(≥EDITOR)는 수정 게이트를 통과해야 한다(3.1): "
        f"{owner_ok.status_code} {owner_ok.text}"
    )

    editor_ok = helpers.attempt_patch_title(
        ws_scenario.editor_client, doc_id, _title("editor수정")
    )
    assert editor_ok.status_code == 200, (
        f"editor 는 수정 게이트를 통과해야 한다(3.1): "
        f"{editor_ok.status_code} {editor_ok.text}"
    )

    viewer_denied = helpers.attempt_patch_title(
        ws_scenario.viewer_client, doc_id, _title("viewer수정")
    )
    assert viewer_denied.status_code == 403, (
        f"viewer 변경 거부(INV-2, 3.2): {viewer_denied.status_code} {viewer_denied.text}"
    )

    nonmember_denied = helpers.attempt_patch_title(
        ws_scenario.nonmember_client, doc_id, _title("비멤버수정")
    )
    assert nonmember_denied.status_code == 403, (
        f"비멤버 차단(INV-1, 3.4): "
        f"{nonmember_denied.status_code} {nonmember_denied.text}"
    )


def test_move_gate_role_matrix(ws_scenario):
    """이동 게이트(EDITOR): owner·editor 통과(3.1)·viewer 403(3.2, INV-2)·비멤버 403(3.4, INV-1).

    빈 이동 본문(형제 참조 없음)은 루트 append 로 200 이 되도록 성공 케이스를 구성한다(형제 정렬
    세부는 이동 스위트가 소유). 대상 문서가 존재하므로 거부는 role 미충족 403 이다.
    """
    ws_id = ws_scenario.workspace_id
    doc = helpers.create_document(ws_scenario.editor_client, ws_id, _title("이동대상"))
    doc_id = doc["id"]

    owner_ok = helpers.attempt_move_document(ws_scenario.owner_client, doc_id)
    assert owner_ok.status_code == 200, (
        f"owner(≥EDITOR)는 이동 게이트를 통과해야 한다(3.1): "
        f"{owner_ok.status_code} {owner_ok.text}"
    )

    editor_ok = helpers.attempt_move_document(ws_scenario.editor_client, doc_id)
    assert editor_ok.status_code == 200, (
        f"editor 는 이동 게이트를 통과해야 한다(3.1): "
        f"{editor_ok.status_code} {editor_ok.text}"
    )

    viewer_denied = helpers.attempt_move_document(ws_scenario.viewer_client, doc_id)
    assert viewer_denied.status_code == 403, (
        f"viewer 변경 거부(INV-2, 3.2): {viewer_denied.status_code} {viewer_denied.text}"
    )

    nonmember_denied = helpers.attempt_move_document(
        ws_scenario.nonmember_client, doc_id
    )
    assert nonmember_denied.status_code == 403, (
        f"비멤버 차단(INV-1, 3.4): "
        f"{nonmember_denied.status_code} {nonmember_denied.text}"
    )


def test_delete_gate_role_matrix(ws_scenario):
    """삭제 게이트(EDITOR): owner·editor 통과(3.1)·viewer 403(3.2, INV-2)·비멤버 403(3.4, INV-1).

    삭제는 파괴적이므로 성공 액터(owner·editor)마다 **별도 문서**를 만든다. viewer·비멤버 거부는
    아직 active 인 별도 문서에서 관측하여(거부가 실제 게이트 판정임을 보장) 삭제로 소진되지 않게 한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    # (성공) owner·editor 는 각자 새 문서를 삭제한다(파괴적 → 액터별 별도 문서).
    doc_for_owner = helpers.create_document(editor, ws_id, _title("owner삭제대상"))
    owner_ok = helpers.attempt_delete_document(
        ws_scenario.owner_client, doc_for_owner["id"]
    )
    assert owner_ok.status_code == 204, (
        f"owner(≥EDITOR)는 삭제 게이트를 통과해야 한다(3.1): "
        f"{owner_ok.status_code} {owner_ok.text}"
    )

    doc_for_editor = helpers.create_document(editor, ws_id, _title("editor삭제대상"))
    editor_ok = helpers.attempt_delete_document(editor, doc_for_editor["id"])
    assert editor_ok.status_code == 204, (
        f"editor 는 삭제 게이트를 통과해야 한다(3.1): "
        f"{editor_ok.status_code} {editor_ok.text}"
    )

    # (거부) viewer·비멤버 는 아직 active 인 별도 문서에서 거부된다(문서는 소진되지 않음).
    doc_active = helpers.create_document(editor, ws_id, _title("삭제거부관측대상"))
    viewer_denied = helpers.attempt_delete_document(
        ws_scenario.viewer_client, doc_active["id"]
    )
    assert viewer_denied.status_code == 403, (
        f"viewer 변경 거부(INV-2, 3.2): {viewer_denied.status_code} {viewer_denied.text}"
    )

    nonmember_denied = helpers.attempt_delete_document(
        ws_scenario.nonmember_client, doc_active["id"]
    )
    assert nonmember_denied.status_code == 403, (
        f"비멤버 차단(INV-1, 3.4): "
        f"{nonmember_denied.status_code} {nonmember_denied.text}"
    )

    # 거부 관측 후에도 문서가 여전히 active(미삭제)임을 editor 조회로 확인한다.
    still_active = helpers.attempt_get_document(editor, doc_active["id"])
    assert still_active.status_code == 200 and still_active.json()["status"] == "active", (
        f"거부된 삭제는 문서를 변경하지 않아야 한다(active 유지): "
        f"{still_active.status_code} {still_active.text}"
    )


# =============================================================================
# 그룹 2: viewer 게이트 (조회: 상세·목록) — 3.3·3.4 (INV-1)
#   매트릭스: owner 통과 · editor 통과 · viewer 통과 · nonmember 403
# =============================================================================


def test_get_detail_gate_role_matrix(ws_scenario):
    """상세 조회 게이트(VIEWER): owner·editor·viewer 통과(3.3)·비멤버 403(3.4, INV-1).

    editor 가 만든 문서를 각 role 세션으로 ``GET /documents/{id}`` 한다. VIEWER 이상은 200, 비멤버는
    존재 문서 + 권한 미충족 403(어댑터 매핑은 성공하고 resolver 가 role None 판정)이다.
    """
    ws_id = ws_scenario.workspace_id
    doc = helpers.create_document(ws_scenario.editor_client, ws_id, _title("조회대상"))
    doc_id = doc["id"]

    for label, client in (
        ("owner", ws_scenario.owner_client),
        ("editor", ws_scenario.editor_client),
        ("viewer", ws_scenario.viewer_client),
    ):
        resp = helpers.attempt_get_document(client, doc_id)
        assert resp.status_code == 200, (
            f"{label}(≥VIEWER)는 상세 조회를 통과해야 한다(3.3): "
            f"{resp.status_code} {resp.text}"
        )

    nonmember_denied = helpers.attempt_get_document(
        ws_scenario.nonmember_client, doc_id
    )
    assert nonmember_denied.status_code == 403, (
        f"비멤버 조회 차단(INV-1, 3.4): "
        f"{nonmember_denied.status_code} {nonmember_denied.text}"
    )


def test_list_gate_role_matrix(ws_scenario):
    """목록 조회 게이트(VIEWER): owner·editor·viewer 통과(3.3)·비멤버 403(3.4, INV-1).

    ``GET /workspaces/{id}/documents`` 는 경로 workspace_id 로 직접 게이트된다. VIEWER 이상은 200
    ``Page[DocumentRead]``, 비멤버는 비멤버 차단 403 이다.
    """
    ws_id = ws_scenario.workspace_id
    helpers.create_document(ws_scenario.editor_client, ws_id, _title("목록대상"))

    for label, client in (
        ("owner", ws_scenario.owner_client),
        ("editor", ws_scenario.editor_client),
        ("viewer", ws_scenario.viewer_client),
    ):
        resp = helpers.attempt_list_documents(client, ws_id)
        assert resp.status_code == 200, (
            f"{label}(≥VIEWER)는 목록 조회를 통과해야 한다(3.3): "
            f"{resp.status_code} {resp.text}"
        )

    nonmember_denied = helpers.attempt_list_documents(
        ws_scenario.nonmember_client, ws_id
    )
    assert nonmember_denied.status_code == 403, (
        f"비멤버 목록 차단(INV-1, 3.4): "
        f"{nonmember_denied.status_code} {nonmember_denied.text}"
    )


# =============================================================================
# 그룹 3: admin bypass (비멤버 admin 이 6개 연산 전부 성공) — 3.5 (INV-3)
# =============================================================================


def test_admin_bypasses_gate_on_all_six_operations(ws_scenario):
    """비멤버 admin 이 조회·목록·생성·수정·이동·삭제 6개 연산을 모두 통과(3.5, INV-3).

    admin 은 이 워크스페이스의 **멤버가 아니다**(픽스처 보장). 그럼에도 모든 문서 게이트에서 role
    위계 판정을 bypass 하여 접근에 성공한다 — viewer 요구(조회·목록)든 EDITOR 요구(생성·수정·이동·
    삭제)든 무관하다. 각 연산마다 별도 대상 문서를 써서 삭제가 다른 관측을 소진하지 않게 한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    admin = ws_scenario.admin_client

    # (조회) admin 상세 조회 — VIEWER 게이트 bypass.
    doc_get = helpers.create_document(editor, ws_id, _title("admin조회대상"))
    got = helpers.attempt_get_document(admin, doc_get["id"])
    assert got.status_code == 200, (
        f"admin 은 비멤버라도 상세 조회 bypass(INV-3): {got.status_code} {got.text}"
    )

    # (목록) admin 목록 — VIEWER 게이트 bypass.
    listed = helpers.attempt_list_documents(admin, ws_id)
    assert listed.status_code == 200, (
        f"admin 은 비멤버라도 목록 조회 bypass(INV-3): {listed.status_code} {listed.text}"
    )

    # (생성) admin 생성 — EDITOR 게이트 bypass.
    created = helpers.attempt_create_document(admin, ws_id, _title("admin생성"))
    assert created.status_code == 201, (
        f"admin 은 비멤버라도 생성 bypass(INV-3): {created.status_code} {created.text}"
    )

    # (수정) admin 제목 수정 — EDITOR 게이트 bypass.
    doc_patch = helpers.create_document(editor, ws_id, _title("admin수정대상"))
    patched = helpers.attempt_patch_title(admin, doc_patch["id"], _title("admin수정"))
    assert patched.status_code == 200, (
        f"admin 은 비멤버라도 수정 bypass(INV-3): {patched.status_code} {patched.text}"
    )

    # (이동) admin 이동 — EDITOR 게이트 bypass.
    doc_move = helpers.create_document(editor, ws_id, _title("admin이동대상"))
    moved = helpers.attempt_move_document(admin, doc_move["id"])
    assert moved.status_code == 200, (
        f"admin 은 비멤버라도 이동 bypass(INV-3): {moved.status_code} {moved.text}"
    )

    # (삭제) admin 삭제 — EDITOR 게이트 bypass.
    doc_delete = helpers.create_document(editor, ws_id, _title("admin삭제대상"))
    deleted = helpers.attempt_delete_document(admin, doc_delete["id"])
    assert deleted.status_code == 204, (
        f"admin 은 비멤버라도 삭제 bypass(INV-3): {deleted.status_code} {deleted.text}"
    )


# =============================================================================
# 그룹 4: 문서→WS 어댑터 (미존재 404 vs 존재+권한미충족 403) — 3.6
# =============================================================================


def test_adapter_missing_document_maps_to_404_even_for_authorized_owner(ws_scenario):
    """`/documents/{id}` 계열은 미존재 문서를 role 판정에 **앞서** 404 로 낸다(어댑터 매핑 실패, 3.6).

    owner(게이트를 통과할 자격이 있는 fully-authorized 멤버)로 호출해도 문서 자체가 없으면 어댑터가
    workspace_id 매핑에 실패해 403 이 아니라 404 를 반환해야 한다 — 어댑터가 resolver 위계·admin
    bypass 를 재구현하지 않고 s01 resolver 에 위임함을 보인다(존재해야 role 결정에 도달). 상세·수정·
    이동·삭제 네 경로 모두에서 확인한다(생성·목록은 경로 {id}=workspace_id 이므로 이 어댑터 대상이 아님).
    """
    owner = ws_scenario.owner_client
    cases = [
        ("상세", helpers.attempt_get_document(owner, MISSING_DOCUMENT_ID)),
        ("수정", helpers.attempt_patch_title(owner, MISSING_DOCUMENT_ID, _title("없음"))),
        ("이동", helpers.attempt_move_document(owner, MISSING_DOCUMENT_ID)),
        ("삭제", helpers.attempt_delete_document(owner, MISSING_DOCUMENT_ID)),
    ]
    for label, resp in cases:
        assert resp.status_code == 404, (
            f"미존재 문서 {label} 은 authorized owner 에게도 404 여야 한다"
            f"(어댑터 매핑 실패 → role 판정 이전, 3.6): {resp.status_code} {resp.text}"
        )


def test_adapter_existing_document_insufficient_role_maps_to_403(ws_scenario):
    """`/documents/{id}` 계열은 **존재하는** 문서 + 권한 미충족을 403 으로 낸다(어댑터 위임, 3.6).

    미존재 404 와 대비되는 축이다: 문서가 존재하면 어댑터가 workspace_id 매핑에 성공하고 resolver 가
    role 을 판정하므로, viewer 의 변경(EDITOR 미충족)과 비멤버의 조회(VIEWER 미충족)는 404 가 아니라
    403 이다. 어댑터가 판정을 재구현하지 않고 resolver 에 위임함을 미존재-404 와 함께 확정한다.
    """
    ws_id = ws_scenario.workspace_id
    doc = helpers.create_document(ws_scenario.editor_client, ws_id, _title("어댑터403대상"))
    doc_id = doc["id"]

    # 존재 문서 + viewer 변경(EDITOR 미충족) → 403 (404 아님).
    viewer_change = helpers.attempt_patch_title(
        ws_scenario.viewer_client, doc_id, _title("viewer변경")
    )
    assert viewer_change.status_code == 403, (
        f"존재 문서 + viewer 변경(EDITOR 미충족)은 403 이어야 한다(어댑터 위임, 3.6): "
        f"{viewer_change.status_code} {viewer_change.text}"
    )

    # 존재 문서 + 비멤버 조회(VIEWER 미충족) → 403 (404 아님).
    nonmember_read = helpers.attempt_get_document(
        ws_scenario.nonmember_client, doc_id
    )
    assert nonmember_read.status_code == 403, (
        f"존재 문서 + 비멤버 조회(VIEWER 미충족)은 403 이어야 한다(어댑터 위임, 3.6): "
        f"{nonmember_read.status_code} {nonmember_read.text}"
    )
