"""문서 코어 CRUD·계층·권한 게이팅 통합 스위트 (Task 5.1 / Req 1.1·1.3·1.4·1.6·1.7,
2.1·2.4·2.6, 3.1·3.2, 4.1·4.6, 10.1·10.2·10.3·10.5·10.6·10.7).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕**s07**) + 실 세션 위에서 문서 6개 엔드포인트
(s01 카탈로그 행 18~23)를 mock 없이 e2e 로 관찰한다. `ws_scenario` 픽스처(L2 conftest)가
role별 독립 세션 클라이언트와 구성된 워크스페이스를 제공하고, 각 테스트는 함수 스코프로
독립된 워크스페이스를 받으므로 테스트 간 상태 간섭이 없다. 게이트가 오작동하면 단언을
약화시키지 않고 실제 회귀(s07/s01/s05 원인)를 그대로 표면화한다.

네 개의 관찰 그룹(task 5.1):
- **구조 왕복(editor)**: 루트→하위 생성→조회 시 content·content_html 포함→제목 수정(본문·버전
  필드 불변)→이동(재부모)·재정렬(형제 사이 중간값)→목록 `Page[DocumentRead]`.
- **권한 게이팅(INV-1·2·3)**: 변경(생성·수정·이동·삭제)은 viewer 403·editor 통과·admin
  bypass(비멤버), 조회는 viewer 통과. 비멤버는 전부 403. 문서 권한이 WS 단위 resolver 로만
  게이팅됨(문서별 개별 권한 없음: viewer 는 WS 내 임의 문서 조회, editor 는 임의 문서 변경).
- **어댑터 게이팅 + 404**: `/documents/{id}` 계열이 문서→WS 어댑터로 게이팅되며 미존재 문서는
  role 판정에 앞서 404.
- **계약 정합**: 성공 본문이 `DocumentRead`·`Page[DocumentRead]` 형태, 오류 본문이 s01
  `ErrorResponse`(code·message·field_errors?) 형태, 그리고 s07 이 새 마이그레이션을 추가하지
  않고 s01 초기 스키마(0001) 위에서만 문서를 제공함(10.6).

로컬 헬퍼(`_create_doc`/`_make_doc`/`_assert_document_read_shape`/`_assert_error_response_shape`)
는 이 파일에 자족적으로 정의한다(공유 L2 하네스·helpers 미변경). 공유 `notion_lite_test` DB
오염을 피하려 제목에 고유 접미사를 붙인다.
"""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# s01 `DocumentRead`(TimestampedRead 상속) 가 노출해야 하는 전체 필드 집합(계약 형태 대조용).
DOCUMENT_READ_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "workspace_id",
    "parent_id",
    "title",
    "status",
    "sort_order",
    "current_version_id",
    "created_by",
    "content",
    "content_html",
}

# 인증되었으나(멤버 자격 무관) 대상이 존재하지 않을 때 어댑터 404 를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999


def _title(prefix: str) -> str:
    """공유 테스트 DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _create_doc(client, workspace_id, title, parent_id=None):
    """``POST /workspaces/{id}/documents`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 스타일 로컬 헬퍼 — 성공(201)과 거부(403/404/422)를 같은 래퍼로 단언한다.
    """
    body = {"title": title}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return client.post(f"/workspaces/{workspace_id}/documents", json=body)


def _make_doc(client, workspace_id, title, parent_id=None):
    """문서를 만들고 201 을 단언한 뒤 파싱된 `DocumentRead` dict 를 반환한다(SETUP 헬퍼)."""
    resp = _create_doc(client, workspace_id, title, parent_id)
    assert resp.status_code == 201, (
        f"문서 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _assert_document_read_shape(body) -> None:
    """관측된 성공 본문이 s01 `DocumentRead` 형태(전체 필드 존재)를 따르는지 강제한다(10.1)."""
    assert isinstance(body, dict), f"DocumentRead 본문은 JSON 객체여야 한다: {body!r}"
    missing = DOCUMENT_READ_FIELDS - set(body)
    assert not missing, (
        f"DocumentRead 본문에 계약 필드 누락: {sorted(missing)} (keys={sorted(body)})"
    )


def _assert_error_response_shape(body) -> None:
    """관측된 오류 본문이 s01 `ErrorResponse` 형태를 따르는지 강제한다(10.2).

    최소 계약(s01 §Errors): 문자열 ``code``·``message`` 를 가지며, ``field_errors`` 가
    존재하면 리스트다(``{code, message, field_errors?}``).
    """
    assert isinstance(body, dict), f"에러 본문은 JSON 객체여야 한다: {body!r}"
    assert isinstance(body.get("code"), str), f"code 는 문자열이어야 한다: {body!r}"
    assert isinstance(body.get("message"), str), f"message 는 문자열이어야 한다: {body!r}"
    if body.get("field_errors") is not None:
        assert isinstance(body["field_errors"], list), (
            f"field_errors 가 존재하면 리스트여야 한다: {body!r}"
        )


# --- 그룹 1: 구조 왕복 (editor) — Req 1.1·1.2·2.1·2.4·3.1·4.1 ------------------------


def test_structure_roundtrip_create_read_patch_move(ws_scenario):
    """루트·하위 생성→조회(content·content_html 포함)→제목 수정→재부모 이동 왕복(editor).

    (1) 루트 문서 생성 시 status=active·created_by=요청자·parent_id=None·current_version_id=None
    (초기 버전 미생성), content=""·content_html 은 빈 본문의 안전 렌더 문자열(2.3). (2) 부모를
    지정한 하위 문서 생성 시 parent_id 가 루트를 가리킨다(1.2). (3) `GET /documents/{id}` 가
    content·content_html 을 포함해 반환한다(2.1·2.4). (4) `PATCH` 로 제목만 갱신되고 본문·버전
    필드(content·current_version_id)는 불변이다(3.1·3.4). (5) `POST /move` 재부모 시 parent_id 가
    갱신된다(4.1).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    # (1) 루트 생성.
    root = _make_doc(editor, ws_id, _title("루트"))
    assert root["workspace_id"] == ws_id
    assert root["parent_id"] is None
    assert root["status"] == "active", f"신규 문서는 active 여야 한다: {root!r}"
    assert root["created_by"] == ws_scenario.editor_user_id, (
        f"created_by 는 요청자여야 한다: {root!r}"
    )
    assert root["current_version_id"] is None, (
        f"생성은 초기 버전을 만들지 않으므로 current_version_id 는 None: {root!r}"
    )
    assert root["content"] == "", f"현재 버전 부재 문서의 content 는 빈 문자열: {root!r}"
    assert isinstance(root["content_html"], str), (
        f"content_html 은 빈 본문의 안전 렌더 문자열이어야 한다: {root!r}"
    )

    # (2) 하위 문서 생성.
    child = _make_doc(editor, ws_id, _title("하위"), parent_id=root["id"])
    assert child["parent_id"] == root["id"], f"하위 문서의 parent_id 는 루트 id: {child!r}"
    assert child["workspace_id"] == ws_id
    assert child["status"] == "active"

    # (3) 조회 — content·content_html 포함.
    got = editor.get(f"/documents/{child['id']}")
    assert got.status_code == 200, f"{got.status_code} {got.text}"
    got_body = got.json()
    _assert_document_read_shape(got_body)
    assert got_body["content"] == ""
    assert isinstance(got_body["content_html"], str)
    assert got_body["parent_id"] == root["id"]

    # (4) 제목 수정 — 본문·버전 필드 불변.
    new_title = _title("수정된하위")
    patched = editor.patch(f"/documents/{child['id']}", json={"title": new_title})
    assert patched.status_code == 200, f"{patched.status_code} {patched.text}"
    patched_body = patched.json()
    assert patched_body["title"] == new_title, f"제목이 갱신되어야 한다: {patched_body!r}"
    assert patched_body["current_version_id"] is None, (
        f"제목 수정은 본문/버전을 건드리지 않는다(3.4): {patched_body!r}"
    )
    assert patched_body["content"] == "", (
        f"제목 수정은 content 를 바꾸지 않는다: {patched_body!r}"
    )

    # (5) 재부모 이동 — child 를 루트로 올린다(parent_id=None).
    moved = editor.post(f"/documents/{child['id']}/move", json={"new_parent_id": None})
    assert moved.status_code == 200, f"{moved.status_code} {moved.text}"
    moved_body = moved.json()
    assert moved_body["parent_id"] is None, (
        f"루트로 이동하면 parent_id 는 None: {moved_body!r}"
    )


def test_reorder_between_siblings_assigns_midpoint_sort_order(ws_scenario):
    """형제 사이 재정렬 시 다른 형제 재배치 없이 두 이웃 사이 중간값 sort_order 가 부여됨(4.1·4.5).

    루트에 A·B·C 를 순서대로 생성하면 sort_order 가 오름차순(A<B<C)이다. C 를
    after_sibling_id=A·before_sibling_id=B 로 이동하면 A·B 사이(중간값)로 삽입되어
    A.sort_order < C.sort_order < B.sort_order 가 성립해야 한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    a = _make_doc(editor, ws_id, _title("A"))
    b = _make_doc(editor, ws_id, _title("B"))
    c = _make_doc(editor, ws_id, _title("C"))

    a_order = Decimal(str(a["sort_order"]))
    b_order = Decimal(str(b["sort_order"]))
    assert a_order < b_order, f"순차 생성 형제는 오름차순 sort_order 여야 한다: {a_order} {b_order}"

    resp = editor.post(
        f"/documents/{c['id']}/move",
        json={"after_sibling_id": a["id"], "before_sibling_id": b["id"]},
    )
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    c_order = Decimal(str(resp.json()["sort_order"]))
    assert a_order < c_order < b_order, (
        f"재정렬된 문서는 두 이웃 사이 중간값이어야 한다: "
        f"A={a_order} C={c_order} B={b_order}"
    )


def test_list_returns_active_documents_as_page(ws_scenario):
    """목록은 WS 의 active 문서를 `Page[DocumentRead]`(items 리스트 + total int)로 반환(2.1).

    editor 로 두 문서를 만든 뒤 viewer 로 목록을 조회해 Page 엔벨로프 형태와 각 item 의
    DocumentRead 형태를 확인한다(조회 게이트는 viewer 통과).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    _make_doc(editor, ws_id, _title("목록1"))
    _make_doc(editor, ws_id, _title("목록2"))

    resp = ws_scenario.viewer_client.get(f"/workspaces/{ws_id}/documents")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    page = resp.json()
    assert isinstance(page, dict), f"목록 본문은 Page 엔벨로프여야 한다: {page!r}"
    assert isinstance(page.get("items"), list), f"Page.items 는 리스트: {page!r}"
    assert isinstance(page.get("total"), int), f"Page.total 는 정수: {page!r}"
    assert page["total"] >= 2, f"생성한 active 문서가 total 에 반영되어야 한다: {page!r}"
    for item in page["items"]:
        _assert_document_read_shape(item)


# --- 그룹 2: 권한 게이팅 (INV-1·2·3) — Req 1.6·1.7·2.6·3.2·4.6·10.3 -----------------


def test_create_gate_viewer_denied_editor_and_admin_allowed(ws_scenario):
    """생성 게이트(EDITOR): viewer 403·editor 201·admin bypass 201(비멤버, INV-1·2·3)."""
    ws_id = ws_scenario.workspace_id

    denied = _create_doc(ws_scenario.viewer_client, ws_id, _title("viewer생성"))
    assert denied.status_code == 403, (
        f"viewer 는 생성 EDITOR 게이트에서 403(INV-2): {denied.status_code} {denied.text}"
    )

    allowed = _create_doc(ws_scenario.editor_client, ws_id, _title("editor생성"))
    assert allowed.status_code == 201, (
        f"editor 는 생성 게이트 통과 201: {allowed.status_code} {allowed.text}"
    )

    bypass = _create_doc(ws_scenario.admin_client, ws_id, _title("admin생성"))
    assert bypass.status_code == 201, (
        f"admin 은 비멤버라도 bypass 로 생성 201 이어야 한다(INV-3): "
        f"{bypass.status_code} {bypass.text}"
    )


def test_patch_gate_viewer_denied_editor_and_admin_allowed(ws_scenario):
    """수정 게이트(EDITOR): viewer 403·editor 200·admin bypass 200(INV-1·2·3)."""
    ws_id = ws_scenario.workspace_id
    doc = _make_doc(ws_scenario.editor_client, ws_id, _title("수정대상"))

    denied = ws_scenario.viewer_client.patch(
        f"/documents/{doc['id']}", json={"title": _title("viewer수정")}
    )
    assert denied.status_code == 403, (
        f"viewer 는 수정 게이트에서 403: {denied.status_code} {denied.text}"
    )

    allowed = ws_scenario.editor_client.patch(
        f"/documents/{doc['id']}", json={"title": _title("editor수정")}
    )
    assert allowed.status_code == 200, (
        f"editor 는 수정 게이트 통과 200: {allowed.status_code} {allowed.text}"
    )

    bypass = ws_scenario.admin_client.patch(
        f"/documents/{doc['id']}", json={"title": _title("admin수정")}
    )
    assert bypass.status_code == 200, (
        f"admin 은 bypass 로 수정 200 이어야 한다(INV-3): {bypass.status_code} {bypass.text}"
    )


def test_move_gate_viewer_denied_editor_and_admin_allowed(ws_scenario):
    """이동 게이트(EDITOR): viewer 403·editor 200·admin bypass 200(INV-1·2·3).

    빈 이동 본문(형제 참조 없음)은 루트 append 로 200 이 되도록 성공 케이스를 구성한다.
    """
    ws_id = ws_scenario.workspace_id
    doc = _make_doc(ws_scenario.editor_client, ws_id, _title("이동대상"))

    denied = ws_scenario.viewer_client.post(f"/documents/{doc['id']}/move", json={})
    assert denied.status_code == 403, (
        f"viewer 는 이동 게이트에서 403: {denied.status_code} {denied.text}"
    )

    allowed = ws_scenario.editor_client.post(f"/documents/{doc['id']}/move", json={})
    assert allowed.status_code == 200, (
        f"editor 는 이동 게이트 통과 200: {allowed.status_code} {allowed.text}"
    )

    bypass = ws_scenario.admin_client.post(f"/documents/{doc['id']}/move", json={})
    assert bypass.status_code == 200, (
        f"admin 은 bypass 로 이동 200 이어야 한다(INV-3): {bypass.status_code} {bypass.text}"
    )


def test_delete_gate_viewer_denied_editor_and_admin_allowed(ws_scenario):
    """삭제 게이트(EDITOR): viewer 403·editor 204·admin bypass 204(INV-1·2·3).

    삭제는 파괴적이므로 성공 액터마다 별도 문서를 만든다. viewer 거부는 그 문서가 아직 active
    인 상태에서 관측한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    doc_for_viewer = _make_doc(editor, ws_id, _title("viewer삭제대상"))
    denied = ws_scenario.viewer_client.delete(f"/documents/{doc_for_viewer['id']}")
    assert denied.status_code == 403, (
        f"viewer 는 삭제 게이트에서 403: {denied.status_code} {denied.text}"
    )

    doc_for_editor = _make_doc(editor, ws_id, _title("editor삭제대상"))
    allowed = editor.delete(f"/documents/{doc_for_editor['id']}")
    assert allowed.status_code == 204, (
        f"editor 는 삭제 게이트 통과 204: {allowed.status_code} {allowed.text}"
    )

    doc_for_admin = _make_doc(editor, ws_id, _title("admin삭제대상"))
    bypass = ws_scenario.admin_client.delete(f"/documents/{doc_for_admin['id']}")
    assert bypass.status_code == 204, (
        f"admin 은 bypass 로 삭제 204 이어야 한다(INV-3): {bypass.status_code} {bypass.text}"
    )


def test_read_gate_allows_viewer(ws_scenario):
    """조회 게이트(VIEWER): viewer 가 상세·목록을 모두 200 으로 통과(2.1·2.6)."""
    ws_id = ws_scenario.workspace_id
    doc = _make_doc(ws_scenario.editor_client, ws_id, _title("조회대상"))

    detail = ws_scenario.viewer_client.get(f"/documents/{doc['id']}")
    assert detail.status_code == 200, (
        f"viewer 는 상세 조회를 통과해야 한다: {detail.status_code} {detail.text}"
    )

    listing = ws_scenario.viewer_client.get(f"/workspaces/{ws_id}/documents")
    assert listing.status_code == 200, (
        f"viewer 는 목록 조회를 통과해야 한다: {listing.status_code} {listing.text}"
    )


def test_nonmember_reads_open_but_edits_denied(ws_scenario):
    """비멤버 활성 사용자: 읽기(목록·상세)는 200(전역 개방), 편집(생성·수정·이동·삭제)은 403.

    s26 읽기 전역 개방(Req 3.8·7.2)으로 비멤버도 목록·상세 조회는 200 이다(더 이상 403 아님 —
    헤드라인 전환). 반면 편집 계열은 멤버십을 요구하므로 비멤버(admin 제외)는 403 으로 거부된다
    (Req 4.6). 비멤버는 인증된 사용자이므로 401 이 아니라 403 이고, `/documents/{id}` 계열은
    문서가 존재하므로 404 가 아니라 403 이다.
    """
    ws_id = ws_scenario.workspace_id
    nonmember = ws_scenario.nonmember_client
    doc = _make_doc(ws_scenario.editor_client, ws_id, _title("비멤버대상"))

    # 읽기 전역 개방: 비멤버 목록·상세 조회 → 200(403 아님).
    read_cases = [
        ("목록", nonmember.get(f"/workspaces/{ws_id}/documents")),
        ("상세", nonmember.get(f"/documents/{doc['id']}")),
    ]
    for label, resp in read_cases:
        assert resp.status_code == 200, (
            f"비멤버 {label} 읽기는 전역 개방으로 200 이어야 한다(403 아님, Req 3.8): "
            f"{resp.status_code} {resp.text}"
        )

    # 편집 계열: 비멤버(admin 제외) 생성·수정·이동·삭제 → 403(멤버십 요구, Req 4.6).
    edit_cases = [
        ("생성", nonmember.post(
            f"/workspaces/{ws_id}/documents", json={"title": _title("비멤버생성")})),
        ("수정", nonmember.patch(
            f"/documents/{doc['id']}", json={"title": _title("비멤버수정")})),
        ("이동", nonmember.post(f"/documents/{doc['id']}/move", json={})),
        ("삭제", nonmember.delete(f"/documents/{doc['id']}")),
    ]
    for label, resp in edit_cases:
        assert resp.status_code == 403, (
            f"비멤버 {label} 편집은 403 이어야 한다(멤버십 요구, Req 4.6): "
            f"{resp.status_code} {resp.text}"
        )


def test_authz_is_workspace_level_not_per_document(ws_scenario):
    """문서 권한은 WS 단위 resolver 로만 게이팅됨(문서별 개별 권한 없음, INV-1·10.3).

    owner 가 만든 문서를 editor(작성자 아님)가 수정할 수 있고, viewer 가 owner·editor 두
    작성자의 문서를 모두 조회할 수 있음을 보여, 권한이 문서 소유가 아니라 WS role 로만
    결정됨을 증명한다.
    """
    ws_id = ws_scenario.workspace_id

    doc_by_owner = _make_doc(ws_scenario.owner_client, ws_id, _title("오너문서"))
    doc_by_editor = _make_doc(ws_scenario.editor_client, ws_id, _title("에디터문서"))

    # editor 는 자신이 만들지 않은 owner 의 문서도 수정할 수 있다(WS editor 권한만으로).
    edited = ws_scenario.editor_client.patch(
        f"/documents/{doc_by_owner['id']}", json={"title": _title("에디터가수정")}
    )
    assert edited.status_code == 200, (
        f"editor 는 WS 내 임의 문서를 수정할 수 있어야 한다(문서별 권한 없음): "
        f"{edited.status_code} {edited.text}"
    )

    # viewer 는 작성자와 무관하게 WS 내 임의 문서를 조회할 수 있다.
    for label, doc in (("오너문서", doc_by_owner), ("에디터문서", doc_by_editor)):
        resp = ws_scenario.viewer_client.get(f"/documents/{doc['id']}")
        assert resp.status_code == 200, (
            f"viewer 는 WS 내 {label} 를 조회할 수 있어야 한다: "
            f"{resp.status_code} {resp.text}"
        )


# --- 그룹 3: 어댑터 게이팅 + 404 — Req 2.7·10.3·10.4 --------------------------------


def test_missing_document_maps_to_404_before_role(ws_scenario):
    """`/documents/{id}` 계열이 미존재 문서에 대해 role 판정에 앞서 404 를 낸다(어댑터 매핑 실패).

    owner(게이트를 통과할 자격이 있는 인증 멤버)로 호출해도 문서 자체가 없으면 어댑터가
    workspace_id 매핑에 실패해 403 이 아니라 404 를 반환해야 한다. 조회 상세·수정·이동·삭제
    네 경로 모두에서 확인한다. (생성/목록은 경로 {id}=workspace_id 이므로 이 어댑터 대상이
    아니다.)
    """
    owner = ws_scenario.owner_client
    cases = [
        ("상세", owner.get(f"/documents/{MISSING_DOCUMENT_ID}")),
        ("수정", owner.patch(
            f"/documents/{MISSING_DOCUMENT_ID}", json={"title": _title("없음")})),
        ("이동", owner.post(f"/documents/{MISSING_DOCUMENT_ID}/move", json={})),
        ("삭제", owner.delete(f"/documents/{MISSING_DOCUMENT_ID}")),
    ]
    for label, resp in cases:
        assert resp.status_code == 404, (
            f"미존재 문서 {label} 은 404 여야 한다(어댑터 매핑 실패): "
            f"{resp.status_code} {resp.text}"
        )
        _assert_error_response_shape(resp.json())


# --- 그룹 4: 계약 정합 — Req 10.1·10.2·10.6 ----------------------------------------


def test_success_bodies_conform_to_document_read_and_page(ws_scenario):
    """성공 본문이 `DocumentRead`·`Page[DocumentRead]` 형태를 따른다(10.1).

    생성(201)·상세(200) 본문이 DocumentRead 전체 필드를 갖고, 목록(200) 본문이 Page 엔벨로프
    (items 리스트 + total int)이며 각 item 이 DocumentRead 형태임을 대조한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    created = _create_doc(editor, ws_id, _title("계약생성"))
    assert created.status_code == 201, f"{created.status_code} {created.text}"
    _assert_document_read_shape(created.json())

    doc_id = created.json()["id"]
    detail = editor.get(f"/documents/{doc_id}")
    assert detail.status_code == 200, f"{detail.status_code} {detail.text}"
    _assert_document_read_shape(detail.json())

    listing = editor.get(f"/workspaces/{ws_id}/documents")
    assert listing.status_code == 200, f"{listing.status_code} {listing.text}"
    page = listing.json()
    assert isinstance(page.get("items"), list) and isinstance(page.get("total"), int), (
        f"목록은 Page[DocumentRead] 형태여야 한다: {page!r}"
    )
    assert page["items"], "생성한 문서가 목록 items 에 있어야 한다"
    for item in page["items"]:
        _assert_document_read_shape(item)


def test_blank_title_returns_422_error_response(ws_scenario):
    """공백 전용 제목 생성 → 422 + code=validation_error + 비어있지 않은 field_errors(10.2).

    editor(게이트 통과)로 공백 제목을 보내 스키마 검증 실패가 s01 전역 핸들러를 거쳐 공통
    `ErrorResponse` 형태의 422 로 직렬화됨을 확인한다(게이트가 아니라 검증 경로).
    """
    ws_id = ws_scenario.workspace_id
    resp = ws_scenario.editor_client.post(
        f"/workspaces/{ws_id}/documents", json={"title": "   "}
    )
    assert resp.status_code == 422, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "validation_error", (
        f"스키마 검증 실패는 code=validation_error 여야 한다: {body!r}"
    )
    assert isinstance(body.get("field_errors"), list) and body["field_errors"], (
        f"검증 오류는 비어있지 않은 field_errors 를 포함해야 한다: {body!r}"
    )


def test_forbidden_body_conforms_to_error_response(ws_scenario):
    """viewer 의 생성 거부(403) 본문이 s01 `ErrorResponse` 형태이며 code=forbidden(10.2)."""
    ws_id = ws_scenario.workspace_id
    resp = _create_doc(ws_scenario.viewer_client, ws_id, _title("거부"))
    assert resp.status_code == 403, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "forbidden", f"403 은 code=forbidden 여야 한다: {body!r}"


def test_documents_served_on_s01_initial_schema_no_new_migration():
    """s07 이 새 마이그레이션 없이 s01 초기 리비전(0001)만으로 문서를 제공함을 확인(10.6).

    `migrations/versions/` 에 리비전 파일이 정확히 하나(`0001_initial_schema.py`)뿐임을
    단언한다 — s01 워크스페이스 스위트(`test_no_additional_s05_migration`)와 동일한 구체·
    비-flaky 판정을 재사용한다. document·document_version 테이블은 이 단일 리비전이 유일한
    출처이며, s07 은 스키마 형태를 신설하지 않고 그 위에서 동작한다.
    """
    backend_dir = Path(__file__).resolve().parents[2]  # integration_L2 -> tests -> backend
    versions_dir = backend_dir / "migrations" / "versions"

    revision_files = sorted(
        p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    # s01 baseline(0001) + additive user_setting(0002·0003) + s26 open-access-roles(0004).
    # s07 이 자기 마이그레이션을 추가하지 않았음을 검증하는 것이 목적이므로 이후 spec 의
    # 정당한 마이그레이션(user_setting additive·s26 role 2단계화)은 허용한다.
    assert revision_files == [
        "0001_initial_schema.py",
        "0002_user_setting.py",
        "0003_user_setting_last_selected_workspace.py",
        "0004_open_access_roles.py",
    ], (
        "s07 은 새 마이그레이션을 추가하지 않고 s01 baseline(0001) + additive user_setting + "
        f"s26 open-access-roles 위에서 문서를 제공해야 한다(10.6): 관측 리비전 파일={revision_files}"
    )
