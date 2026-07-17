"""참조 소멸↔버전 저장 결합 스위트 — 이미지 보관 이동·붙여넣기 보호·현재참조 유지 미보관·
이미지 한정·관측 판정 (8.7)
(Task 2.4 / Req 5.1·5.2·5.3·5.4·5.5, design §SaveDereferenceCombinationSuite,
§System Flows "저장 참조 소멸 아카이브 (8.7) — 현재 버전 참조 관측").

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕**s12** 첨부 라우터·아카이브
스케줄러 조립, `app.main.create_app`) 위에서, **실제** s09 저장 경로(잠금→저장)로 만들어진
현재 버전 참조에 s12 `ArchivalSweepService` 가 반응하는 seam(8.7)을 mock 없이 결합 검증한다.
저장/보관 루트만 tmp 로 격리(`tmp_attachment_roots`)해 디스크상 이동을 실제 파일시스템으로
관찰한다. 문서 버전·현재 버전 참조를 직접 세팅하는 지름길이 아니라 실제 API 로

    이미지 업로드 → `POST /documents/{id}/lock` + `POST /documents/{id}/save`(현재 버전 생성)
    → (참조 제거 본문으로) 다시 저장(새 현재 버전) → `archival_sweep.sweep(now)`

경로를 태워(L5 `helpers.save_with_reference`/`save_without_reference` = L4 잠금→저장 재사용),
s09 가 만든 관측 가능한 결과(문서 `current_version_id`·그 버전 본문의 참조)에만 s12 가 반응함을
보인다. 검증 항목(design §SaveDereferenceCombinationSuite):

- **참조 소멸 아카이브(5.1)**: v1(참조 포함)→v2(참조 제거) 저장으로 현재 버전이 더 이상
  참조하지 않으면 스윕이 그 이미지를 보관 폴더로 이동하고 `is_archived=true`(파일 이동·GET 404):
  :func:`test_dereferenced_image_is_archived`.
- **현재 참조 유지 미보관(5.2/5.5)**: 현재 버전 본문이 여전히 `/attachments/{id}` 를 참조하면
  (`ReferenceScanner`) 스윕이 그 이미지를 보관하지 않는다(is_archived 유지·GET 200):
  :func:`test_current_reference_held_is_not_archived`.
- **붙여넣기 보호(5.3)**: `attachment.created_at > current_version.created_at`(어떤 저장 버전에도
  미반영된 새 붙여넣기)이면 참조 소멸로 간주하지 않아 보관하지 않는다(is_archived 유지·GET 200):
  :func:`test_unsaved_paste_is_protected`.
- **관측 판정(5.4)**: s12 는 저장·버전 생성을 수행하지 않고 s09 가 만든 현재 버전 참조를
  관측(`load_current_content`)해 판정한다 — 참조를 제거하는 **실제 저장(POST /save)** 이 현재
  버전을 바꿔야 비로소 보관되고, 스윕은 문서 `current_version_id`·버전 수를 바꾸지 않는다:
  :func:`test_sweep_observes_current_version_only`.
- **이미지 한정(5.5)**: 참조 소멸 스윕은 `kind=image` 에만 적용되고 active 문서의 일반
  파일(kind=file)은 참조 소멸로 보관되지 않는다(파일 보관은 8.6 완전삭제 반응 전용):
  :func:`test_general_file_not_archived_by_dereference`.

created_at 결정성(붙여넣기 보호): 붙여넣기 보호는 `attachment.created_at >
current_version.created_at` 을 DATETIME(0) 초 정밀도로 비교한다. 빠른 실행이 업로드·저장을 같은
초에 떨어뜨리면 비교가 비결정적이 될 수 있으므로, 관련 `attachment.created_at` 을 부팅 앱과 동일
세션 팩토리(`harness.session_local`)로 직접 초단위(마이크로초 0) 값으로 핀 고정한다(L4
`TrashScenario.pin_trashed_at` 규약 답습 — 테스트 시드 조작이지 스윕 대역이 아니다). 보관
후보(참조 소멸)는 `att.created_at <= current_version.created_at` 이 되도록 이른 값(_EARLY)으로,
붙여넣기 보호 대상은 `att.created_at > current_version.created_at` 이 되도록 늦은 값(_LATE)으로
고정해 초 정밀도 비교를 명확히 한다. 현재 버전 created_at 은 실제 저장 시각(~2026-07)이므로
_EARLY(2026-01) < 현재 < _LATE(2027-01) 로 두 경계 모두 결정적이다.

REPEATABLE READ 정합(4.2 노트 답습): 공유 테스트 세션 풀 + MySQL REPEATABLE READ 에서 스윕이
커밋 이전 스냅샷을 잡지 않도록, 커밋되는 API 호출(업로드·저장)과 핀 고정 쓰기를 **먼저**
수행하고, 그다음 `archival_sweep.sweep(now)` 를, 마지막에 GET/DB 관찰을 한다. 스윕 접근 핸들은
호출마다 전용 신규 세션을 열어 관찰한다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드·conftest·helpers·하네스는 건드리지 않고
재사용만 한다. 재검증 트리거: s01/s02/s03/s05/s07/s09/s10/s12 중 하나라도 수정되면 이
체크포인트를 누적 집합 기준으로 재실행한다(s01 수정 시 모든 체크포인트 재실행).
"""

from datetime import datetime

from sqlalchemy import func, select

from app.attachment.schemas import AttachmentKind
from app.models import Attachment, Document, DocumentVersion
from tests.integration_L5 import helpers as h

# 업로드 바이너리(작은 PNG 시그니처 + 페이로드; 25MiB 한도 이하라 저장·이동 경로만 관찰).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l5-save-dereference-image-payload"
# 일반 파일 바이너리(kind=file 은 8.7 image 한정 스코프에서 제외 → 참조 소멸 보관 이동 부재 관찰).
_FILE_BYTES = b"%PDF-1.4 l5-save-dereference-file-payload\n%%EOF"

# 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 8.7 은 now 에 직접 의존하지 않으나 API 가 받는다.
_NOW = datetime(2026, 7, 17, 12, 0, 0)

# 첨부 created_at 핀 값(마이크로초 0). 참조 소멸 후보는 현재 버전 이전(_EARLY, <=), 붙여넣기 보호
# 대상은 현재 버전 이후(_LATE, >)로 고정해 초 정밀도 비교를 결정적으로 만든다.
_EARLY = datetime(2026, 1, 1, 0, 0, 0)
_LATE = datetime(2027, 1, 1, 0, 0, 0)


def _pin_attachment_created_at(harness, attachment_id, ts):
    """첨부 ``created_at`` 을 결정적 초단위(마이크로초 0) 값으로 핀 고정한다(붙여넣기 보호 결정성).

    업로드·저장이 같은 벽시계 초에 떨어져 `att.created_at` vs `current_version.created_at`
    비교가 비결정적이 되는 것을 막으려, 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로
    직접 DATETIME(0) 정합 값을 부여한다(L4 `pin_trashed_at` 규약 답습 — 테스트 시드 조작이며
    스윕 서비스는 이 값을 저장하지 않는다).
    """
    ts = ts.replace(microsecond=0)
    with harness.session_local() as db:
        att = db.get(Attachment, attachment_id)
        assert att is not None, f"핀 대상 첨부가 있어야 한다: id={attachment_id}"
        att.created_at = ts
        db.commit()


def _doc_version_state(harness, document_id):
    """부팅 앱과 동일 세션 팩토리로 문서의 ``(current_version_id, 버전 수)`` 를 신규 세션으로 관측한다.

    s12 스윕이 저장·버전 생성·전이를 수행하지 않고 관측만 함을(Req 5.4) 스윕 전·후 이 값의
    불변으로 확인하기 위한 관측 헬퍼.
    """
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        assert doc is not None, f"관측 대상 문서가 있어야 한다: id={document_id}"
        count = db.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
        )
        return doc.current_version_id, count


# =============================================================================
# 1) 참조 소멸 → 보관 이동 (Req 5.1)
# =============================================================================


def test_dereferenced_image_is_archived(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """새 버전 저장으로 현재 버전이 더 이상 참조하지 않게 된 이미지는 보관된다(Req 5.1).

    이미지 업로드 → v1(참조 포함) 저장 → v2(참조 제거) 저장으로 현재 버전은 이미지를 참조하지
    않는다. att.created_at 을 현재 버전 이전으로 핀(붙여넣기 보호 통과) → 스윕이 이미지를 보관
    폴더로 이동하고 `is_archived=true` 로 표시한다(파일이 보관 루트로 이동·저장 루트에서
    소멸·GET 404). 저장은 실제 `POST /save`(L4 잠금→저장 재사용)이며 s12 는 관측만 한다.
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    att = h.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    att_id = att["id"]
    url = att["url"]
    assert att["kind"] == AttachmentKind.IMAGE.value, "붙여넣기 이미지 kind=image"

    # 스윕 전 저장 위치에 이미지 파일이 물리적으로 존재(이동의 출발점).
    stored_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert stored_rel_path is not None, "업로드 첨부의 저장 file_path 가 커밋되어 있어야 한다"
    h.assert_ws_isolated(stored_rel_path, ws_id)
    stored_file = h.assert_stored(tmp_attachment_roots, stored_rel_path)
    assert stored_file.read_bytes() == _IMAGE_BYTES, "저장 파일 바이트가 업로드와 일치해야 한다"

    # v1: 참조 포함, v2(현재): 참조 제거 → 현재 버전은 이미지를 참조하지 않는다(실제 s09 저장).
    h.save_with_reference(editor, doc_id, att_id)
    h.save_without_reference(editor, doc_id)
    _pin_attachment_created_at(harness, att_id, _EARLY)

    # 스윕 — 현재 버전(v2)이 참조하지 않으므로 이 이미지 1건이 보관 이동된다.
    processed = h.run_archival_sweep(archival_sweep, _NOW)
    assert processed == 1, (
        f"현재 버전이 참조하지 않는 이미지 1건만 보관 이동되어야 한다(결정적 하네스): {processed}"
    )

    # (DB) is_archived=true·file_path 가 보관 루트 하위 WS 격리 상대 경로로 갱신(Req 5.1).
    assert h.attachment_is_archived(harness.session_local, att_id) is True, (
        "참조 소멸 이미지는 보관됨(is_archived=true, Req 5.1)"
    )
    archived_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert archived_rel_path is not None
    h.assert_ws_isolated(archived_rel_path, ws_id)

    # (디스크·INV-4) 물리 삭제 없이 이동 — 보관 위치에 원본 바이트로 존재, 저장 위치에서는 소멸.
    archived_file = h.assert_archived(tmp_attachment_roots, archived_rel_path)
    assert archived_file.read_bytes() == _IMAGE_BYTES, (
        "보관된 이미지 내용은 원본과 동일해야 한다(이동일 뿐 삭제·훼손 아님, INV-4)"
    )
    h.assert_not_stored(tmp_attachment_roots, stored_rel_path)

    # 보관 첨부는 role 무관 조회 불가(404).
    assert viewer.get(url).status_code == 404, "보관된 이미지는 조회 불가(404)"


# =============================================================================
# 2) 현재 참조 유지 → 보관 안 함 (Req 5.2 / 5.5 current-ref-held)
# =============================================================================


def test_current_reference_held_is_not_archived(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """현재 버전이 여전히 `/attachments/{id}` 를 참조하는 이미지는 스윕에서 보관되지 않는다(Req 5.2).

    이미지 업로드 → 참조를 포함한 본문으로 s09 저장(현재 버전이 참조) → att.created_at 을 현재
    버전 이전으로 핀(붙여넣기 보호 통과) → `ReferenceScanner.is_referenced` 가 True 이므로 스윕은
    이 이미지를 보관하지 않는다. 이 이미지가 8.7 유일 후보이자 삭제 문서가 없어 스윕은 0 을
    반환하고(참조 유지 → 보관 없음), is_archived 유지·file_path 불변·GET 200 이다.
    """
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    att = h.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    att_id = att["id"]
    url = att["url"]

    # 현재 버전이 이미지를 참조하도록 저장(s09). att.created_at <= 현재 버전(붙여넣기 보호 통과).
    h.save_with_reference(editor, doc_id, att_id)
    _pin_attachment_created_at(harness, att_id, _EARLY)
    stored_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert stored_rel_path is not None

    # 스윕 — 유일 후보가 참조 유지 이미지이므로 보관 없음(0).
    assert h.run_archival_sweep(archival_sweep, _NOW) == 0, (
        "현재 버전이 여전히 참조하는 이미지는 보관되지 않아야 한다(sweep 0, Req 5.2)"
    )

    # (DB) 미보관 유지·file_path 불변 — 참조 유지 → 아카이브 아님.
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "참조 유지 이미지는 미보관 상태 유지(Req 5.2)"
    )
    assert h.attachment_file_path(harness.session_local, att_id) == stored_rel_path, (
        "참조 유지 이미지의 file_path 는 스윕에 의해 바뀌면 안 된다"
    )

    # (디스크) 저장 위치 존속·보관 위치 부재.
    h.assert_stored(tmp_attachment_roots, stored_rel_path)
    h.assert_not_archived(tmp_attachment_roots, stored_rel_path)

    # 참조 유지 이미지는 계속 조회 가능(200).
    assert viewer.get(url).status_code == 200, "참조 유지 이미지는 계속 조회 가능(200)"


# =============================================================================
# 3) 붙여넣기 보호 — 미저장 새 붙여넣기는 보관 안 함 (Req 5.3)
# =============================================================================


def test_unsaved_paste_is_protected(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """어떤 저장 버전에도 반영되지 않은 새 붙여넣기 이미지는 참조 소멸로 간주하지 않는다(Req 5.3).

    문서에 현재 버전(참조 없음)을 **먼저** 만든 뒤 이미지를 붙여넣고, att.created_at 을 현재
    버전보다 **엄격히 나중**(_LATE)으로 핀 고정한다(미저장 새 붙여넣기 상태). 현재 버전이 이
    이미지를 참조하지 않지만, 붙여넣기 보호(`att.created_at > current_version.created_at`)가 참조
    판정보다 먼저 적용되어 보관하지 않는다 → is_archived 유지·file_path 불변·GET 200. 편집 중
    붙여넣기 직후 오아카이브 방지. 현재 버전 created_at 은 실제 저장 시각(~2026-07)이라 _LATE
    (2027-01) 가 엄격히 나중임이 초 정밀도와 무관하게 결정적이다.
    """
    doc_id = doc_tree_scenario.child_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    # 현재 버전을 먼저 만든다(참조 없음) → 이미지가 8.7 스코프(현재 버전 존재)에 들되,
    # 붙여넣기 보호로 걸러지는 경로를 명확히 격리한다.
    h.save_without_reference(editor, doc_id)

    att = h.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    att_id = att["id"]
    url = att["url"]

    # 붙여넣기 보호: att.created_at 을 현재 버전보다 엄격히 나중으로 핀(미저장 새 붙여넣기).
    _pin_attachment_created_at(harness, att_id, _LATE)
    stored_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert stored_rel_path is not None

    # 스윕 — 붙여넣기 보호로 보관되지 않음(0).
    assert h.run_archival_sweep(archival_sweep, _NOW) == 0, (
        "현재 버전보다 나중 생성된 미저장 붙여넣기 이미지는 보관되지 않아야 한다(sweep 0, Req 5.3)"
    )

    # (DB) 미보관 유지·file_path 불변, (디스크) 저장 위치 존속·보관 위치 부재.
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "미저장 붙여넣기 이미지는 미보관 유지(붙여넣기 보호, Req 5.3)"
    )
    assert h.attachment_file_path(harness.session_local, att_id) == stored_rel_path
    h.assert_stored(tmp_attachment_roots, stored_rel_path)
    h.assert_not_archived(tmp_attachment_roots, stored_rel_path)

    # 붙여넣기 보호 이미지는 계속 조회 가능(200).
    assert viewer.get(url).status_code == 200, "붙여넣기 보호 이미지는 계속 조회 가능(200)"


# =============================================================================
# 4) 관측 판정 — 실제 저장이 현재 버전을 바꾸고, 스윕은 관측만 (Req 5.4)
# =============================================================================


def test_sweep_observes_current_version_only(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """s12 스윕은 저장·버전 생성을 수행하지 않고 s09 가 만든 현재 버전 참조를 관측해 판정한다
    (Req 5.4).

    참조 소멸 판정을 만드는 것은 s12 가 아니라 **실제 저장(POST /save)** 임을 대조로 보인다:

    - v1(참조 포함) 저장 후 스윕하면 현재 버전이 참조하므로 **보관되지 않는다**(스윕은 s09 가 만든
      현재 버전 참조를 관측할 뿐).
    - 참조를 제거하는 **실제 저장(v2)** 이 현재 버전을 바꾼 **뒤에야** 스윕이 보관한다(현재
      버전 참조 관측 판정).
    - 스윕은 문서 `current_version_id` 와 버전 수를 바꾸지 않는다(저장·버전·전이 미수행) — 스윕
      전·후 동일함을 단언한다.
    """
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client

    att = h.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    att_id = att["id"]

    # v1: 현재 버전이 이미지를 참조. att.created_at <= 현재 버전(붙여넣기 보호 통과).
    v1 = h.save_with_reference(editor, doc_id, att_id)
    _pin_attachment_created_at(harness, att_id, _EARLY)

    # 저장 직후 버전 상태: v1 이 현재, 버전 1개(s09 저장이 만든 관측 기준값).
    current_after_v1, count_after_v1 = _doc_version_state(harness, doc_id)
    assert current_after_v1 == v1["id"], "저장 직후 현재 버전은 v1 이어야 한다"
    assert count_after_v1 == 1, "저장 직후 버전 수는 1 이어야 한다"

    # (대조 전제) 아직 현재 버전이 참조하므로 스윕은 보관하지 않는다 — s12 는 참조를 소멸시키지
    # 않는다(저장이 해야 한다).
    assert h.run_archival_sweep(archival_sweep, _NOW) == 0, (
        "현재 버전이 참조하는 동안은 스윕이 보관하지 않는다(s12 는 참조 소멸을 만들지 않음)"
    )
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "저장이 참조를 제거하기 전에는 이미지가 보관되지 않는다"
    )

    # v2: 참조를 제거하는 **실제 저장(POST /save)** 이 현재 버전을 바꾼다(관측 대상 변경).
    v2 = h.save_without_reference(editor, doc_id)
    current_after_v2, count_after_v2 = _doc_version_state(harness, doc_id)
    assert current_after_v2 == v2["id"], (
        "참조를 제거하는 실제 저장이 현재 버전을 v2 로 바꿔야 한다(s09 저장이 판정 대상을 만든다)"
    )
    assert count_after_v2 == 2, "실제 저장으로 버전 수는 2 가 되어야 한다"

    # 이제 현재 버전(v2)이 참조하지 않으므로 스윕이 관측해 보관한다.
    assert h.run_archival_sweep(archival_sweep, _NOW) == 1, (
        "현재 버전이 참조를 잃은 뒤에야 스윕이 이미지를 보관한다(현재 버전 참조 관측 판정, Req 5.4)"
    )
    assert h.attachment_is_archived(harness.session_local, att_id) is True, (
        "관측 판정으로 참조 소멸 이미지는 보관됨"
    )

    # (관측 전용) 스윕은 새 버전·전이를 만들지 않는다 — current_version_id·버전 수 불변(Req 5.4).
    current_after_sweep, count_after_sweep = _doc_version_state(harness, doc_id)
    assert current_after_sweep == v2["id"], (
        "s12 스윕은 새 버전을 만들지 않으므로 current_version_id 는 v2 그대로여야 한다(Req 5.4)"
    )
    assert count_after_sweep == 2, (
        "s12 스윕은 버전을 추가하지 않으므로 버전 수는 s09 저장 결과(2)와 동일해야 한다(Req 5.4)"
    )


# =============================================================================
# 5) 이미지 한정 — 일반 파일은 참조 소멸로 보관 안 함 (Req 5.5, 이미지 한정)
# =============================================================================


def test_general_file_not_archived_by_dereference(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """active 문서의 일반 파일 첨부(kind=file)는 참조 소멸 아카이브(8.7) 대상이 아니다(Req 5.5).

    active 문서에 현재 버전(참조 없음)을 만들고 일반 파일을 첨부한 뒤 스윕해도, 8.7 은 image
    종류에 한정되므로 파일은 보관되지 않는다(파일의 보관 이동은 8.6 완전삭제 반응 전용이며 문서는
    삭제되지 않았다). is_archived 유지·file_path 불변·저장 위치 존속·GET 200.
    """
    doc_id = doc_tree_scenario.grandchild_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    # 현재 버전을 만들되 파일을 참조하지 않는다(참조 소멸 상태를 파일에 대해 재현).
    h.save_without_reference(editor, doc_id)

    att = h.upload_file(editor, doc_id, content=_FILE_BYTES)
    att_id = att["id"]
    url = att["url"]
    assert att["kind"] == AttachmentKind.FILE.value, "일반 파일 kind=file"

    stored_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert stored_rel_path is not None
    h.assert_stored(tmp_attachment_roots, stored_rel_path)

    # 스윕 — 파일은 8.7 스코프(image 한정) 밖이고 문서도 삭제되지 않아 보관되지 않는다(0).
    assert h.run_archival_sweep(archival_sweep, _NOW) == 0, (
        "일반 파일 첨부는 참조 소멸(8.7)로 보관되지 않아야 한다(sweep 0, Req 5.5 이미지 한정)"
    )

    # (DB) 미보관 유지·file_path 불변, (디스크) 저장 위치 존속·보관 위치 부재.
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "일반 파일은 참조 소멸로 보관되지 않는다(Req 5.5 이미지 한정)"
    )
    assert h.attachment_file_path(harness.session_local, att_id) == stored_rel_path, (
        "파일 첨부의 file_path 는 참조 소멸 스윕에 의해 바뀌면 안 된다"
    )
    h.assert_stored(tmp_attachment_roots, stored_rel_path)
    h.assert_not_archived(tmp_attachment_roots, stored_rel_path)

    # 미보관 파일은 계속 조회 가능(200).
    assert viewer.get(url).status_code == 200, "미보관 파일은 계속 조회 가능(200)"
