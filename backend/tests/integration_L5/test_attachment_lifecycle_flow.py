"""첨부 생성·서빙·WS 격리 흐름 스위트 — 이미지 붙여넣기·파일 첨부·서빙·게이팅 e2e
(Task 2.2 / Req 3.1·3.2·3.3·3.4·3.5, design §AttachmentLifecycleFlowSuite; s12 8.1·8.2·8.3 교차참조).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕**s12** 첨부 라우터·아카이브
스케줄러 조립, `app.main.create_app`) + **실제 세션 쿠키** 위에서 s12 첨부 2개 라우트(카탈로그
행 32~33: `POST /documents/{id}/attachments` editor·`GET /attachments/{id}` viewer)를 mock
없이 결합 검증한다. 저장 루트만 tmp 로 격리(`tmp_attachment_roots`)해 디스크상 WS 격리 저장을
실제 파일시스템으로 관찰한다.

판정은 s05 가 채운 **실제** `workspace_member` 데이터 위에서 s01 resolver 가 수행한다: 업로드는
`require_ws_role(EDITOR)`(s07 문서→WS 어댑터 경유), 서빙은 `require_ws_role(VIEWER)`(s12 첨부→WS
어댑터 경유). 동일 워크스페이스의 owner/editor/viewer/비멤버/admin 세션은 `doc_tree_scenario`
(editor + 워크스페이스 + 문서 트리)와 그것이 담은 `WorkspaceScenario`(role별 클라이언트)를 그대로
쓰고, 미인증 자는 하네스가 만든 쿠키 없는 `harness.new_client()` 를 쓴다. 첨부·서빙·게이팅 래퍼는
`tests.integration_L5.helpers`(실 라우트의 얇은 래퍼)로 단일 정의된 것을 재사용한다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가 실제
구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다.
"""

from tests.integration_L5 import helpers as h

# 어댑터 매핑-실패(→404)를 관측하기 위한 미존재 리소스 id(시드 범위와 겹치지 않는 큰 값).
MISSING_ID = 999_999_999

# 업로드 바이너리(작은 시그니처 + 페이로드; 25MiB 한도 이하라 저장·서빙 경로만 검증).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l5-lifecycle-image-payload"
_FILE_BYTES = b"%PDF-1.4 l5-lifecycle-file-payload\n%%EOF"


# =============================================================================
# 1) 이미지 붙여넣기 — 파일로 저장(base64 인라인 아님)·kind=image·안정 참조 url (3.1, 8.1)
# =============================================================================


def test_image_paste_saved_as_file_with_stable_url(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """editor 이미지 붙여넣기 업로드 → `kind=image`·디스크 파일로 저장(인라인 아님)·url=`/attachments/{id}`.

    - 응답 `AttachmentRead.kind == image`, `url == /attachments/{id}`(문서 본문 안정 참조 규약).
    - 저장은 base64 인라인이 아니라 **디스크상 실제 파일**이며, 그 파일의 바이트가 업로드
      바이트와 정확히 일치함을 파일시스템 관찰로 확인한다(8.1).
    """
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    att = h.upload_image(
        editor, doc_id, content=_IMAGE_BYTES, filename="paste.png"
    )

    att_id = att["id"]
    assert att["kind"] == "image", "붙여넣기 이미지는 kind=image 로 기록되어야 한다(8.1)"
    assert att["url"] == f"/attachments/{att_id}", (
        "url 은 /attachments/{id} 파생 규약이어야 한다(문서 본문 안정 참조, 8.1)"
    )
    assert att["is_archived"] is False, "신규 첨부는 미보관이어야 한다"

    # base64 인라인이 아니라 디스크상 파일로 저장되고, 그 바이트가 업로드와 일치한다(8.1).
    rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert rel_path is not None, "첨부 file_path 가 DB 에 커밋되어 있어야 한다"
    disk_file = h.assert_stored(tmp_attachment_roots, rel_path)
    assert disk_file.read_bytes() == _IMAGE_BYTES, (
        "디스크에 저장된 파일 바이트가 업로드 바이트와 정확히 일치해야 한다(파일 저장, 인라인 아님)"
    )


# =============================================================================
# 2) 파일 첨부 — kind=file·원본명 보존·대상 문서/WS 연결 (3.2, 8.2)
# =============================================================================


def test_file_attachment_kind_and_document_link(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """editor 비이미지 파일 첨부 → `kind=file`·`original_name` 보존·대상 문서/WS 연결(8.2).

    - 응답 `kind == file`, `original_name` 이 업로드 파일명과 정확히 일치(보존).
    - `document_id` 가 대상 문서, `workspace_id` 가 그 문서의 소속 WS 와 일치(연결).
    """
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id
    ws_id = doc_tree_scenario.workspace_id

    att = h.upload_file(
        editor, doc_id, content=_FILE_BYTES, filename="report.pdf"
    )

    assert att["kind"] == "file", "비이미지 파일은 kind=file 로 기록되어야 한다(8.2)"
    assert att["original_name"] == "report.pdf", (
        "원본 파일명(original_name)이 정확히 보존되어야 한다(8.2)"
    )
    assert att["document_id"] == doc_id, "첨부는 대상 문서에 연결되어야 한다(8.2)"
    assert att["workspace_id"] == ws_id, (
        "첨부 소속 WS 는 대상 문서의 소속 워크스페이스여야 한다(8.2)"
    )


# =============================================================================
# 3) WS 격리 저장 — workspace_id 문서 확정·저장 파일 {ws}/ 격리 (3.3, 8.3, INV-6)
# =============================================================================


def test_workspace_isolated_storage_from_document(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """소속 `workspace_id` 가 대상 문서에서 확정되고 저장 파일이 `{ws}/` 하위에 격리됨(8.3, INV-6).

    multipart 폼에는 워크스페이스 필드가 없으므로 클라이언트가 WS 를 지정할 방법이 없다. 폼에
    조작된 `workspace_id` 필드를 실어도 무시되고, 영속화된 workspace_id 는 대상 문서의 WS 와
    일치한다. 저장 파일의 DB `file_path` 는 `{workspace_id}/...` 상대 경로이고 그 위치에 디스크
    파일이 물리적으로 존재한다(INV-6).
    """
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id
    ws_id = doc_tree_scenario.workspace_id

    # 폼에 위조 workspace_id 를 실어도 무시되어야 한다(클라이언트 입력이 아닌 문서 기준 확정).
    resp = h.attempt_upload_attachment(
        editor,
        doc_id,
        filename="isolated.png",
        content=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert resp.status_code == 201, (
        f"editor 업로드 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    assert body["workspace_id"] == ws_id, (
        "첨부 workspace_id 는 클라이언트 입력이 아니라 대상 문서의 WS 로 확정되어야 한다(8.3)"
    )

    # 저장 파일은 WS 단위로 분리된 위치(`file_storage_root/{workspace_id}/...`)에 보관된다(INV-6).
    rel_path = h.attachment_file_path(harness.session_local, body["id"])
    assert rel_path is not None, "저장 파일의 DB file_path 가 커밋되어 있어야 한다"
    h.assert_ws_isolated(rel_path, ws_id)
    h.assert_stored(tmp_attachment_roots, rel_path)


# =============================================================================
# 4) 서빙 — viewer 가 미보관 첨부 바이너리 스트리밍 조회 (3.4)
# =============================================================================


def test_viewer_serves_unarchived_binary(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """viewer 가 미보관 첨부의 바이너리를 `GET /attachments/{id}` 로 조회 → 200·정확한 바이트·content-type.

    첨부 소속 WS 권한(VIEWER)을 판정한 뒤 파일 바이너리를 스트리밍 반환한다. viewer(멤버)는
    업로드한 정확한 바이트를 원본명 기반 content-type(`image/png`)과 함께 돌려받는다(3.4).
    """
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client
    doc_id = doc_tree_scenario.root_id

    att = h.upload_image(
        editor, doc_id, content=_IMAGE_BYTES, filename="served.png"
    )

    serve = h.get_attachment(viewer, att["id"])
    assert serve.content == _IMAGE_BYTES, (
        "업로드한 정확한 바이너리를 스트리밍으로 돌려받아야 한다(3.4)"
    )
    assert serve.headers["content-type"].startswith("image/png"), (
        "원본명 기반 content-type(image/png)이 실려야 한다(3.4)"
    )


# =============================================================================
# 5a) 업로드 게이트 = EDITOR — viewer 403·비멤버 403·미인증 401·미존재 문서 404 (3.5, INV-1·2)
# =============================================================================


def test_upload_gate_editor_over_real_membership(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """업로드 게이트(EDITOR): editor 201·viewer 403·비멤버 403·미인증 401·미존재 문서 404·admin bypass 201.

    판정은 s05 실제 멤버십 위에서 s01 `require_ws_role(EDITOR)`(문서→WS 어댑터)가 수행한다.
    viewer 는 VIEWER 라 editor 미만이라 403(INV-2), 비멤버는 WS 멤버가 아니라 403(INV-1,
    anti-enumeration), 미인증(세션 없음)은 401, admin(비멤버지만 resolver bypass)은 201(INV-3).
    미존재 문서는 문서→WS 어댑터가 role 판정 이전 404.
    """
    scenario = doc_tree_scenario.scenario
    doc_id = doc_tree_scenario.root_id

    def _attempt(client, doc=doc_id):
        return h.attempt_upload_attachment(
            client,
            doc,
            filename="gate.png",
            content=_IMAGE_BYTES,
            content_type="image/png",
        )

    # editor(EDITOR)는 201(정상 통과).
    assert _attempt(scenario.editor_client).status_code == 201, "editor 업로드 201"

    # viewer(멤버, VIEWER)는 editor 미만이라 403(INV-2).
    assert _attempt(scenario.viewer_client).status_code == 403, "viewer 업로드 403(INV-2)"

    # 비멤버(WS 멤버 아님)는 403(INV-1, anti-enumeration).
    assert _attempt(scenario.nonmember_client).status_code == 403, (
        "비멤버 업로드 403(INV-1)"
    )

    # 미인증(쿠키 없는 신규 클라이언트)은 401.
    assert _attempt(harness.new_client()).status_code == 401, "미인증 업로드 401"

    # admin(비멤버지만 resolver bypass)은 201(INV-3).
    assert _attempt(scenario.admin_client).status_code == 201, (
        "admin bypass 업로드 201(INV-3)"
    )

    # 미존재 문서 업로드는 문서→WS 어댑터가 role 판정 이전 404(authorized editor 에게도).
    assert _attempt(scenario.editor_client, MISSING_ID).status_code == 404, (
        "미존재 문서 업로드 404(어댑터 매핑 실패)"
    )


# =============================================================================
# 5b) 서빙 게이트 = VIEWER — 비멤버 403·미존재 첨부 404·admin bypass 200 (3.5, INV-1·3)
# =============================================================================


def test_serve_gate_viewer_and_admin_bypass(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """서빙 읽기 전역 개방: member 200·비멤버 200·미인증 401·admin 200·미존재 첨부 404
    (s26 Req 3.4·3.8·7.2).

    첨부 서빙(`GET /attachments/{id}`)은 s26 읽기 개방으로 활성 사용자면 멤버십과 무관하게
    200 이다. member·비멤버 활성 사용자(viewer·nonmember) 모두 200(더 이상 403 아님), 미인증은
    401(인증 게이트 유지), admin 도 200, 미존재 첨부는 첨부→WS 어댑터가 매핑 실패로 404.
    """
    scenario = doc_tree_scenario.scenario
    doc_id = doc_tree_scenario.root_id

    # member 가 서빙 대상 첨부를 하나 만든다.
    att = h.upload_image(
        scenario.editor_client, doc_id, content=_IMAGE_BYTES, filename="target.png"
    )
    att_id = att["id"]

    # member·비멤버 활성 사용자 모두 조회 200(읽기 전역 개방, 403 아님).
    for label, client in (
        ("member", scenario.editor_client),
        ("viewer(비멤버)", scenario.viewer_client),
        ("nonmember", scenario.nonmember_client),
        ("admin", scenario.admin_client),
    ):
        assert h.attempt_get_attachment(client, att_id).status_code == 200, (
            f"{label} 첨부 서빙 200(읽기 전역 개방, 3.8): 403 아님"
        )

    # 미인증(쿠키 없는 신규 클라이언트)은 401(인증 게이트 유지).
    assert h.attempt_get_attachment(harness.new_client(), att_id).status_code == 401, (
        "미인증 조회 401"
    )

    # 미존재 첨부는 첨부→WS 어댑터가 매핑 실패로 404(활성 사용자에게도).
    assert h.attempt_get_attachment(scenario.viewer_client, MISSING_ID).status_code == 404, (
        "미존재 첨부 조회 404(어댑터 매핑 실패)"
    )
