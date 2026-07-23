"""링크 경유 첨부 서빙·연동 차단 seam 통합 테스트 (Task 4.4 / design §Testing Strategy
Integration Tests "링크 경유 첨부 서빙·연동 차단 seam", §System Flows "링크 경유 첨부 서빙",
§Components #PublicShareService(serve_public_attachment), §Security(파일 격리·보관),
Req 6.1·6.2·6.3·6.4·6.5·7.7).

마이그레이션된 실제 MySQL 테스트 DB + s14 공유 라우터가 조립된 부팅 앱(`app.main.create_app`,
task 3.3) 위에서 mock 없이 **링크 경유 첨부 서빙** seam 을 검증한다. 하네스·워크스페이스
시나리오·문서 트리·엔진 접근·tmp 저장 루트는 `tests/sharing/conftest.py`(L3 체인 재사용 +
s14 확장)에서 온다. 첨부 업로드는 s12 실경로(`POST /documents/{id}/attachments` multipart)로
수행해 tmp 저장 루트에 실제 바이너리를 기록하고(`tmp_attachment_roots`), 서빙은 공개 경로
(`GET /public/{token}/attachments/{aid}`)로 그 바이너리를 되읽는다. 상태 전이(문서 trashed)는
s07/s10 `DocumentStateEngine` primitive(`engine_access`)로, 게이트(`is_shareable`)는 s05
`PATCH /workspaces/{id}`(owner)로 뒤집는다 — s14 는 관측 가능한 결과만 소비한다.

검증 시나리오(design §System Flows 링크 경유 첨부 서빙 flowchart 관찰 가능 완료 기준):

1. **공유 문서 첨부 서빙(Req 6.1, 8.4)**: 게이트 on·active 루트에 올린 첨부가 링크 경유로
   200 + 업로드한 정확한 바이너리로 서빙된다(실 스트리밍, s12 재사용).
2. **active 하위 첨부 서빙(Req 6.1·6.4)**: 공유 루트의 하위(자식·손자)에 올린 첨부도 루트
   토큰으로 200 바이너리 서빙된다(서브트리 구성원이면 통과).
3. **게이트 off 차단(Req 6.2, 8.5)**: 서빙되던 첨부가 게이트 off 이후 404(파일 접근도 함께 차단).
4. **문서 trashed 차단(Req 6.2, 8.5)**: 공유 문서를 trashed 로 전이하면 파일 접근도 404.
5. **보관 첨부 404(Req 6.3)**: 범위 안 첨부라도 `is_archived` 이면 s12 규약대로 role·경로 무관
   404(보관 파일 비노출).
6. **범위 밖·다른 WS 404(Req 6.4, INV-6)**: 공유 서브트리에 속하지 않는 같은 WS 문서의 첨부,
   그리고 다른 워크스페이스의 첨부는 범위 밖으로 404 비노출.
7. **미존재 첨부 id·미존재 토큰 404(정보 비노출)**: 유효 토큰 + 미존재 aid, 미존재 토큰 +
   유효 aid 모두 사유 구분 없이 404.

재사용 관찰(Req 6.5·7.7): s14 는 첨부 저장·격리·보관을 재구현하지 않고 s12 첨부 서빙(업로드·
저장·보관 판정)을 재사용한다 — 업로드가 s12 라우트로 tmp 에 실제 파일을 쓰고, 링크 경유 서빙이
그 바이너리를 되읽으며, 보관 차단이 s12 `serve_attachment` 위임에서 발생한다는 것이 이를
입증한다. mock·stub 미사용, 공유 `markspace_test` DB 오염 방지를 위해 문서 제목에 uuid4
접미사를 쓴다. DB 미가용·부팅 실패는 스킵이 아니라 `harness` 가 오류를 전파해 **실패**한다.
"""

from uuid import uuid4

from app.document.repository import DocumentRepository
from app.models import Attachment
from tests.integration_L2 import helpers as l2_helpers

# 업로드 바이너리(작은 시그니처 + 페이로드; 25MiB 한도 이하라 서빙 왕복만 검증).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-link-attachment-serve-payload"
_CHILD_BYTES = b"\x89PNG\r\n\x1a\n-descendant-attachment-payload"

# 시드 범위와 겹치지 않는, 존재하지 않는 첨부 id(정보 비노출 404 관찰용).
_MISSING_AID = 99_999_999


def _unique_title(prefix: str) -> str:
    """공유 ``markspace_test`` DB 에서 충돌하지 않는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _enable_gate(scenario) -> None:
    """워크스페이스 `is_shareable` 게이트를 owner 세션으로 켠다(발급/서빙 전제, s05 소유 게이트).

    `doc_tree_scenario` 의 워크스페이스는 게이트 OFF 로 시작하므로, 링크 경유 접근이 가능하려면
    실제 owner 라우트로 게이트를 켜야 한다(s14 는 게이트를 소유하지 않고 관측만 한다).
    """
    l2_helpers.update_settings(
        scenario.owner_client, scenario.workspace_id, is_shareable=True
    )


def _disable_gate(scenario) -> None:
    """워크스페이스 `is_shareable` 게이트를 owner 세션으로 끈다(s05 라우트)."""
    l2_helpers.update_settings(
        scenario.owner_client, scenario.workspace_id, is_shareable=False
    )


def _create_doc(client, ws_id: int, title: str, parent_id: int | None = None) -> dict:
    """세션으로 ``POST /workspaces/{id}/documents`` 를 태워 active 문서를 만든다(201)."""
    body: dict[str, object] = {"title": title}
    if parent_id is not None:
        body["parent_id"] = parent_id
    resp = client.post(f"/workspaces/{ws_id}/documents", json=body)
    assert resp.status_code == 201, (
        f"문서 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _upload(client, doc_id: int, *, filename: str, data: bytes) -> int:
    """editor 세션으로 s12 실경로에 첨부를 업로드하고 첨부 id 를 반환한다(201 단언).

    파일 필드명은 계약상 ``file`` 이며, content-type 이 kind 추론을 구동한다(image/* → image).
    업로드는 `tmp_attachment_roots` 가 격리한 tmp 저장 루트에 실제 바이너리를 기록한다.
    """
    resp = client.post(
        f"/documents/{doc_id}/attachments",
        files={"file": (filename, data, "image/png")},
    )
    assert resp.status_code == 201, (
        f"첨부 업로드 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()["id"]


def _issue(client, doc_id: int) -> str:
    """editor 세션으로 ``POST /documents/{id}/share`` 를 태워 활성 링크 토큰을 반환한다(200).

    발급된 링크는 항상 활성이며 `share_url` 은 `/public/{token}` 규약이다(INV-8).
    """
    resp = client.post(f"/documents/{doc_id}/share")
    assert resp.status_code == 200, (
        f"공유 링크 발급 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    assert body["is_enabled"] is True, "발급된 링크는 활성이어야 한다"
    assert body["share_url"] == f"/public/{body['token']}", (
        "share_url 은 /public/{token} 규약이어야 한다"
    )
    return body["token"]


def _serve(anon, token: str, aid: int):
    """``GET /public/{token}/attachments/{aid}`` 를 태우고 응답을 그대로 반환한다(상태 미단언).

    성공(200 바이너리)·거부(404 JSON) 를 각 테스트가 단언한다.
    """
    return anon.get(f"/public/{token}/attachments/{aid}")


def _assert_not_found(resp) -> None:
    """링크 경유 서빙 거부가 s01 `ErrorResponse`(code=not_found) 규약의 404 임을 단언한다."""
    assert resp.status_code == 404, (
        f"차단된 링크 경유 첨부 접근은 404 여야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "not_found", "s01 ErrorCode 값(not_found)"


# =============================================================================
# (1) 공유 문서 첨부 서빙 — 실 바이너리 왕복 (Req 6.1, 8.4)
# =============================================================================


def test_serves_attachment_on_shared_doc(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """게이트 on·active 루트에 올린 첨부가 링크 경유로 200 + 정확한 바이너리로 서빙된다
    (Req 6.1·6.5·7.7, 8.4).

    editor 가 s12 실경로로 루트 문서에 첨부를 업로드(tmp 저장 루트에 실제 파일 기록)하고 링크를
    발급한 뒤, 인증 없는 클라이언트가 `GET /public/{token}/attachments/{aid}` 로 업로드한 **정확한
    바이너리**를 content-type 과 함께 되받는다 — s14 가 s12 첨부 서빙을 재사용해 실 스트리밍한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    anon = harness.new_client()  # 공개 경로는 인증이 없어 로그인하지 않은 클라이언트로 접근.

    aid = _upload(editor, root_id, filename="shared.png", data=_IMAGE_BYTES)
    token = _issue(editor, root_id)

    resp = _serve(anon, token, aid)
    assert resp.status_code == 200, (
        f"공유 문서 첨부는 링크 경유 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.content == _IMAGE_BYTES, "업로드한 정확한 바이너리를 되받아야 한다(실 스트리밍)"
    assert resp.headers["content-type"].startswith("image/png"), "원본명 기반 content-type"


# =============================================================================
# (2) active 하위 첨부 서빙 — 서브트리 구성원 (Req 6.1·6.4)
# =============================================================================


def test_serves_attachment_on_active_descendant(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """공유 루트의 active 하위(자식·손자)에 올린 첨부도 루트 토큰으로 200 바이너리 서빙된다
    (Req 6.1·6.4·7.7).

    루트→자식→손자 트리에서 루트에 링크를 발급하고, 자식·손자 문서에 각각 올린 첨부를 **루트
    토큰**으로 서빙하면 둘 다 200 + 정확한 바이너리를 되받는다 — 서브트리 구성원 문서의 첨부는
    링크 범위 안(s07 active_descendants 소속)임을 관찰한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    child_aid = _upload(
        editor, doc_tree_scenario.child_id, filename="child.png", data=_CHILD_BYTES
    )
    grandchild_aid = _upload(
        editor, doc_tree_scenario.grandchild_id, filename="gc.png", data=_IMAGE_BYTES
    )
    token = _issue(editor, root_id)

    child_resp = _serve(anon, token, child_aid)
    assert child_resp.status_code == 200, (
        f"자식 문서 첨부는 루트 토큰 경유 200 이어야 한다: {child_resp.status_code} {child_resp.text}"
    )
    assert child_resp.content == _CHILD_BYTES, "자식 첨부의 정확한 바이너리를 되받아야 한다"

    grandchild_resp = _serve(anon, token, grandchild_aid)
    assert grandchild_resp.status_code == 200, (
        f"손자 문서 첨부는 루트 토큰 경유 200 이어야 한다: {grandchild_resp.status_code}"
    )
    assert grandchild_resp.content == _IMAGE_BYTES, "손자 첨부의 정확한 바이너리를 되받아야 한다"


# =============================================================================
# (3) 게이트 off 연동 차단 (Req 6.2, 8.5)
# =============================================================================


def test_gate_off_blocks_link_attachment(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """서빙되던 링크 경유 첨부가 게이트 off 이후 404 로 함께 차단된다(Req 6.2, 8.5).

    첨부가 정상 서빙됨을 먼저 확인한 뒤, owner 가 게이트를 끄면(s05) 공개 렌더와 동일한 실시간
    유효성 게이트가 파일 접근도 차단해 404 로 통일한다(파일 접근이 게이트와 함께 무효화됨).
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    aid = _upload(editor, root_id, filename="gated.png", data=_IMAGE_BYTES)
    token = _issue(editor, root_id)

    # 게이트 on 상태에서는 정상 서빙(전제 확인).
    assert _serve(anon, token, aid).status_code == 200, "게이트 on 에서는 서빙되어야 한다"

    # owner 가 게이트 off → 파일 접근도 함께 404(실시간 게이트, Req 6.2).
    _disable_gate(scenario)
    _assert_not_found(_serve(anon, token, aid))


# =============================================================================
# (4) 문서 trashed 연동 차단 (Req 6.2, 8.5)
# =============================================================================


def test_trashed_doc_blocks_link_attachment(
    doc_tree_scenario, harness, engine_access, tmp_attachment_roots
):
    """공유 문서를 trashed 로 전이하면 링크 경유 파일 접근도 404 로 차단된다(Req 6.2, 8.5).

    첨부가 정상 서빙됨을 확인한 뒤 s07/s10 상태 엔진(`engine_access`)으로 공유 루트를 trashed 로
    전이하면(s14 미경유), 실시간 유효성 게이트가 문서 status 를 관측해 파일 접근을 404 로
    차단한다 — 파일 접근이 문서 status 와 함께 무효화됨을 관찰한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    aid = _upload(editor, root_id, filename="trashed.png", data=_IMAGE_BYTES)
    token = _issue(editor, root_id)
    assert _serve(anon, token, aid).status_code == 200, "trashed 전에는 서빙되어야 한다"

    # s07/s10 경로로 공유 루트를 trashed 로 전이(실제 커밋, s14 미경유).
    with engine_access.session() as db:
        doc = DocumentRepository().get(db, root_id)
        assert doc is not None, "공유 루트 문서가 존재해야 한다"
        engine_access.engine.trash_document(db, doc)

    # trashed 후: 파일 접근도 함께 404(문서 status 관측, Req 6.2).
    _assert_not_found(_serve(anon, token, aid))


# =============================================================================
# (5) 보관 첨부 404 — s12 규약 재사용 (Req 6.3)
# =============================================================================


def test_archived_attachment_is_404(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """범위 안 첨부라도 보관(archived)되면 s12 규약대로 role·경로 무관 404 로 비노출된다(Req 6.3·6.5).

    게이트 on·active 루트에 올린(따라서 링크 범위 안) 첨부를 앱 세션 팩토리로 직접 `is_archived=
    True` 로 뒤집으면, s14 서빙이 s12 `serve_attachment` 위임에서 보관 차단을 받아 404 가 된다 —
    보관 판정을 s14 가 재구현하지 않고 s12 규약을 그대로 이어받음을 입증한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    aid = _upload(editor, root_id, filename="archived.png", data=_IMAGE_BYTES)
    token = _issue(editor, root_id)
    assert _serve(anon, token, aid).status_code == 200, "보관 전에는 서빙되어야 한다"

    # 앱 세션 팩토리로 첨부를 직접 보관 처리(결정적) — s12 serve 위임이 role·경로 무관 404.
    with harness.session_local() as db:
        att = db.get(Attachment, aid)
        assert att is not None, "첨부 레코드가 커밋되어 있어야 한다"
        att.is_archived = True
        db.commit()

    # 보관 후: 범위 안이어도 404(s12 보관 규약 재사용, Req 6.3).
    _assert_not_found(_serve(anon, token, aid))


# =============================================================================
# (6) 범위 밖·다른 워크스페이스 404 (Req 6.4, INV-6)
# =============================================================================


def test_out_of_scope_and_other_workspace_are_404(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """공유 서브트리 밖(같은 WS)·다른 워크스페이스의 첨부는 링크 범위 밖으로 404 비노출된다
    (Req 6.4, INV-6).

    (a) 같은 WS 이지만 공유 루트의 하위가 아닌 별도 루트 문서의 첨부는 서브트리 구성원이 아니므로
        루트 토큰으로 404(같은 WS 라도 소속 검사로 차단).
    (b) 다른 워크스페이스(owner 가 별도 생성, 게이트 on)의 문서 첨부는 WS 격리 검사로 404.
    두 경로 모두 s14 서빙의 소속(`document_id ∈ 서브트리`)·격리(`workspace_id` 일치) 검사가
    범위 밖 파일을 노출하지 않음을 관찰한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    owner = scenario.owner_client
    ws_id = doc_tree_scenario.workspace_id
    root_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    token = _issue(editor, root_id)

    # (a) 같은 WS 의, 공유 루트 하위가 아닌 별도 루트 문서 + 그 첨부(범위 밖).
    unrelated = _create_doc(editor, ws_id, _unique_title("범위밖루트"))
    unrelated_aid = _upload(
        editor, unrelated["id"], filename="unrelated.png", data=_IMAGE_BYTES
    )
    _assert_not_found(_serve(anon, token, unrelated_aid))

    # (b) 다른 워크스페이스(owner 생성, 게이트 on) 문서 + 그 첨부(WS 격리 밖).
    ws2_id = l2_helpers.create_workspace(owner, _unique_title("다른WS"))
    l2_helpers.update_settings(owner, ws2_id, is_shareable=True)
    ws2_doc = _create_doc(owner, ws2_id, _unique_title("다른WS문서"))
    ws2_aid = _upload(owner, ws2_doc["id"], filename="ws2.png", data=_IMAGE_BYTES)
    _assert_not_found(_serve(anon, token, ws2_aid))


# =============================================================================
# (7) 미존재 첨부 id·미존재 토큰 404 — 정보 비노출
# =============================================================================


def test_unknown_attachment_and_unknown_token_are_404(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """유효 토큰 + 미존재 첨부 id, 미존재 토큰 + 유효 첨부 id 모두 사유 구분 없이 404 다(정보 비노출).

    존재 추정을 차단하기 위해 첨부 부재·토큰 부재를 동일한 404 로 통일한다: 유효 링크에서 시드
    범위 밖 aid 조회는 404, 그리고 미존재(bogus) 토큰으로는 실재하는 aid 를 조회해도 404.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    aid = _upload(editor, root_id, filename="known.png", data=_IMAGE_BYTES)
    token = _issue(editor, root_id)
    # sanity: 유효 토큰 + 유효 aid 는 서빙된다(대비군).
    assert _serve(anon, token, aid).status_code == 200, "유효 토큰+aid 는 서빙되어야 한다"

    # 유효 토큰 + 미존재 aid → 404(첨부 부재 비노출).
    _assert_not_found(_serve(anon, token, _MISSING_AID))

    # 미존재 토큰 + 유효 aid → 404(토큰 부재 비노출, 사유 구분 없음).
    _assert_not_found(_serve(anon, f"bogus-{uuid4().hex}", aid))
