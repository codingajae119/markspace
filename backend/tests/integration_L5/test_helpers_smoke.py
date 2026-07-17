"""L5 헬퍼 스모크 — Task 1.2 관찰 가능 완료 기준 (Req 1.4·3.1·4.1·5.1·6.1, design §Helpers).

이 스위트는 태스크 1.2 헬퍼(`tests/integration_L5/helpers.py`)가 실제 결합 환경(L4 헬퍼
재사용 + s12 첨부 업로드/서빙·이미지 참조 저장·아카이브 스윕·파일시스템 관찰 래퍼)을
제공하는지 mock 없이 확인한다("역-RED": 새 테스트가 실제 구현 위에서 **통과**하는 것이 검증).
관찰 가능 완료 기준(tasks.md 1.2):

1. 헬퍼로 editor 가 이미지를 업로드(:func:`~tests.integration_L5.helpers.upload_image`)하고
   참조 본문으로 저장(:func:`~tests.integration_L5.helpers.save_with_reference`)한 뒤
   ``GET /attachments/{id}``(:func:`~tests.integration_L5.helpers.get_attachment`)가 업로드한
   바이너리를 돌려주고, 파일시스템 관찰 헬퍼가 저장 파일이 WS 격리 경로(`{workspace_id}/`)에
   존재함을 보고한다.
2. 첨부 연결 문서를 완전삭제(L4 휴지통 헬퍼 재사용)해 ``deleted`` 로 전이시킨 뒤 아카이브 스윕
   헬퍼(:func:`~tests.integration_L5.helpers.run_archival_sweep`)가 ``now`` 주입 호출로 처리
   건수(int)를 반환하고, 파일시스템 관찰 헬퍼가 보관 경로의 파일 존재를 보고한다.

L4(및 그것이 재사용하는 L3/L2/L1) 헬퍼를 재사용·확장하며 애플리케이션 코드·config.yml·하위
하네스는 만지지 않는다. mock·stub·pytest.skip 미사용. 저장/보관 루트는 ``tmp_attachment_roots``
로 격리해 실제 ``./var/attachments`` 를 오염시키지 않는다. 함수-스코프 하네스가 매 테스트마다
마이그레이션을 새로 수행하므로 스윕 건수는 결정적이다(누적 오염 없음).
"""

from datetime import datetime

from tests.integration_L5 import helpers as h

# 업로드 스모크 바이너리(작은 PNG 시그니처 + 페이로드; 25MiB 한도 이하라 저장/서빙 경로만 검증).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l5-helpers-smoke-image-payload"
# 일반 파일 바이너리(kind=file 은 8.7 image 한정 스코프 밖 → 8.6 완전삭제 반응만이 보관 경로).
_FILE_BYTES = b"%PDF-1.4 l5-helpers-smoke-file-payload\n%%EOF"

# 아카이브 스윕에 주입할 고정 기준 시각(결정성; 마이크로초 0, DATETIME(0) 정합).
_SWEEP_NOW = datetime(2026, 7, 17, 0, 0, 0)


# =============================================================================
# (1) 업로드·이미지 참조 저장·서빙·저장 파일 관찰 (관찰 가능 완료 ①)
# =============================================================================


def test_upload_reference_serve_and_stored_file_observed(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """헬퍼 왕복: 이미지 업로드 → 참조 본문 저장 → 바이너리 서빙 → 저장 파일 WS 격리 관찰.

    - :func:`~tests.integration_L5.helpers.upload_image` 가 201 을 단언하고 파싱된
      ``AttachmentRead`` dict(url=`/attachments/{id}`·kind=image)를 반환한다.
    - :func:`~tests.integration_L5.helpers.save_with_reference` 가 잠금→저장(L4 재사용)으로
      현재 버전 본문에 `/attachments/{id}` 토큰을 남긴다.
    - :func:`~tests.integration_L5.helpers.get_attachment` 가 200 + 업로드 바이너리를 돌려준다.
    - 파일시스템 헬퍼가 저장 파일이 `{workspace_id}/` 하위에 물리적으로 존재함을 보고한다.
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    att = h.upload_image(editor, doc_id, content=_IMAGE_BYTES, filename="paste.png")
    att_id = att["id"]
    assert att["url"] == f"/attachments/{att_id}", "url 은 /attachments/{id} 파생 규약"
    assert att["kind"] == "image", "image/png 업로드 kind=image"

    # 현재 버전 본문에 참조 토큰을 남기는 저장(잠금→저장, L4 재사용). 반환은 버전 dict.
    version = h.save_with_reference(editor, doc_id, att_id)
    assert version["id"], "save_with_reference 는 새 버전 dict 를 돌려줘야 한다"

    # 응답 url 로 viewer 가 바이너리를 왕복 조회(서빙 헬퍼는 200 단언 후 Response 반환).
    serve = h.get_attachment(viewer, att_id)
    assert serve.content == _IMAGE_BYTES, "업로드한 정확한 바이너리를 돌려받아야 한다"

    # DB rel path 조회 + 파일시스템 관찰(저장 루트·WS 격리).
    rel = h.attachment_file_path(harness.session_local, att_id)
    assert rel is not None, "커밋된 첨부의 file_path 를 읽을 수 있어야 한다"
    h.assert_stored(tmp_attachment_roots, rel)
    h.assert_ws_isolated(rel, ws_id)
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "업로드 직후 첨부는 미보관"
    )


def test_save_without_reference_produces_unreferenced_current_version(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """:func:`~tests.integration_L5.helpers.save_without_reference` 는 참조 토큰이 없는 현재
    버전을 만든다(참조 소멸 구성용). 반환된 버전 본문에 `/attachments/` 토큰이 없어야 한다.
    """
    doc_id = doc_tree_scenario.child_id
    editor = doc_tree_scenario.editor_client

    version = h.save_without_reference(editor, doc_id, content="본문 텍스트")
    assert "/attachments/" not in version.get("content", ""), (
        "save_without_reference 본문에는 첨부 참조 토큰이 없어야 한다"
    )


# =============================================================================
# (2) 완전삭제 → 아카이브 스윕 → 보관 파일 관찰 (관찰 가능 완료 ②)
# =============================================================================


def test_purge_then_archival_sweep_reports_archived_file(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """첨부 연결 문서를 완전삭제(L4 재사용)로 deleted 전이시킨 뒤 아카이브 스윕 헬퍼가 처리
    건수(int)를 반환하고, 파일시스템 헬퍼가 보관 경로의 파일 존재를 보고한다(8.6, INV-4).

    - 일반 파일(kind=file)을 업로드해 8.6 완전삭제 반응만이 보관 경로가 되도록 격리한다.
    - `DELETE /documents/{id}`(trashed) → 휴지통 묶음 조회 → `DELETE /trash/{bundleId}`(deleted)
      까지 L4/L3 헬퍼로 진행한다(임의 DB 조작 금지 — 실제 s07/s10 경로).
    - :func:`~tests.integration_L5.helpers.run_archival_sweep` 가 ``now`` 주입으로 스윕을 1회
      구동하고 처리 건수를 반환한다.
    - 스윕 후 `is_archived=true`·file_path 가 보관 루트 하위를 가리키고, 파일이 보관 위치에
      물리적으로 존재한다(이동일 뿐 삭제 아님).
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.grandchild_id
    editor = doc_tree_scenario.editor_client

    att = h.upload_file(editor, doc_id, content=_FILE_BYTES, filename="doc.pdf")
    att_id = att["id"]

    # 저장 루트에 사전 존재(이동의 출발점).
    stored_rel = h.attachment_file_path(harness.session_local, att_id)
    h.assert_stored(tmp_attachment_roots, stored_rel)

    # 실제 s07/s10 경로로 deleted 전이(L4/L3 재사용). 손자는 단독 묶음(루트=자기 자신).
    h.l3_helpers.delete_document(editor, doc_id)
    trash = h.l4_helpers.list_trash(editor, ws_id)
    bundle = next(
        item for item in trash["items"] if item["root_document_id"] == doc_id
    )
    h.l4_helpers.purge_bundle_via_api(editor, bundle["bundle_id"])

    # 아카이브 스윕 1회(now 주입) — deleted 문서의 미보관 첨부 1건이 보관 이동된다.
    processed = h.run_archival_sweep(archival_sweep, _SWEEP_NOW)
    assert isinstance(processed, int), "아카이브 스윕은 처리 건수(int)를 반환해야 한다"
    assert processed >= 1, (
        f"deleted 문서의 미보관 첨부가 보관 이동되어야 한다(결정적 하네스): {processed}"
    )

    # DB + 파일시스템 관찰: 보관 이동 + WS 격리 + 저장 위치 소멸.
    assert h.attachment_is_archived(harness.session_local, att_id) is True, (
        "완전삭제 반응으로 첨부는 보관됨(is_archived=true)"
    )
    archived_rel = h.attachment_file_path(harness.session_local, att_id)
    h.assert_archived(tmp_attachment_roots, archived_rel)
    h.assert_ws_isolated(archived_rel, ws_id)
    h.assert_not_stored(tmp_attachment_roots, stored_rel)


# 미사용 경고 방지 + 재-export 확인(후속 스위트가 한 지점에서 L4/L3 헬퍼에 도달).
assert h.l4_helpers is not None
assert h.l3_helpers is not None
