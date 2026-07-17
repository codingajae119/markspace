"""공개 렌더 동적 하위 통합 테스트 (Task 4.3 / design §Testing Strategy Integration Tests
"동적 하위 포함", §System Flows "공개 읽기 전용 렌더", Req 3.1·3.2·3.3·3.4·3.5·7.7).

마이그레이션된 DB + 부팅 앱(공유 라우터 조립, 4.x conftest) 위에서 **실제** s14 공개 렌더
경로를 mock 없이 관찰한다. 검증 대상은 design §System Flows 공개 렌더 flowchart 의 관찰 가능
완료 기준 그대로다:

- **기본 렌더 + 안전 렌더(Req 3.1·3.2)**: 활성 링크 토큰으로 `GET /public/{token}` 이 문서를
  루트로 하는 읽기 전용 트리를 반환하고, 본문은 s07 `MarkdownRenderer` 로 안전 렌더되어
  실행 가능한 스크립트·이벤트 핸들러가 제거된다.
- **참조 재작성(Req 3.2, 링크 스코프)**: 렌더 HTML 의 `/attachments/{id}` 첨부 참조가
  `/public/{token}/attachments/{id}` 로 재작성되며, `5`↔`50` id 경계가 오염되지 않는다.
- **동적 active 하위 포함(Req 3.1·3.4)**: 발급 이후 하위 문서를 추가하면 **같은 토큰** 재요청에
  새 하위가 트리에 동적으로 포함되고, 손자까지 중첩된다(재발급 불필요).
- **trashed 하위 제외(Req 3.5)**: 하위를 trashed 로 전이하면 그 서브트리가 트리에서 제외된다
  (접근 시점의 현재 active 하위만 포함).
- **읽기 전용(Req 3.3)**: 공개 경로는 GET 만 서빙하며 변경 엔드포인트를 제공하지 않는다.

재사용 관찰(Req 7.7): 공개 렌더는 s07 `DocumentStateEngine.active_descendants`(동적 active 하위
질의)·`MarkdownRenderer`(안전 렌더)를 재사용하며, 동적 포함/제외·안전 렌더가 실제 앱에서
동작한다는 것이 s14 가 그 primitive 를 재구현하지 않고 소비함을 입증한다(하위 문서 추가/trashed
전이는 s07/s10 경로로 커밋되고, 공개 렌더가 그 상태를 접근 시점에 그대로 반영한다).

mock·stub 미사용, 공유 `notion_lite_test` DB 오염 방지를 위해 문서 제목에 uuid4 접미사를 쓴다.
DB 미가용·부팅 실패는 스킵이 아니라 `harness` 가 오류를 전파해 **실패**한다.
"""

from datetime import datetime
from uuid import uuid4

from app.document.repository import DocumentRepository
from app.models import Document, DocumentVersion
from tests.integration_L2 import helpers as l2_helpers

# 안전 렌더(스크립트 제거)·참조 재작성(링크 스코프)·id 경계를 한 번에 관찰하기 위한 본문.
# `<script>`·`onerror` 는 s07 MarkdownRenderer(markdown-it html=False + nh3)가 제거하고,
# `/attachments/5`·`/attachments/50` 이미지 참조는 링크 스코프 경로로 재작성되어야 한다.
_UNSAFE_CONTENT = (
    "# 제목\n\n"
    "<script>alert(1)</script>\n\n"
    '<img src="x" onerror="alert(2)">\n\n'
    "![그림](/attachments/5)\n\n"
    "![다른](/attachments/50)\n"
)


def _unique_title(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 에서 충돌하지 않는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _enable_sharing(ws_scenario) -> None:
    """owner 세션으로 워크스페이스 게이트(`is_shareable`)를 켠다(발급 전제, s05 소유 게이트)."""
    l2_helpers.update_settings(
        ws_scenario.owner_client, ws_scenario.workspace_id, is_shareable=True
    )


def _create_doc(client, ws_id: int, title: str, parent_id: int | None = None) -> dict:
    """editor 세션으로 ``POST /workspaces/{id}/documents`` 를 태워 active 문서를 만든다(201)."""
    body: dict[str, object] = {"title": title}
    if parent_id is not None:
        body["parent_id"] = parent_id
    resp = client.post(f"/workspaces/{ws_id}/documents", json=body)
    assert resp.status_code == 201, (
        f"문서 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _issue_share(client, doc_id: int) -> dict:
    """editor 세션으로 ``POST /documents/{id}/share`` 를 태워 활성 링크를 발급한다(200).

    파싱된 `ShareLinkRead`(token·share_url·is_enabled) dict 를 반환한다.
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
    return body


def _seed_content(session_local, doc_id: int, content: str, created_by: int) -> None:
    """`DocumentVersion` 을 시드하고 문서의 `current_version_id` 를 그 버전으로 가리킨다.

    s09 편집 잠금 흐름을 거치지 않고 결정적으로 본문을 주입해, 공개 렌더가
    `load_current_content`→`MarkdownRenderer`→참조 재작성을 실제로 수행하게 한다(앱 세션 팩토리
    사용, API 커밋 경계와 정렬).
    """
    with session_local() as db:
        ver = DocumentVersion(
            document_id=doc_id,
            content=content,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        db.add(ver)
        db.flush()
        doc = db.get(Document, doc_id)
        doc.current_version_id = ver.id
        db.commit()


def _render(client, token: str) -> dict:
    """``GET /public/{token}`` 을 태워 200 을 단언하고 파싱된 `PublicDocumentRead` 를 반환한다."""
    resp = client.get(f"/public/{token}")
    assert resp.status_code == 200, (
        f"공개 렌더 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def _find_node(node: dict, target_id: int) -> dict | None:
    """읽기 전용 트리에서 id 로 노드를 재귀 탐색한다(없으면 None)."""
    if node["id"] == target_id:
        return node
    for child in node["children"]:
        found = _find_node(child, target_id)
        if found is not None:
            return found
    return None


def _child_ids(node: dict) -> set[int]:
    """노드의 직계 자식 id 집합."""
    return {child["id"] for child in node["children"]}


def test_public_render_base_and_safe_render(harness, ws_scenario):
    """발급된 활성 링크로 문서를 안전 렌더된 읽기 전용 트리로 반환한다(Req 3.1·3.2).

    루트 문서를 만들고 스크립트·이벤트 핸들러가 섞인 본문을 시드한 뒤 발급→공개 렌더한다.
    응답 루트가 문서 id·title 을 담고, content_html 에서 실행 가능한 스크립트·이벤트 핸들러가
    제거되었음을 단언한다(s07 MarkdownRenderer 재사용, Req 7.7).
    """
    _enable_sharing(ws_scenario)
    ws_id = ws_scenario.workspace_id
    title = _unique_title("공개루트")
    root = _create_doc(ws_scenario.editor_client, ws_id, title)
    _seed_content(
        harness.session_local, root["id"], _UNSAFE_CONTENT,
        ws_scenario.editor_user_id,
    )

    issued = _issue_share(ws_scenario.editor_client, root["id"])
    token = issued["token"]

    body = _render(harness.new_client(), token)
    root_node = body["root"]

    # 루트 정체성: 공유 문서가 트리의 루트다.
    assert root_node["id"] == root["id"], "트리 루트는 공유 문서여야 한다"
    assert root_node["title"] == title, "루트 title 이 문서 제목과 일치해야 한다"
    assert isinstance(root_node["children"], list)

    # 안전 렌더: 스크립트 태그·이벤트 핸들러가 제거된다(s07 MarkdownRenderer, Req 3.2).
    html = root_node["content_html"]
    assert "<script>" not in html, "스크립트 태그가 남으면 안 된다(안전 렌더)"
    assert "alert(1)" not in html, "스크립트 본문이 실행 가능한 형태로 남으면 안 된다"
    assert "onerror=" not in html, "이벤트 핸들러 속성이 남으면 안 된다(안전 렌더)"
    # 안전한 서식은 보존된다(렌더가 실제로 markdown 을 HTML 로 변환했음).
    assert "제목" in html, "안전한 본문 텍스트는 보존되어야 한다"


def test_public_render_rewrites_attachment_refs_to_link_scope(harness, ws_scenario):
    """content_html 의 첨부 참조가 링크 스코프 경로로 재작성되고 id 경계가 보존된다(Req 3.2).

    `/attachments/5`·`/attachments/50` 이미지 참조가 각각
    `/public/{token}/attachments/5`·`/public/{token}/attachments/50` 로 재작성되며, 바레(un-
    rewritten) 참조가 남지 않고 `5`→`50` id 경계가 오염되지 않음을 실제 토큰 기준으로 단언한다.
    """
    _enable_sharing(ws_scenario)
    ws_id = ws_scenario.workspace_id
    root = _create_doc(ws_scenario.editor_client, ws_id, _unique_title("참조루트"))
    _seed_content(
        harness.session_local, root["id"], _UNSAFE_CONTENT,
        ws_scenario.editor_user_id,
    )

    issued = _issue_share(ws_scenario.editor_client, root["id"])
    token = issued["token"]

    body = _render(harness.new_client(), token)
    html = body["root"]["content_html"]

    # 링크 스코프로 재작성된 경로가 존재한다(id 5·50 각각). 닫는 따옴표로 id 경계를 고정한다.
    assert f'/public/{token}/attachments/5"' in html, (
        "id 5 참조가 링크 스코프 경로로 재작성되어야 한다"
    )
    assert f'/public/{token}/attachments/50"' in html, (
        "id 50 참조가 링크 스코프 경로로 재작성되어야 한다(50 이 5 로 잘리지 않음)"
    )
    # 바레 참조가 남지 않는다: src 값 앞의 따옴표로 미재작성 참조를 식별한다(속성 순서 무관).
    assert '"/attachments/5"' not in html, "바레 /attachments/5 참조가 남으면 안 된다"
    assert '"/attachments/50"' not in html, "바레 /attachments/50 참조가 남으면 안 된다"


def test_public_render_dynamic_active_subtree_inclusion(harness, ws_scenario):
    """발급 이후 추가한 하위가 같은 토큰 재요청에 동적으로 트리에 포함된다(Req 3.1·3.4).

    루트만 있는 상태로 발급→렌더(자식 없음)→editor 가 자식 추가→같은 토큰 재렌더에 자식이
    root.children 에 등장→손자 추가→재렌더에 손자가 자식 밑에 중첩됨을 id 로 단언한다. 재발급
    없이 접근 시점의 현재 active 하위(s07 active_descendants)가 반영됨을 관찰한다(Req 7.7).
    """
    _enable_sharing(ws_scenario)
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    root = _create_doc(editor, ws_id, _unique_title("동적루트"))

    issued = _issue_share(editor, root["id"])
    token = issued["token"]

    # 발급 시점: 하위 없음.
    before = _render(harness.new_client(), token)
    assert before["root"]["id"] == root["id"]
    assert before["root"]["children"] == [], "발급 시점엔 하위가 없어야 한다"

    # 자식 추가 → 같은 토큰 재요청에 동적으로 포함(재발급 없음).
    child = _create_doc(editor, ws_id, _unique_title("동적자식"), parent_id=root["id"])
    after_child = _render(harness.new_client(), token)
    assert _child_ids(after_child["root"]) == {child["id"]}, (
        "새 하위가 같은 토큰 재요청에 동적으로 root.children 에 포함되어야 한다"
    )

    # 손자 추가 → 재렌더에 자식 밑으로 중첩.
    grandchild = _create_doc(
        editor, ws_id, _unique_title("동적손자"), parent_id=child["id"]
    )
    after_grandchild = _render(harness.new_client(), token)
    child_node = _find_node(after_grandchild["root"], child["id"])
    assert child_node is not None, "자식 노드가 트리에 있어야 한다"
    assert _child_ids(child_node) == {grandchild["id"]}, (
        "손자가 자식 노드 밑에 중첩되어야 한다(동적 계층 반영)"
    )
    # 루트의 직계 자식은 여전히 자식 하나뿐(손자는 자식 밑에만 존재).
    assert _child_ids(after_grandchild["root"]) == {child["id"]}


def test_public_render_excludes_trashed_subtree(harness, ws_scenario, engine_access):
    """하위를 trashed 로 전이하면 그 서브트리가 트리에서 제외된다(Req 3.5).

    루트→자식→손자 트리를 만들어 발급·렌더로 자식·손자 포함을 확인한 뒤, s07 상태 엔진
    (`engine_access`)으로 자식을 trashed(그 시점 active 하위 = 손자까지 캐스케이드)하면 같은
    토큰 재요청에 자식·손자가 모두 제외되고 접근 시점의 현재 active 하위(루트만)만 남음을 id
    부재로 단언한다(Req 7.7).
    """
    _enable_sharing(ws_scenario)
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client
    root = _create_doc(editor, ws_id, _unique_title("보관루트"))
    child = _create_doc(editor, ws_id, _unique_title("보관자식"), parent_id=root["id"])
    grandchild = _create_doc(
        editor, ws_id, _unique_title("보관손자"), parent_id=child["id"]
    )

    issued = _issue_share(editor, root["id"])
    token = issued["token"]

    # trashed 전: 자식·손자가 트리에 포함된다.
    before = _render(harness.new_client(), token)
    assert _find_node(before["root"], child["id"]) is not None
    assert _find_node(before["root"], grandchild["id"]) is not None

    # s07 상태 엔진으로 자식을 trashed(그 시점 active 하위 = 손자까지 캐스케이드, 실제 커밋).
    with engine_access.session() as db:
        doc = DocumentRepository().get(db, child["id"])
        assert doc is not None
        engine_access.engine.trash_document(db, doc)

    # trashed 후: 같은 토큰 재요청에 자식·손자 서브트리 전체가 제외되고 루트만 남는다.
    after = _render(harness.new_client(), token)
    assert after["root"]["id"] == root["id"], "루트는 여전히 active 로 노출된다"
    assert _find_node(after["root"], child["id"]) is None, (
        "trashed 자식은 트리에서 제외되어야 한다"
    )
    assert _find_node(after["root"], grandchild["id"]) is None, (
        "trashed 자식의 손자 서브트리도 함께 제외되어야 한다"
    )
    assert after["root"]["children"] == [], (
        "접근 시점의 현재 active 하위(루트만)만 남아야 한다"
    )


def test_public_path_is_read_only_no_mutation_endpoints(harness, ws_scenario):
    """공개 경로는 GET 만 서빙하며 변경 엔드포인트를 제공하지 않는다(Req 3.3).

    발급된 토큰에 대해 POST·PUT·DELETE `/public/{token}` 이 405(Method Not Allowed) 또는
    404(라우트 아님)로 거부되고, GET 만 200 을 반환함을 단언한다 — 공개 표면이 읽기 전용임을
    입증한다(변경 동작 없음).
    """
    _enable_sharing(ws_scenario)
    ws_id = ws_scenario.workspace_id
    root = _create_doc(ws_scenario.editor_client, ws_id, _unique_title("읽기전용루트"))
    issued = _issue_share(ws_scenario.editor_client, root["id"])
    token = issued["token"]

    client = harness.new_client()
    path = f"/public/{token}"

    # 변경 메서드는 405(경로는 있으나 메서드 미허용) 또는 404(라우트 부재)로만 응답한다.
    for method in ("post", "put", "delete", "patch"):
        resp = getattr(client, method)(path)
        assert resp.status_code in (404, 405), (
            f"{method.upper()} {path} 는 변경 동작을 제공하지 않아야 한다: "
            f"{resp.status_code} {resp.text}"
        )
        # 어떤 경우에도 2xx(성공적 변경)가 나오면 안 된다.
        assert not (200 <= resp.status_code < 300), (
            f"{method.upper()} {path} 가 성공하면 안 된다(읽기 전용 위반)"
        )

    # GET 은 읽기 전용 트리를 200 으로 반환한다(유일하게 서빙되는 메서드).
    get_resp = client.get(path)
    assert get_resp.status_code == 200, (
        f"GET {path} 는 읽기 전용 렌더로 200 이어야 한다: {get_resp.status_code}"
    )
    assert get_resp.json()["root"]["id"] == root["id"]
