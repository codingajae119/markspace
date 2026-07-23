"""첨부 업로드·서빙·권한 게이팅 통합 테스트
(Task 4.1 / Req 1.1, 1.3, 2.1, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 7.1, 7.2).

design.md §Testing Strategy "Integration Tests(첨부 업로드·서빙 왕복)"·"Contract/Boundary
Tests"·§Security Considerations 를 **마이그레이션된 실제 DB + 부팅 앱**(첨부 라우터 조립,
`app.main.create_app`) 위에서 검증한다. mock 없이 s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12 를
결합한 L3 하네스(`tests/attachment/conftest.py` 재-import)를 쓰며, 저장 루트만 tmp 로 격리해
디스크상 워크스페이스 격리 저장을 실제로 관찰한다(``tmp_attachment_roots``).

세 시나리오 그룹을 모두 실제 앱 컨텍스트에서 통과시킨다:

1. **왕복 + WS 격리(Req 1.1·2.1·3.1·3.2)**: editor 가 `POST /documents/{id}/attachments` 로
   이미지·파일을 업로드→응답 url(`/attachments/{id}`)로 viewer 가 `GET /attachments/{id}` 하면
   업로드한 **정확한 바이너리**를 content-type 과 함께 돌려받고, 저장 파일이
   `{file_storage_root}/{workspace_id}/...` 격리 위치(DB `file_path` + 디스크 파일)에 존재한다.
2. **권한 게이팅(Req 2.3·2.4·3.3·3.4·3.5·3.6, INV-1·2·3)**: 업로드는 viewer 403·비멤버 403·
   비인증 401·editor 201·admin(비멤버) bypass 201·미존재 문서 404. 조회는 viewer(멤버) 200·
   비멤버 403·비인증 401·admin bypass 200·미존재 첨부 404. 첨부 권한은 WS 단위 resolver 로만
   게이팅되며(문서·첨부별 개별 권한 없음, Req 3.5) 이를 viewer 가 WS 내 임의 첨부를 서빙함으로
   보인다.
3. **위조 불가 + 계약 형태(Req 3.2·7.1·7.2)**: 첨부 workspace_id 는 multipart 폼에 워크스페이스
   필드가 없고 **대상 문서에서 확정**되므로 클라이언트가 위조할 수 없다(persisted workspace_id ==
   문서의 workspace). 성공 응답은 `AttachmentRead` 규약으로, 오류 응답은 s01 `ErrorResponse`
   규약(code·message)으로 직렬화된다.

DB 관찰은 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로 커밋된 행을 신규 세션에서
직접 조회한다(캐시 아님). 공유 `notion_lite_test` DB 오염 방지를 위해 문서·사용자는 하네스가
uuid4 접미사로 시드한다.
"""

from datetime import datetime
from urllib.parse import quote

from app.attachment.schemas import AttachmentKind, AttachmentRead
from app.models import Attachment, Document

# 업로드 바이너리(작은 PNG 시그니처 + 페이로드; 25MiB 한도 이하라 저장 경로만 검증).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-integration-roundtrip-image-payload"
_FILE_BYTES = b"%PDF-1.4 integration-roundtrip-file-payload\n%%EOF"

# 존재하지 않는 리소스 id(어댑터 404 관찰용; 시드 범위와 겹치지 않는 큰 값).
_MISSING_ID = 99_999_999


def _upload(client, document_id, *, filename, data, content_type, kind=None):
    """``POST /documents/{id}/attachments`` multipart 업로드를 태우고 응답을 그대로 반환한다.

    파일 필드명은 계약상 ``file`` 이며, tuple 의 content-type 이 라우터의 kind 추론을 구동한다
    (image/* → image, 그 외 → file). ``kind`` 를 주면 Form 필드로 실어 추론보다 우선시킨다.
    상태는 호출자가 단언한다(성공·게이팅 음성 경로를 같은 래퍼로 관찰).
    """
    files = {"file": (filename, data, content_type)}
    form = {"kind": kind} if kind is not None else None
    return client.post(
        f"/documents/{document_id}/attachments", files=files, data=form
    )


# =============================================================================
# (1) 왕복 + 워크스페이스 격리 저장
# =============================================================================


def test_editor_uploads_image_round_trip_and_ws_isolated_storage(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """editor 이미지 업로드→viewer 조회 왕복 + WS 격리 저장을 실제 앱에서 검증한다
    (Req 1.1·1.3·2.1·3.1·3.2).

    - 업로드 201 + `AttachmentRead`(url=`/attachments/{id}`, kind=image, 원본명 보존,
      is_archived=false).
    - 응답 url 로 viewer 가 GET → 200 + **정확한 업로드 바이너리** + image/png content-type.
    - DB `file_path` 가 `{workspace_id}/...` 로 격리되고 디스크 파일이 tmp 저장 루트의 그 경로에
      물리적으로 존재한다(8.3, INV-6).
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    resp = _upload(
        editor, doc_id, filename="photo.png", data=_IMAGE_BYTES, content_type="image/png"
    )
    assert resp.status_code == 201, f"editor 이미지 업로드 201: {resp.status_code} {resp.text}"
    body = resp.json()

    # AttachmentRead 계약 필드(Req 1.4·7.1).
    att_id = body["id"]
    assert body["url"] == f"/attachments/{att_id}", "url 은 /attachments/{id} 파생 규약"
    assert body["kind"] == AttachmentKind.IMAGE.value, "붙여넣기 이미지 kind=image"
    assert body["original_name"] == "photo.png", "원본 파일명 보존"
    assert body["is_archived"] is False, "신규 첨부는 미보관"
    assert body["workspace_id"] == ws_id, "소속 WS 는 대상 문서의 WS"
    assert body["document_id"] == doc_id, "대상 문서에 연결"

    # 응답 url 로 viewer 가 바이너리 왕복 조회(Req 3.3).
    serve = viewer.get(body["url"])
    assert serve.status_code == 200, f"viewer 조회 200: {serve.status_code} {serve.text}"
    assert serve.content == _IMAGE_BYTES, "업로드한 정확한 바이너리를 돌려받아야 한다"
    assert serve.headers["content-type"].startswith("image/png"), "원본명 기반 content-type"

    # DB + 디스크 관찰: WS 격리 저장(Req 3.1).
    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att is not None, "첨부 레코드가 커밋되어 있어야 한다"
        assert att.workspace_id == ws_id
        assert att.file_path.startswith(f"{ws_id}/"), "file_path 는 WS 격리 상대 경로"
        assert att.is_archived is False
        stored_path = att.file_path

    disk_file = tmp_attachment_roots.file_storage_root / stored_path
    assert disk_file.is_file(), "저장 파일이 tmp 저장 루트의 WS 격리 위치에 존재해야 한다"
    assert disk_file.read_bytes() == _IMAGE_BYTES, "디스크 저장 내용은 업로드와 동일"


def test_editor_uploads_general_file_round_trip(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """editor 일반 파일 첨부→viewer 조회 왕복을 검증한다(Req 2.1·2.2·3.1).

    명시 `kind=file` 로 종류를 강제하고, 원본명(`report.pdf`)이 보존되며, 조회 시 원본명 기반
    content-type(application/pdf)으로 정확한 바이너리를 돌려받고, 저장이 WS 격리됨을 확인한다.
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    resp = _upload(
        editor,
        doc_id,
        filename="report.pdf",
        data=_FILE_BYTES,
        content_type="application/pdf",
        kind="file",
    )
    assert resp.status_code == 201, f"editor 파일 업로드 201: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["kind"] == AttachmentKind.FILE.value, "명시 kind=file 이 기록되어야 한다"
    assert body["original_name"] == "report.pdf", "원본 파일명 보존"

    serve = viewer.get(body["url"])
    assert serve.status_code == 200, f"viewer 파일 조회 200: {serve.status_code} {serve.text}"
    assert serve.content == _FILE_BYTES, "업로드한 정확한 파일 바이너리를 돌려받아야 한다"
    assert serve.headers["content-type"].startswith("application/pdf")

    with harness.session_local() as db:
        att = db.get(Attachment, body["id"])
        assert att.workspace_id == ws_id
        assert att.file_path.startswith(f"{ws_id}/"), "일반 파일도 WS 격리 저장"
        stored_path = att.file_path

    disk_file = tmp_attachment_roots.file_storage_root / stored_path
    assert disk_file.is_file()
    assert disk_file.read_bytes() == _FILE_BYTES


def test_serve_non_ascii_filename_does_not_500(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """비-ASCII(한글) 원본명 파일 조회가 500 이 아니라 200 이어야 한다(회귀).

    과거 서빙 라우터가 원본명을 ``Content-Disposition: inline; filename="<원본명>"`` 에 그대로
    넣어, Starlette 의 latin-1 헤더 인코딩에서 한글 파일명이 ``UnicodeEncodeError`` 를 일으켜
    500 이 났다(이미지가 무사했던 건 붙여넣기 이미지 원본명이 ASCII 라서일 뿐). RFC 5987
    ``filename*=UTF-8''`` 인코딩으로 안전하게 직렬화되어야 한다.
    """
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    korean_name = "백엔드-김기열.pdf"
    resp = _upload(
        editor,
        doc_id,
        filename=korean_name,
        data=_FILE_BYTES,
        content_type="application/pdf",
        kind="file",
    )
    assert resp.status_code == 201, f"업로드 201: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["original_name"] == korean_name, "한글 원본명 보존"

    serve = viewer.get(body["url"])
    # 핵심 회귀: 한글 파일명이어도 헤더 인코딩에서 500 이 나지 않는다.
    assert serve.status_code == 200, f"한글 파일명 조회 200: {serve.status_code} {serve.text}"
    assert serve.content == _FILE_BYTES, "정확한 바이너리 반환"

    # RFC 5987 로 UTF-8 percent-encoding 된 파일명 파라미터를 포함한다(ASCII 폴백도 공존).
    disposition = serve.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert quote(korean_name, safe="") in disposition


# =============================================================================
# (2) 업로드 게이팅 — role별 통과·거부·admin bypass·미존재 문서
# =============================================================================


def test_upload_permission_gating(doc_tree_scenario, harness, tmp_attachment_roots):
    """업로드 게이트: viewer 403·비멤버 403·비인증 401·editor 201·admin bypass 201·미존재 404
    (Req 2.3·2.4·3.4, INV-1·2·3). 첨부 권한은 WS 단위 resolver 로만 판정된다."""
    doc_id = doc_tree_scenario.root_id
    scenario = doc_tree_scenario.scenario

    # viewer(멤버, VIEWER)는 editor 미만이라 업로드 403(Req 2.3).
    r_viewer = _upload(
        scenario.viewer_client, doc_id, filename="v.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert r_viewer.status_code == 403, f"viewer 업로드 403: {r_viewer.status_code}"

    # 비멤버(WS 멤버 아님)는 403(INV-2, anti-enumeration).
    r_nonmember = _upload(
        scenario.nonmember_client, doc_id, filename="n.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert r_nonmember.status_code == 403, f"비멤버 업로드 403: {r_nonmember.status_code}"

    # 비인증(세션 없음)은 401(Req 2.4).
    r_anon = _upload(
        harness.new_client(), doc_id, filename="a.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert r_anon.status_code == 401, f"비인증 업로드 401: {r_anon.status_code}"

    # editor(EDITOR)는 201(Req 2.1).
    r_editor = _upload(
        scenario.editor_client, doc_id, filename="e.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert r_editor.status_code == 201, f"editor 업로드 201: {r_editor.status_code} {r_editor.text}"

    # admin(비멤버지만 resolver bypass)은 201(INV-3).
    r_admin = _upload(
        scenario.admin_client, doc_id, filename="ad.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert r_admin.status_code == 201, f"admin bypass 업로드 201: {r_admin.status_code} {r_admin.text}"

    # 미존재 문서 업로드는 문서→WS 어댑터가 판정 이전 404(Req 1.5).
    r_missing = _upload(
        scenario.editor_client, _MISSING_ID, filename="m.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert r_missing.status_code == 404, f"미존재 문서 업로드 404: {r_missing.status_code}"


# =============================================================================
# (3) 서빙 게이팅 — role별 통과·거부·admin bypass·미존재 첨부
# =============================================================================


def test_serve_permission_gating(doc_tree_scenario, harness, tmp_attachment_roots):
    """서빙 읽기 전역 개방: member·비멤버 활성 사용자 모두 200·비인증 401·admin 200·미존재 첨부 404
    (s26 Req 3.4·3.8·7.2). 읽기는 멤버십과 무관하게 열려 있고, 미인증만 401 로 거부된다."""
    doc_id = doc_tree_scenario.root_id
    scenario = doc_tree_scenario.scenario

    # member 가 서빙 대상 첨부를 하나 만든다.
    created = _upload(
        scenario.editor_client, doc_id, filename="served.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert created.status_code == 201
    url = created.json()["url"]

    # member·비멤버 활성 사용자·admin 모두 조회 200(읽기 전역 개방, 403 아님).
    for label, client in (
        ("member", scenario.editor_client),
        ("viewer(비멤버)", scenario.viewer_client),
        ("nonmember", scenario.nonmember_client),
        ("admin", scenario.admin_client),
    ):
        assert client.get(url).status_code == 200, f"{label} 첨부 서빙 200(읽기 개방, 3.8)"

    # 비인증은 401(인증 게이트 유지).
    assert harness.new_client().get(url).status_code == 401, "비인증 조회 401"

    # 미존재 첨부는 첨부→WS 어댑터가 판정 이전 404(Req 3.7).
    r_missing = scenario.viewer_client.get(f"/attachments/{_MISSING_ID}")
    assert r_missing.status_code == 404, f"미존재 첨부 조회 404: {r_missing.status_code}"


def test_ws_role_only_gating_viewer_serves_any_attachment_in_workspace(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """첨부 권한은 WS 단위 resolver 로만 게이팅된다 — viewer 가 WS 내 서로 다른 문서의 첨부를
    모두 서빙함으로 문서·첨부별 개별 권한이 없음을 보인다(Req 3.5).

    editor 가 루트 문서와 손자 문서에 각각 첨부를 올리면, 같은 WS 의 viewer 는 두 첨부를 모두
    조회할 수 있다(개별 ACL 이 있었다면 문서별로 달라졌을 것).
    """
    scenario = doc_tree_scenario.scenario
    viewer = scenario.viewer_client
    editor = scenario.editor_client

    a1 = _upload(
        editor, doc_tree_scenario.root_id, filename="r.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    a2 = _upload(
        editor, doc_tree_scenario.grandchild_id, filename="g.png", data=b"grandchild-doc-bytes",
        content_type="image/png",
    )
    assert a1.status_code == 201 and a2.status_code == 201

    # 서로 다른 문서의 두 첨부를 같은 WS viewer 가 모두 서빙(WS 단위 게이팅).
    assert viewer.get(a1.json()["url"]).status_code == 200, "루트 문서 첨부 서빙 200"
    assert viewer.get(a2.json()["url"]).status_code == 200, "손자 문서 첨부 서빙 200"


# =============================================================================
# (4) 위조 불가 workspace_id + 계약 형태
# =============================================================================


def test_workspace_id_is_determined_from_document_not_client(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """첨부 workspace_id 는 클라이언트 입력이 아니라 대상 문서에서 확정된다(위조 불가, Req 3.2).

    multipart 폼에는 workspace 필드가 없으므로 클라이언트가 WS 를 지정할 방법이 없다. 폼에
    조작된 `workspace_id`/`document_id` 필드를 실어 보내도 무시되고, 영속화된 workspace_id 는
    대상 문서의 workspace 와 정확히 일치한다.
    """
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client

    # 폼에 위조 필드를 실어도 무시되어야 한다(다중 form 필드 주입).
    resp = editor.post(
        f"/documents/{doc_id}/attachments",
        files={"file": ("forge.png", _IMAGE_BYTES, "image/png")},
        data={"workspace_id": "999999", "document_id": "888888"},
    )
    assert resp.status_code == 201, f"조작 필드가 있어도 업로드 201: {resp.status_code} {resp.text}"
    body = resp.json()
    att_id = body["id"]

    # 영속화된 workspace_id 는 대상 문서의 workspace 와 일치(클라이언트 위조값 아님).
    with harness.session_local() as db:
        doc = db.get(Document, doc_id)
        att = db.get(Attachment, att_id)
        assert att.workspace_id == doc.workspace_id, "첨부 WS 는 문서 WS 에서 확정"
        assert att.workspace_id != 999999, "클라이언트가 실은 위조 workspace_id 는 무시된다"
        assert att.document_id == doc_id, "대상 문서에 연결(위조 document_id 무시)"


def test_success_body_matches_attachment_read_and_error_matches_error_response(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """성공 응답은 `AttachmentRead`, 오류 응답은 s01 `ErrorResponse` 규약을 따른다(Req 7.1·7.2)."""
    doc_id = doc_tree_scenario.root_id
    scenario = doc_tree_scenario.scenario

    # 성공 응답: AttachmentRead 로 재검증(누락/타입 오류면 여기서 실패).
    ok = _upload(
        scenario.editor_client, doc_id, filename="shape.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert ok.status_code == 201
    model = AttachmentRead(**ok.json())
    assert model.url == f"/attachments/{model.id}"
    assert model.kind == AttachmentKind.IMAGE
    assert model.is_archived is False
    assert isinstance(model.created_at, datetime)

    # 오류 응답(403): ErrorResponse 규약(code·message).
    err = _upload(
        scenario.viewer_client, doc_id, filename="err.png", data=_IMAGE_BYTES,
        content_type="image/png",
    )
    assert err.status_code == 403
    err_body = err.json()
    assert err_body["code"] == "forbidden", "s01 ErrorCode 값(forbidden)"
    assert isinstance(err_body["message"], str) and err_body["message"], "사람이 읽을 message"

    # 오류 응답(404): 미존재 첨부 조회도 동일 ErrorResponse 규약.
    nf = scenario.viewer_client.get(f"/attachments/{_MISSING_ID}")
    assert nf.status_code == 404
    nf_body = nf.json()
    assert nf_body["code"] == "not_found", "s01 ErrorCode 값(not_found)"
    assert isinstance(nf_body["message"], str) and nf_body["message"]
