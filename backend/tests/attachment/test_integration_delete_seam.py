"""완전삭제 반응 보관 이동 seam 통합 테스트 (8.6)
(Task 4.2 / Req 4.1, 4.2, 4.3, 4.4, 6.2, 6.3, 6.4, 7.7).

design.md §Testing Strategy "완전삭제 반응 보관 이동(8.6, 핵심 seam)"·§System Flows "완전삭제
반응 보관 이동 (8.6) — deleted 상태 관측" 을 **마이그레이션된 실제 DB + 부팅 앱**(첨부 라우터 +
휴지통·문서 라우트 조립, `app.main.create_app`) 위에서 검증한다. mock 없이
s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12 를 결합한 L3 하네스(`tests/attachment/conftest.py`
재-import)를 쓰며, 저장/보관 루트를 tmp 로 격리해(``tmp_attachment_roots``) 디스크상 이동을
실제로 관찰한다.

핵심은 **실제 s07/s10 완전삭제 경로를 통과한 deleted 상태**에 s12 스윕이 반응하는 seam 이다.
문서를 곧장 `status='deleted'` 로 세팅하는 지름길이 아니라, 실제 API 로

    첨부 업로드 → `DELETE /documents/{id}`(trashed 캐스케이드) → 휴지통 묶음 조회 →
    `DELETE /trash/{bundleId}`(purge → deleted) → `archival_sweep.sweep(now)`

경로를 태워 s10/s07 이 만든 관측 가능한 결과(문서 status='deleted')에만 s12 가 반응함을 보인다.
검증 항목:

- **8.6 archive-move seam (Req 4.1/4.2)**: 스윕 후 첨부가 `is_archived=true`·`file_path` 가
  보관 루트 하위를 가리키고, 물리 파일이 보관 위치에 원본 바이트로 **존재**하며(INV-4, 삭제 아님)
  저장 루트에서는 사라진다.
- **보관 비노출 role-agnostic 404 (Req 6.2/6.3, INV-7)**: 보관 후 `GET /attachments/{id}` 가
  viewer·owner·admin 모두 404(요청자 role 무관 비노출).
- **영구성·복원 부재 (Req 6.4, INV-7)**: 반복 조회가 계속 404 이고 첨부가 계속 보관 상태이며,
  보관 첨부를 active 로 되돌리는 애플리케이션 경로가 없음(un-archive 엔드포인트 부재).
- **멱등성 (Req 4.4)**: 두 번째 스윕은 이 첨부를 다시 이동하지 않는다(반환 0·파일 불변·계속 404).
- **관측 전용 (Req 7.7)**: deleted 전이는 s07/s10 purge 경로가 만들었고 s12 스윕은 반응만 한다
  — 문서 status 가 스윕 **전·후 모두** 'deleted' 로 s12 가 전이를 수행하지 않음을 보인다.

DB 관찰은 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로 커밋된 행을 신규 세션에서 직접
조회한다. function-scope 하네스가 매 테스트마다 마이그레이션을 새로 수행하므로 스윕 건수는
결정적이다(누적 오염 없음).
"""

from datetime import datetime

from app.models import Attachment, Document
from tests.integration_L3 import helpers as l3_helpers
from tests.integration_L4 import helpers as l4_helpers

# 업로드 바이너리(일반 파일 첨부; kind=file 은 8.7 참조 소멸 스코프(image 한정)에서 제외되므로
# 이 첨부를 보관 이동시킬 수 있는 경로는 오직 8.6 완전삭제 반응뿐이다 — seam 을 명확히 격리).
_FILE_BYTES = b"%PDF-1.4 delete-seam-archive-payload\n%%EOF"

# 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 8.6 은 now 에 의존하지 않으나 API 가 받는다.
_NOW = datetime(2026, 7, 17, 12, 0, 0)


def _upload_file(client, document_id, *, filename="doc.pdf", data=_FILE_BYTES):
    """``POST /documents/{id}/attachments`` 로 일반 파일 첨부를 업로드하고 응답을 반환한다.

    파일 필드명은 계약상 ``file`` 이며, 명시 ``kind=file`` 로 일반 파일 종류를 강제한다(8.7 참조
    소멸 스코프에서 제외 → 8.6 seam 만이 보관 이동 경로가 되도록).
    """
    return client.post(
        f"/documents/{document_id}/attachments",
        files={"file": (filename, data, "application/pdf")},
        data={"kind": "file"},
    )


def _drive_document_to_deleted(scenario, document_id, workspace_id):
    """실제 s07/s10 경로로 문서를 ``status='deleted'`` 로 만든다(지름길 아님).

    1. editor 가 `DELETE /documents/{id}` → 대상 문서(및 하위 트리)가 trashed 캐스케이드.
    2. editor 가 `GET /workspaces/{id}/trash` 로 휴지통 묶음을 조회해 이 문서를 루트로 하는
       묶음(bundle_id = root_document_id)을 찾는다.
    3. editor 가 `DELETE /trash/{bundleId}`(purge, **비가역**) → 묶음 구성원 전체가 deleted 종착.

    s12 는 이 전이를 소유하지 않는다 — s10/s07 이 만든 deleted 상태를 뒤에서 관측할 뿐이다.
    """
    editor = scenario.editor_client
    l3_helpers.delete_document(editor, document_id)

    trash = l4_helpers.list_trash(editor, workspace_id)
    bundle = next(
        item for item in trash["items"] if item["root_document_id"] == document_id
    )
    l4_helpers.purge_bundle_via_api(editor, bundle["bundle_id"])


def _archive_seam_setup(doc_tree_scenario, harness):
    """첨부 업로드 → 소속 문서 완전삭제(deleted) 까지 진행하고 관측 값을 돌려준다.

    반환: ``(att_id, doc_id, stored_rel_path)``.
    - ``att_id``: 업로드한 첨부 id.
    - ``doc_id``: 첨부가 연결된(그리고 deleted 로 전이된) 문서 id.
    - ``stored_rel_path``: 스윕 **전** DB `file_path`(= 저장 루트 기준 상대 경로). 스윕 후 이
      경로가 저장 루트에서 사라지고 보관 루트에서 나타남을 대조하는 데 쓴다.
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client

    created = _upload_file(editor, doc_id)
    assert created.status_code == 201, (
        f"editor 파일 업로드 201: {created.status_code} {created.text}"
    )
    att_id = created.json()["id"]

    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is False, "업로드 직후 첨부는 미보관"
        stored_rel_path = att.file_path

    _drive_document_to_deleted(doc_tree_scenario.scenario, doc_id, ws_id)
    return att_id, doc_id, stored_rel_path


# =============================================================================
# (1) 8.6 archive-move seam — 이동·is_archived·물리 존재(INV-4)·관측 전용(7.7)
# =============================================================================


def test_deleted_document_reaction_archive_move_seam(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """완전삭제 반응 보관 이동 seam 을 실제 delete→purge→sweep 경로로 검증한다
    (Req 4.1·4.2·4.3·7.7, INV-4).

    - **관측 전용(Req 4.3·7.7)**: deleted 전이는 s07/s10 purge 가 만들었고, 스윕 **전** 문서
      status 가 이미 'deleted' 다(s12 가 전이를 수행하지 않음).
    - **archive-move(Req 4.1)**: 스윕 후 `is_archived=true`·`file_path` 가 보관 루트 하위를 가리킨다.
    - **물리 이동(Req 4.2·INV-4)**: 파일이 보관 위치에 원본 바이트로 **존재**하고(삭제 아님) 저장
      위치에서는 사라진다.
    - **관측 전용(Req 7.7) 재확인**: 스윕 **후**에도 문서 status 는 여전히 'deleted'(s12 는 문서
      상태를 바꾸지 않는다 — 반응만).
    """
    att_id, doc_id, stored_rel_path = _archive_seam_setup(doc_tree_scenario, harness)

    # (관측 전용 — 전) deleted 전이는 s07/s10 purge 가 만든 관측 가능한 결과다(Req 4.3·7.7).
    with harness.session_local() as db:
        assert db.get(Document, doc_id).status == "deleted", (
            "스윕 이전에 문서는 이미 s10/s07 purge 로 deleted 여야 한다(s12 전이 미수행)"
        )

    # 저장 루트에 실제 파일이 있는지 사전 확인(이동의 출발점).
    stored_file = tmp_attachment_roots.file_storage_root / stored_rel_path
    assert stored_file.is_file(), "스윕 전 첨부 파일은 저장 루트에 존재해야 한다"

    # s12 아카이브 스윕 1회 — 부팅 앱과 동일 세션 팩토리로 실제 ArchivalSweepService 구동.
    processed = archival_sweep.sweep(_NOW)
    assert processed == 1, (
        f"deleted 문서의 미보관 첨부 1건만 보관 이동되어야 한다(결정적 하네스): {processed}"
    )

    # (DB) is_archived=true·file_path 가 보관 루트 하위 상대 경로로 갱신됨(Req 4.1).
    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is True, "완전삭제 반응으로 첨부는 보관됨(is_archived=true)"
        archived_rel_path = att.file_path

    archived_file = tmp_attachment_roots.attachment_archive_root / archived_rel_path
    stored_file_after = tmp_attachment_roots.file_storage_root / stored_rel_path

    # (디스크·INV-4) 물리 삭제 없이 이동 — 보관 위치에 원본 바이트로 존재, 저장 위치에서는 소멸.
    assert archived_file.is_file(), (
        "보관 이동된 파일은 보관 루트의 WS 격리 위치에 물리적으로 존재해야 한다(INV-4, 삭제 아님)"
    )
    assert archived_file.read_bytes() == _FILE_BYTES, (
        "보관된 파일 내용은 원본과 동일해야 한다(이동일 뿐 삭제·훼손 아님)"
    )
    assert not stored_file_after.exists(), (
        "이동 후 저장 루트에는 파일이 남아 있지 않아야 한다(보관 위치로 옮겨짐)"
    )
    assert archived_rel_path.startswith(f"{doc_tree_scenario.workspace_id}/"), (
        "보관 경로도 WS 격리 상대 경로여야 한다(8.8)"
    )

    # (관측 전용 — 후) s12 스윕은 문서 상태를 바꾸지 않는다 — 여전히 deleted(Req 7.7).
    with harness.session_local() as db:
        assert db.get(Document, doc_id).status == "deleted", (
            "s12 스윕은 문서 전이를 수행하지 않으므로 스윕 후에도 status 는 deleted 여야 한다"
        )


# =============================================================================
# (2) 보관 비노출 — role-agnostic 404 (viewer·owner·admin)
# =============================================================================


def test_archived_attachment_serve_404_role_agnostic(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """보관된 첨부 조회는 요청자 role 과 무관하게 404 다(Req 6.2·6.3, INV-7).

    완전삭제 반응 보관 이동 후에는 viewer·owner·admin(관리자) 모두에게 404 로 비노출된다. 보관
    비노출이 권한 판정보다 **먼저** 적용되어 admin 에게도 새지 않음을 보인다(미보관 첨부의 정상
    서빙 200 은 `test_integration_upload_serve.py` 가 별도로 검증한다).

    주의: 여기서는 스윕을 **먼저** 수행한 뒤 조회를 단언한다. 첨부 조회(GET)를 스윕 직전에 끼우면
    공유 테스트 세션 팩토리의 커넥션 풀에서 스윕이 완전삭제(purge) 커밋 이전 스냅샷을 가진
    커넥션을 잡을 수 있는 하네스 격리 특성이 있어(제품 결함 아님 — 실 스케줄러는 전용 신규 세션
    으로 스윕하며 설계상 다음 주기 재시도로 멱등 복구), 조회는 보관 이후에만 배치한다.
    """
    scenario = doc_tree_scenario.scenario
    att_id, _doc_id, _stored = _archive_seam_setup(doc_tree_scenario, harness)
    url = f"/attachments/{att_id}"

    assert archival_sweep.sweep(_NOW) == 1

    # 보관 후: role 무관 404(viewer·owner·admin 모두).
    assert scenario.viewer_client.get(url).status_code == 404, "viewer 는 보관 첨부 404"
    assert scenario.owner_client.get(url).status_code == 404, "owner 는 보관 첨부 404"
    assert scenario.admin_client.get(url).status_code == 404, (
        "admin(관리자)에게도 보관 첨부는 노출되지 않아야 한다(role-agnostic 비노출, Req 6.3)"
    )


# =============================================================================
# (3) 영구성·복원 부재 — 반복 조회 계속 404·보관 상태 유지 (INV-7)
# =============================================================================


def test_archive_permanence_no_restore_path(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """보관 이동은 영구삭제로 간주되어 애플리케이션상 복원(active 되돌리기) 경로가 없다
    (Req 6.4, INV-7).

    스윕 이후 반복 조회가 계속 404 이고 첨부가 계속 `is_archived=true` 임을 확인해 비노출의
    **지속성**을 보인다. s12 에는 보관 첨부를 되살리는 un-archive/restore 엔드포인트가 없으며
    (첨부 라우터는 업로드·서빙 2개 라우트뿐, s01 카탈로그 행 32~33), 휴지통 복구
    (`POST /trash/{bundleId}/restore`)도 이미 완전삭제(deleted)된 묶음에는 적용되지 않는다.
    """
    scenario = doc_tree_scenario.scenario
    att_id, _doc_id, _stored = _archive_seam_setup(doc_tree_scenario, harness)
    url = f"/attachments/{att_id}"

    assert archival_sweep.sweep(_NOW) == 1

    # 반복 조회는 계속 404(비노출 지속) — 조회가 상태를 되돌리지 않는다.
    for _ in range(3):
        assert scenario.viewer_client.get(url).status_code == 404, (
            "보관 첨부는 반복 조회해도 계속 404(복원되지 않음)"
        )
        assert scenario.admin_client.get(url).status_code == 404, (
            "admin 반복 조회도 계속 404"
        )

    # 애플리케이션 경로로 되돌아오지 않았음을 DB 로 확인(is_archived 유지).
    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is True, (
            "보관 첨부는 active 로 되돌아오지 않는다(복원 경로 부재, INV-7)"
        )


# =============================================================================
# (4) 멱등성 — 두 번째 스윕은 재이동하지 않음 (Req 4.4)
# =============================================================================


def test_repeated_sweep_is_idempotent(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """완전삭제 반응 보관 이동은 반복 스윕에 멱등하다(Req 4.4).

    첫 스윕이 첨부 1건을 보관한 뒤, 두 번째 스윕은 이미 보관된 이 첨부를 다시 이동하거나 오류를
    내지 않는다(반환 0). 보관 파일은 그대로 원본 바이트로 남아 있고(더블 무브·훼손 없음),
    `GET` 은 계속 404 다.
    """
    att_id, _doc_id, _stored = _archive_seam_setup(doc_tree_scenario, harness)
    url = f"/attachments/{att_id}"

    # 첫 스윕: 보관.
    assert archival_sweep.sweep(_NOW) == 1, "첫 스윕은 미보관 첨부 1건을 보관"

    with harness.session_local() as db:
        archived_rel_path = db.get(Attachment, att_id).file_path
    archived_file = tmp_attachment_roots.attachment_archive_root / archived_rel_path
    assert archived_file.read_bytes() == _FILE_BYTES

    # 두 번째 스윕: 이미 보관되어 스코프에서 제외 → 재이동 없음(반환 0).
    assert archival_sweep.sweep(_NOW) == 0, (
        "이미 보관된 첨부는 스코프에서 제외되어 두 번째 스윕은 0 을 반환(멱등)"
    )

    # 더블 무브·훼손 없음: 파일 여전히 보관 위치에 원본 바이트로 존재, 여전히 404.
    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is True, "멱등 스윕 후에도 계속 보관 상태"
        assert att.file_path == archived_rel_path, "file_path 가 재이동으로 바뀌지 않아야 한다"
    assert archived_file.is_file(), "보관 파일은 두 번째 스윕 후에도 그대로 존재"
    assert archived_file.read_bytes() == _FILE_BYTES, "내용도 불변(더블 무브·훼손 없음)"
    assert doc_tree_scenario.scenario.viewer_client.get(url).status_code == 404, (
        "멱등 스윕 후에도 보관 첨부는 계속 404"
    )
