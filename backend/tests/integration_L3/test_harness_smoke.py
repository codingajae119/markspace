"""L3 하네스 스모크 테스트 (Task 1.1 관찰 가능한 완료 기준 / Req 1.1·1.2·1.3·1.4).

L3 하네스(``harness``·``ws_scenario`` 재사용 + ``doc_tree_scenario``·``engine_access`` 신규)가
**s07 문서 라우트가 조립된 실제 결합 런타임** 위에서 다음을 실제로 제공함을 end-to-end 로
증명한다:

1. ``doc_tree_scenario`` 가 마이그레이션 DB + 부팅 앱(s07 문서 라우트) + admin 시드 + role별
   세션 클라이언트 + 구성된 워크스페이스/멤버 + 문서 트리(루트→자식→손자)를 제공한다.
2. editor 세션의 ``POST /workspaces/{id}/documents`` 가 201 을 반환한다(문서 라우트가 부팅
   앱에 마운트·게이팅됨을 증명).
3. ``engine_access`` 가 부팅 앱과 동일 DB 위의 실제 `DocumentStateEngine` 인스턴스를 제공하고,
   ``identify_bundles(workspace_id)`` 호출이 결과(list)를 반환한다(라우터 밖 primitive 재사용
   경계가 오류 없이 호출 가능).

또한 스모크가 **실제 결합 런타임을 실제로 관통**함(자명 통과 안티패턴 회피)을 보이기 위해,
editor 가 API 로 문서를 생성·삭제(`DELETE /documents/{id}` 204)한 뒤 엔진 ``identify_bundles``
가 그 삭제를 **API 커밋 후 신선하게 관찰**해 해당 루트를 묶음으로 식별함을 확인한다(동일 DB·
동일 세션 팩토리 정합).
"""

from app.document.engine import Bundle


def test_doc_tree_scenario_provides_three_level_tree(doc_tree_scenario):
    """문서 트리(루트→자식→손자)가 실제 라우트로 구성되어 계층·상태·소속이 정합한다.

    root←child←grandchild parent_id 연결, 모두 status=active·같은 workspace_id, 그리고
    editor 가 작성자임을 관측한다(부팅 앱 s07 문서 라우트가 실제로 트리를 만든 결과).
    """
    tree = doc_tree_scenario
    ws_id = tree.workspace_id

    assert tree.root["parent_id"] is None, f"루트는 parent_id 가 None: {tree.root!r}"
    assert tree.child["parent_id"] == tree.root_id, (
        f"자식의 parent_id 는 루트 id 여야 한다: {tree.child!r}"
    )
    assert tree.grandchild["parent_id"] == tree.child_id, (
        f"손자의 parent_id 는 자식 id 여야 한다: {tree.grandchild!r}"
    )
    for label, doc in (("루트", tree.root), ("자식", tree.child), ("손자", tree.grandchild)):
        assert doc["workspace_id"] == ws_id, f"{label} 는 같은 WS 소속: {doc!r}"
        assert doc["status"] == "active", f"{label} 는 생성 직후 active: {doc!r}"
        assert doc["created_by"] == tree.scenario.editor_user_id, (
            f"{label} 작성자는 editor 여야 한다: {doc!r}"
        )


def test_editor_can_create_document_returns_201(doc_tree_scenario):
    """editor 세션의 POST /workspaces/{id}/documents 가 201(문서 라우트 마운트·게이팅 증명)."""
    ws_id = doc_tree_scenario.workspace_id
    resp = doc_tree_scenario.editor_client.post(
        f"/workspaces/{ws_id}/documents",
        json={"title": "스모크-신규문서"},
    )
    assert resp.status_code == 201, (
        f"editor 문서 생성은 201 이어야 한다(라우트 마운트+EDITOR 게이트 통과): "
        f"{resp.status_code} {resp.text}"
    )


def test_engine_identify_bundles_callable_over_same_db(doc_tree_scenario, engine_access):
    """engine.identify_bundles(workspace_id) 가 동일 DB 위에서 오류 없이 list 를 반환한다.

    아직 아무것도 삭제하지 않았으므로 이 워크스페이스에 대한 결과는 빈 리스트일 수 있다 —
    핵심은 primitive 가 부팅 앱과 동일 세션 팩토리 위에서 **호출 가능**하다는 것이다(라우터 밖
    재사용 경계, Req 1.1·design §L3TestHarness).
    """
    ws_id = doc_tree_scenario.workspace_id
    bundles = engine_access.identify_bundles(ws_id)
    assert isinstance(bundles, list), (
        f"identify_bundles 는 list[Bundle] 를 반환해야 한다: {bundles!r}"
    )
    for b in bundles:
        assert isinstance(b, Bundle), f"항목은 Bundle 이어야 한다: {b!r}"


def test_engine_observes_api_committed_delete(doc_tree_scenario, engine_access):
    """엔진이 API 커밋(DELETE)을 신선하게 관찰해 해당 루트를 묶음으로 식별한다(자명 통과 회피).

    editor 가 새 문서를 API 로 만들고 `DELETE /documents/{id}` (204)로 휴지통에 보낸 뒤,
    엔진 `identify_bundles` 가 그 삭제를 관찰해 삭제된 문서 id 를 루트로 하는 묶음을 식별해야
    한다. 이는 엔진 세션이 부팅 앱과 동일 DB 를 보고(동일 세션 팩토리) primitive 가 실제 s07
    코드로 동작함을 증명한다 — 실 런타임을 관통하지 않는 자명 통과가 아님을 보인다.
    """
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client

    created = editor.post(
        f"/workspaces/{ws_id}/documents", json={"title": "스모크-삭제대상"}
    )
    assert created.status_code == 201, f"{created.status_code} {created.text}"
    doc_id = created.json()["id"]

    deleted = editor.delete(f"/documents/{doc_id}")
    assert deleted.status_code == 204, (
        f"editor 삭제는 204 여야 한다: {deleted.status_code} {deleted.text}"
    )

    bundles = engine_access.identify_bundles(ws_id)
    roots = {b.root_document_id for b in bundles}
    assert doc_id in roots, (
        f"엔진이 API 커밋된 삭제를 관찰해 삭제 문서를 묶음 루트로 식별해야 한다: "
        f"삭제 id={doc_id}, 식별된 루트={sorted(roots)}"
    )
