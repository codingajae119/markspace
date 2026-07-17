"""보관 이동↔완전삭제 결합 스위트 — deleted 관측 → 보관 이동·물리삭제 부재·멱등·묶음 범위
(Task 2.3 / Req 4.1·4.2·4.3·4.4·4.5, design §PurgeArchiveCombinationSuite, §System Flows
"보관 이동 ↔ 완전삭제 (8.6)"; s12 8.6·INV-4 교차참조).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕**s12** 첨부 라우터·아카이브
스케줄러 조립, `app.main.create_app`) 위에서, **실제** s07/s10 완전삭제·보관 만료 경로를 통과해
`document.status='deleted'` 가 된 결과에 s12 `ArchivalSweepService` 가 반응함을 mock 없이 결합
검증한다. 저장/보관 루트만 tmp 로 격리(`tmp_attachment_roots`)해 디스크상 이동을 실제
파일시스템으로 관찰한다.

핵심 seam(8.6): s12 는 상태 전이를 **소유하지 않는다** — 문서를 곧장 `status='deleted'` 로
세팅하는 지름길이 아니라, 두 실제 경로

  (A) 완전삭제: 첨부 업로드 → `DELETE /documents/{id}`(trashed 캐스케이드) →
      `DELETE /trash/{bundleId}`(purge → deleted) → `run_archival_sweep(now)`
  (B) 보관 만료: 첨부 업로드 → `DELETE /documents/{id}`(trashed) → trashed_at 만료 핀 →
      `RetentionSweepService.sweep(now)`(→ deleted) → `run_archival_sweep(now)`

를 태워, s10/s07 이 만든 관측 가능한 결과(문서 status='deleted')에만 s12 가 반응함을 보인다.
두 deleted 경로 모두 동일하게 첨부를 보관 이동(`is_archived=true`·파일 이동)함을 확인한다(Req 4.1·4.2).

이 스위트는 8.6 완전삭제 반응 seam 만 격리하기 위해 **일반 파일 첨부(`kind=file`)** 를 쓴다 —
`kind=file` 은 8.7 참조 소멸 스코프(image 한정)에서 제외되므로 이 첨부를 보관 이동시킬 수 있는
경로는 오직 8.6 완전삭제 반응뿐이다(관측 판정·묶음 범위 단언을 8.7 간섭 없이 결정적으로 만든다).

검증 항목(design §PurgeArchiveCombinationSuite):
- **완전삭제 경로(4.1)**·**물리 삭제 부재(4.3, INV-4)**·**관측 판정(4.4)**:
  :func:`test_purge_path_archives_and_moves_file`.
- **보관 만료 경로(4.2)** — retention 스윕이 만든 deleted 에도 동일 반응:
  :func:`test_retention_expiry_path_archives_identically`.
- **관측 판정(4.4)** — 비deleted(active/trashed) 문서 첨부는 미대상:
  :func:`test_only_deleted_document_attachments_are_archived`.
- **멱등·묶음 범위(4.5)** — 반복 스윕 skip·묶음 내 deleted 문서 첨부만 이동·비deleted 불변:
  :func:`test_idempotent_and_bundle_scope`.

DB 관찰은 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로 커밋된 행을 신규 세션에서 직접
조회한다. function-scope 하네스가 매 테스트마다 마이그레이션을 새로 수행하므로 아카이브 스윕
처리 건수는 결정적이다(누적 오염 없음). deleted 유발은 항상 실제 완전삭제·retention 스윕으로만
하며(임의 DB status 조작 금지), 스윕·엔진 직접 호출은 실제 s12·s10·s07 코드 실행이다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드·conftest·helpers·하네스는 건드리지 않고
재사용만 한다. 재검증 트리거: s01/s02/s03/s05/s07/s09/s10/s12 중 하나라도 수정되면 이
체크포인트를 누적 집합 기준으로 재실행한다(s01 수정 시 모든 체크포인트 재실행).
"""

from datetime import datetime, timedelta

from app.models import Document
from tests.integration_L5 import helpers as h

# 업로드 바이너리(일반 파일 첨부; kind=file 은 8.7 참조 소멸(image 한정)에서 제외되므로
# 이 첨부를 보관 이동시킬 수 있는 경로는 오직 8.6 완전삭제 반응뿐이다 — seam 을 명확히 격리).
_FILE_BYTES = b"%PDF-1.4 l5-purge-archive-combination-payload\n%%EOF"

# 아카이브 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 8.6 은 now 에 의존하지 않으나
# 배치 계약 일관성상 API 가 받는다. 완전삭제 경로 테스트에서 사용한다.
_NOW = datetime(2026, 7, 17, 12, 0, 0)


def _upload_file(client, document_id, *, filename="doc.pdf", content=_FILE_BYTES):
    """editor 세션으로 대상 문서에 일반 파일 첨부를 업로드하고 첨부 id 를 반환한다(SETUP).

    L5 `helpers.upload_file` 로 명시 `kind=file` 업로드(201 단언)를 태운다 — 8.7 참조 소멸
    스코프(image 한정)에서 제외되어 8.6 완전삭제 반응만이 보관 경로가 되도록 한다.
    """
    att = h.upload_file(client, document_id, content=content, filename=filename)
    return att["id"]


def _status_of(harness, document_id):
    """부팅 앱과 동일 세션 팩토리로 문서 행의 `status` 를 신규 세션으로 직접 관측한다(없으면 None).

    doc_tree_scenario 경로에는 `status_of` 편의가 없으므로, deleted 전이가 s07/s10 purge 가 만든
    관측 가능한 결과임을 확인하기 위해 커밋된 문서 status 를 직접 읽는다(관측 판정, Req 4.4).
    """
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.status


def _drive_document_to_deleted(scenario, document_id, workspace_id):
    """실제 s07/s10 완전삭제 경로로 문서를 `status='deleted'` 로 만든다(지름길 아님, Req 4.4).

    1. editor 가 `DELETE /documents/{id}`(L3) → 대상 문서(및 하위 트리)가 trashed 캐스케이드.
    2. editor 가 `GET /workspaces/{id}/trash`(L4)로 이 문서를 루트로 하는 묶음을 찾는다.
    3. editor 가 `DELETE /trash/{bundleId}`(L4 purge, **비가역**) → 묶음 구성원 전체가 deleted 종착.

    s12 는 이 전이를 소유하지 않는다 — s10/s07 이 만든 deleted 상태를 뒤에서 관측할 뿐이다.
    """
    editor = scenario.editor_client
    h.l3_helpers.delete_document(editor, document_id)

    trash = h.l4_helpers.list_trash(editor, workspace_id)
    bundle = next(
        item for item in trash["items"] if item["root_document_id"] == document_id
    )
    h.l4_helpers.purge_bundle_via_api(editor, bundle["bundle_id"])


# =============================================================================
# 1) 완전삭제 경로 — deleted 관측 → 보관 이동·is_archived·물리 이동(INV-4)·관측 판정 (4.1·4.3·4.4)
# =============================================================================


def test_purge_path_archives_and_moves_file(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """완전삭제로 deleted 가 된 문서의 첨부가 실제 스윕으로 보관 이동됨을 검증한다
    (Req 4.1·4.3·4.4, INV-4).

    - **관측 판정 — 전(Req 4.4)**: deleted 전이는 s07/s10 purge 가 만들었고, 아카이브 스윕
      **전** 문서 status 가 이미 'deleted' 다(s12 가 전이를 수행하지 않음).
    - **보관 이동(Req 4.1)**: 스윕 후 `is_archived=true`·DB `file_path` 가 보관 루트 하위 WS
      격리 상대 경로로 갱신된다.
    - **물리 삭제 부재(Req 4.3·INV-4)**: 파일이 보관 위치에 원본 바이트로 **존재**하고(삭제 아님)
      저장 위치에서는 사라진다(이동일 뿐).
    - **관측 판정 — 후(Req 4.4)**: 스윕 **후**에도 문서 status 는 여전히 'deleted'(s12 는 문서
      상태를 바꾸지 않는다 — 반응만).
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client

    att_id = _upload_file(editor, doc_id)

    # 업로드 직후: 미보관·저장 루트에 물리 파일 존재(이동의 출발점).
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "업로드 직후 첨부는 미보관이어야 한다"
    )
    stored_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert stored_rel_path is not None, "업로드 첨부의 저장 file_path 가 커밋되어 있어야 한다"
    h.assert_ws_isolated(stored_rel_path, ws_id)
    stored_file = h.assert_stored(tmp_attachment_roots, stored_rel_path)
    assert stored_file.read_bytes() == _FILE_BYTES, "저장 파일 바이트가 업로드와 일치해야 한다"

    # 실제 완전삭제 경로로 deleted 전이(s07/s10 purge — s12 지름길 아님).
    _drive_document_to_deleted(doc_tree_scenario.scenario, doc_id, ws_id)

    # (관측 판정 — 전) 스윕 이전에 문서는 이미 deleted 다(s12 전이 미수행, Req 4.4).
    assert _status_of(harness, doc_id) == "deleted", (
        "아카이브 스윕 이전에 문서는 이미 s10/s07 purge 로 deleted 여야 한다(s12 전이 미수행)"
    )
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "완전삭제만으로는 첨부가 아직 보관되지 않는다(스윕이 반응해야 보관됨)"
    )

    # s12 아카이브 스윕 1회 — 부팅 앱과 동일 세션 팩토리로 실제 ArchivalSweepService 구동.
    processed = h.run_archival_sweep(archival_sweep, _NOW)
    assert processed == 1, (
        f"deleted 문서의 미보관 첨부 1건만 보관 이동되어야 한다(결정적 하네스): {processed}"
    )

    # (보관 이동 — DB) is_archived=true·file_path 가 보관 루트 하위 WS 격리 상대 경로로 갱신(Req 4.1).
    assert h.attachment_is_archived(harness.session_local, att_id) is True, (
        "완전삭제 반응으로 첨부는 보관됨(is_archived=true)"
    )
    archived_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert archived_rel_path is not None
    h.assert_ws_isolated(archived_rel_path, ws_id)

    # (물리 삭제 부재 — 디스크·INV-4) 보관 위치에 원본 바이트로 존재, 저장 위치에서는 소멸.
    archived_file = h.assert_archived(tmp_attachment_roots, archived_rel_path)
    assert archived_file.read_bytes() == _FILE_BYTES, (
        "보관된 파일 내용은 원본과 동일해야 한다(이동일 뿐 삭제·훼손 아님, INV-4)"
    )
    h.assert_not_stored(tmp_attachment_roots, stored_rel_path)

    # (관측 판정 — 후) s12 스윕은 문서 전이를 수행하지 않는다 — 여전히 deleted(Req 4.4).
    assert _status_of(harness, doc_id) == "deleted", (
        "s12 스윕은 문서 전이를 수행하지 않으므로 스윕 후에도 status 는 deleted 여야 한다"
    )


# =============================================================================
# 2) 보관 만료 경로 — retention 스윕이 만든 deleted 에도 동일 보관 이동 (4.2)
# =============================================================================


def test_retention_expiry_path_archives_identically(
    trash_scenario, sweep_access, archival_sweep, harness, tmp_attachment_roots
):
    """보관 만료 자동 영구삭제(retention 스윕)로 deleted 가 된 문서의 첨부도 완전삭제 경로와
    **동일하게** 보관 이동됨을 검증한다(Req 4.2 — 두 deleted 경로 모두 관측으로 반응).

    deleted 전이는 임의 DB status 조작이 아니라 **실제** `now` 주입 `RetentionSweepService.sweep`
    가 만든다:

    1. trash_scenario 워크스페이스(retention=30)에 새 문서 D 를 만들고(active) 파일 첨부 업로드.
    2. editor 가 `DELETE /documents/{id}` 로 D 를 trashed.
    3. D 의 `trashed_at` 을 기준시각 40일 전으로 핀(만료; retention 30 초과) — trash_scenario 의
       `pin_trashed_at`(직접 DB 시드) 재사용. 스윕 서비스는 trashed_at 을 쓰지 않는다.
    4. `sweep_access.sweep(reference)`(실제 s10 retention 스윕)로 D 를 deleted 전이(관측 판정).
    5. `run_archival_sweep(reference)`(실제 s12 아카이브 스윕)로 D 의 첨부가 보관 이동됨을 관찰.

    결과가 완전삭제 경로와 동일함을 파일시스템(보관 위치 존재·저장 위치 소멸)·DB(is_archived)로
    확인한다.
    """
    ws_id = trash_scenario.workspace_id
    editor = trash_scenario.editor_client
    now = trash_scenario.reference

    # (1) 활성 문서 D + 파일 첨부(업로드는 삭제 이전에 — deleted 문서엔 업로드 불가).
    doc = h.l3_helpers.create_document(editor, ws_id, "보관만료-대상문서")
    doc_id = doc["id"]
    att_id = _upload_file(editor, doc_id)
    stored_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert stored_rel_path is not None
    h.assert_stored(tmp_attachment_roots, stored_rel_path)

    # (2) trashed 전이(실제 s07 DELETE), (3) 만료 핀(직접 DB 시드 — 스윕은 trashed_at 미기록).
    h.l3_helpers.delete_document(editor, doc_id)
    assert trash_scenario.status_of(doc_id) == "trashed", (
        "완전삭제 이전 D 는 trashed 상태여야 한다(retention 스윕 대상)"
    )
    trash_scenario.pin_trashed_at([doc_id], now - timedelta(days=40))

    # (4) 실제 retention 스윕이 D 를 deleted 로 전이(임의 status 조작 아님).
    h.l4_helpers.run_sweep(sweep_access, now)
    assert trash_scenario.status_of(doc_id) == "deleted", (
        "만료 묶음은 실제 RetentionSweepService 로 deleted 전이되어야 한다(임의 DB 조작 아님, Req 4.2)"
    )
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "retention 전이만으로는 첨부가 아직 보관되지 않는다(s12 스윕이 반응해야 함)"
    )

    # (5) 실제 아카이브 스윕 — 만료로 deleted 된 문서의 첨부도 동일하게 보관 이동.
    processed = h.run_archival_sweep(archival_sweep, now)
    assert processed == 1, (
        f"보관 만료로 deleted 된 문서의 미보관 첨부 1건만 보관 이동되어야 한다: {processed}"
    )

    # (완전삭제 경로와 동일 결과) is_archived=true·보관 위치 존재·저장 위치 소멸(INV-4).
    assert h.attachment_is_archived(harness.session_local, att_id) is True, (
        "보관 만료 경로의 deleted 문서 첨부도 보관됨(is_archived=true, 두 경로 동일 반응)"
    )
    archived_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert archived_rel_path is not None
    h.assert_ws_isolated(archived_rel_path, ws_id)
    archived_file = h.assert_archived(tmp_attachment_roots, archived_rel_path)
    assert archived_file.read_bytes() == _FILE_BYTES, (
        "보관 만료 경로에서도 파일은 이동일 뿐 원본 바이트로 존재해야 한다(INV-4)"
    )
    h.assert_not_stored(tmp_attachment_roots, stored_rel_path)


# =============================================================================
# 3) 관측 판정 — deleted 문서 첨부만 이동·비deleted(active/trashed) 첨부 불변 (4.4)
# =============================================================================


def test_only_deleted_document_attachments_are_archived(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """s12 는 deleted 전이를 수행하지 않고 `document.status='deleted'` 관측으로만 보관을
    판정하므로, 같은 스윕 실행에서 비deleted(active/trashed) 문서의 첨부는 이동 대상이 아님을
    검증한다(Req 4.4, 관측 기반 조정).

    동일 워크스페이스·동일 editor 로 세 독립 문서를 두고 각각 파일 첨부를 업로드한다:
    - DEL: 완전삭제(purge)로 `status='deleted'` → 스윕이 첨부를 보관 이동해야 한다.
    - TR : trashed(완전삭제 안 함) → deleted 아님 → 스윕이 첨부를 건드리면 안 된다.
    - ACT: active(삭제 안 함) → deleted 아님 → 스윕이 첨부를 건드리면 안 된다.

    한 번의 스윕이 오직 DEL 의 첨부만 보관 이동(처리 1)하고 TR·ACT 첨부는 미보관·저장 위치
    존속임을 DB·파일시스템으로 확인한다.
    """
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client

    del_doc = h.l3_helpers.create_document(editor, ws_id, "관측-완전삭제")
    tr_doc = h.l3_helpers.create_document(editor, ws_id, "관측-휴지통")
    act_doc = h.l3_helpers.create_document(editor, ws_id, "관측-활성")

    del_att = _upload_file(editor, del_doc["id"], filename="del.pdf")
    tr_att = _upload_file(editor, tr_doc["id"], filename="tr.pdf")
    act_att = _upload_file(editor, act_doc["id"], filename="act.pdf")

    del_stored = h.attachment_file_path(harness.session_local, del_att)
    tr_stored = h.attachment_file_path(harness.session_local, tr_att)
    act_stored = h.attachment_file_path(harness.session_local, act_att)

    # DEL → deleted(실제 purge), TR → trashed(완전삭제 없음), ACT → active(그대로).
    _drive_document_to_deleted(doc_tree_scenario.scenario, del_doc["id"], ws_id)
    h.l3_helpers.delete_document(editor, tr_doc["id"])

    assert _status_of(harness, del_doc["id"]) == "deleted"
    assert _status_of(harness, tr_doc["id"]) == "trashed"
    assert _status_of(harness, act_doc["id"]) == "active"

    # 스윕: 오직 deleted 문서(DEL)의 첨부만 보관 이동 대상(관측 판정).
    processed = h.run_archival_sweep(archival_sweep, _NOW)
    assert processed == 1, (
        f"deleted 문서(DEL)의 첨부 1건만 보관 이동되어야 한다(비deleted 미대상): {processed}"
    )

    # DEL 첨부: 보관됨·보관 위치 존재·저장 위치 소멸.
    assert h.attachment_is_archived(harness.session_local, del_att) is True, (
        "deleted 문서 첨부는 보관되어야 한다(관측 판정)"
    )
    h.assert_archived(
        tmp_attachment_roots, h.attachment_file_path(harness.session_local, del_att)
    )
    h.assert_not_stored(tmp_attachment_roots, del_stored)

    # TR·ACT 첨부: 미보관·file_path 불변·저장 위치 존속(비deleted 는 스윕이 건드리지 않음).
    for name, att_id, stored in (("trashed", tr_att, tr_stored), ("active", act_att, act_stored)):
        assert h.attachment_is_archived(harness.session_local, att_id) is False, (
            f"{name} 문서 첨부는 deleted 아니므로 보관되면 안 된다(관측 판정, Req 4.4)"
        )
        assert h.attachment_file_path(harness.session_local, att_id) == stored, (
            f"{name} 문서 첨부의 file_path 는 스윕에 의해 바뀌면 안 된다"
        )
        h.assert_stored(tmp_attachment_roots, stored)
        h.assert_not_archived(tmp_attachment_roots, stored)


# =============================================================================
# 4) 멱등·묶음 범위 — 반복 스윕 skip·묶음 내 deleted 문서 첨부만 이동·비deleted 불변 (4.5)
# =============================================================================


def test_idempotent_and_bundle_scope(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """반복 스윕 멱등성과 묶음 범위를 검증한다(Req 4.5).

    - **묶음 범위**: doc_tree_scenario 트리(루트→자식→손자)의 루트를 삭제·완전삭제하면 묶음
      구성원(루트+자식+손자) 전체가 deleted 종착한다. 루트·자식에 파일 첨부를 두고, 묶음과
      무관한 **별도 active 문서**에도 파일 첨부를 둔다. 첫 스윕은 deleted 묶음의 두 첨부(루트·
      자식)만 보관 이동(처리 2)하고, active 문서 첨부는 불변이어야 한다.
    - **멱등성**: 두 번째 스윕은 이미 보관된 첨부를 다시 이동하거나 오류를 내지 않고 건너뛴다
      (처리 0). 보관 파일은 그대로 원본 바이트로 남고 active 첨부도 여전히 불변이다.
    """
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client
    root_id = doc_tree_scenario.root_id
    child_id = doc_tree_scenario.child_id

    # 묶음(루트+자식)의 두 문서에 파일 첨부(삭제 이전 업로드). 손자는 첨부 없음.
    root_att = _upload_file(editor, root_id, filename="root.pdf")
    child_att = _upload_file(editor, child_id, filename="child.pdf")

    # 묶음과 무관한 별도 active 문서 + 파일 첨부(묶음 범위 밖 — 불변이어야 함).
    active_doc = h.l3_helpers.create_document(editor, ws_id, "범위밖-활성")
    active_att = _upload_file(editor, active_doc["id"], filename="active.pdf")

    root_stored = h.attachment_file_path(harness.session_local, root_att)
    child_stored = h.attachment_file_path(harness.session_local, child_att)
    active_stored = h.attachment_file_path(harness.session_local, active_att)

    # 루트 삭제(자식·손자 캐스케이드) → purge → 묶음 구성원 전체 deleted.
    _drive_document_to_deleted(doc_tree_scenario.scenario, root_id, ws_id)
    assert _status_of(harness, root_id) == "deleted"
    assert _status_of(harness, child_id) == "deleted", (
        "완전삭제 묶음은 구성원(자식) 전체가 deleted 종착해야 한다"
    )
    assert _status_of(harness, active_doc["id"]) == "active", (
        "묶음 밖 별도 문서는 완전삭제에 영향받지 않아야 한다"
    )

    # (묶음 범위 — 첫 스윕) deleted 묶음의 루트·자식 첨부 2건만 이동, active 첨부 불변.
    first = h.run_archival_sweep(archival_sweep, _NOW)
    assert first == 2, (
        f"완전삭제 묶음의 deleted 문서 첨부 2건(루트·자식)만 보관 이동되어야 한다: {first}"
    )

    for att_id, stored in ((root_att, root_stored), (child_att, child_stored)):
        assert h.attachment_is_archived(harness.session_local, att_id) is True, (
            "묶음 내 deleted 문서 첨부는 보관되어야 한다"
        )
        h.assert_archived(
            tmp_attachment_roots, h.attachment_file_path(harness.session_local, att_id)
        )
        h.assert_not_stored(tmp_attachment_roots, stored)

    # (묶음 범위 밖) active 문서 첨부는 불변(미보관·file_path·저장 위치 유지).
    assert h.attachment_is_archived(harness.session_local, active_att) is False, (
        "묶음 밖 active 문서 첨부는 보관되면 안 된다(묶음 범위, Req 4.5)"
    )
    assert h.attachment_file_path(harness.session_local, active_att) == active_stored
    h.assert_stored(tmp_attachment_roots, active_stored)

    # 첫 스윕 이후 보관 첨부의 보관 경로·바이트 스냅샷(멱등 대조 기준).
    root_archived = h.attachment_file_path(harness.session_local, root_att)
    child_archived = h.attachment_file_path(harness.session_local, child_att)
    root_bytes_before = h.assert_archived(tmp_attachment_roots, root_archived).read_bytes()

    # (멱등성 — 두 번째 스윕) 이미 보관된 첨부는 스코프에서 제외 → 재이동 없음(처리 0).
    second = h.run_archival_sweep(archival_sweep, _NOW)
    assert second == 0, (
        f"이미 보관된 첨부는 스코프에서 제외되어 두 번째 스윕은 0 을 반환해야 한다(멱등): {second}"
    )

    # 더블 무브·훼손 없음: file_path 불변·보관 파일 원본 바이트 존속·active 여전히 불변.
    assert h.attachment_file_path(harness.session_local, root_att) == root_archived, (
        "멱등 스윕은 보관 첨부의 file_path 를 재이동으로 바꾸면 안 된다"
    )
    assert h.attachment_file_path(harness.session_local, child_att) == child_archived
    archived_file = h.assert_archived(tmp_attachment_roots, root_archived)
    assert archived_file.read_bytes() == root_bytes_before == _FILE_BYTES, (
        "멱등 스윕 후에도 보관 파일 내용은 불변이어야 한다(더블 무브·훼손 없음)"
    )
    assert h.attachment_is_archived(harness.session_local, active_att) is False, (
        "멱등 스윕 후에도 묶음 밖 active 첨부는 미보관으로 유지되어야 한다"
    )
    h.assert_stored(tmp_attachment_roots, active_stored)
