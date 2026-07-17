"""저장 참조 소멸 아카이브 seam 통합 테스트 (8.7)
(Task 4.3 / Req 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.5, 7.7).

design.md §Testing Strategy "참조 소멸 아카이브(8.7, 핵심 seam)"·§System Flows "저장 참조
소멸 아카이브 (8.7) — 현재 버전 참조 관측" 을 **마이그레이션된 실제 DB + 부팅 앱**(첨부 라우터 +
잠금·버전 라우트 조립, `app.main.create_app`) 위에서 검증한다. mock 없이
s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12 를 결합한 L3 하네스(`tests/attachment/conftest.py`
재-import)를 쓰며, 저장/보관 루트를 tmp 로 격리해(``tmp_attachment_roots``) 디스크상 이동을
실제로 관찰한다.

핵심은 **실제 s09 저장 경로(잠금→저장)로 만들어진 현재 버전 참조**에 s12 스윕이 반응하는
seam 이다. 문서 버전·현재 버전 참조를 직접 세팅하는 지름길이 아니라, 실제 API 로

    이미지 업로드 → `POST /documents/{id}/lock` + `POST /documents/{id}/save`(현재 버전 생성)
    → (참조 제거 본문으로) 다시 저장(새 현재 버전) → `archival_sweep.sweep(now)`

경로를 태워 s09 가 만든 관측 가능한 결과(문서 `current_version_id`·그 버전 본문의 참조)에만
s12 가 반응함을 보인다. 검증 항목:

- **참조 유지 → 보관 안 함 (Req 5.5)**: 현재 버전 본문이 여전히 `/attachments/{id}` 를 참조하면
  스윕이 그 이미지를 보관하지 않는다(is_archived 유지·GET 200, 후보 단독 시 sweep 0).
- **참조 소멸 → 보관 (Req 5.1/5.2, wrong-version-join 경화)**: v1 이 참조하고 v2(현재)가
  참조하지 않으면 스윕이 그 이미지를 보관한다(is_archived=true·파일이 보관 루트로 이동·GET 404).
  판정은 **현재 버전(v2)만** 관측하며, 더 오래된 v1 이 참조해도 보관됨을 보여 잘못된 버전 조인
  회귀를 잡는다.
- **붙여넣기 보호 (Req 5.3)**: 어떤 저장 버전에도 반영되지 않은(현재 버전보다 나중 생성) 새
  붙여넣기 이미지는 참조 소멸로 간주하지 않아 보관하지 않는다(is_archived 유지·GET 200).
- **이미지 한정 (Req 5.6)**: active 문서의 일반 파일 첨부(kind=file)는 참조 소멸(8.7) 스코프에서
  제외되어 보관되지 않는다(파일은 8.6 완전삭제 반응으로만 처리·문서 미삭제).
- **관측 전용 (Req 5.4/7.7)**: 버전·현재 버전은 s09 저장 경로가 만들었고, s12 스윕은 저장·버전
  생성·전이를 수행하지 않는다 — 문서 `current_version_id` 와 버전 수가 스윕 **전·후 동일**함을
  보인다.
- **단조 증가 보관 (Req 6.5)**: 보관된 이미지는 보관 폴더에 누적될 뿐이다(암시적 — archive-move
  로 충족).

created_at 결정성(붙여넣기 보호): 붙여넣기 보호는 `attachment.created_at >
current_version.created_at` 을 DATETIME(0) 초 정밀도로 비교한다. 빠른 테스트 실행이 업로드·저장을
같은 초에 떨어뜨리면 비교가 비결정적이 될 수 있으므로, 각 경우가 명확해지도록 관련 `created_at`
을 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로 직접 초단위(마이크로초 0) 값으로 핀
고정한다(L4 `TrashScenario.pin_trashed_at` 규약 답습). 보관 후보(저장 후 참조 소멸)는
`att.created_at <= current_version.created_at` 이 되도록 초기값으로, 붙여넣기 보호 대상은
`att.created_at > current_version.created_at` 이 되도록 후기값으로 핀 고정한다.

REPEATABLE READ 정합(하네스 아티팩트 회피, 4.2 노트): 공유 테스트 세션 풀 + MySQL REPEATABLE
READ 에서 스윕이 커밋 이전 스냅샷 커넥션을 잡지 않도록, 커밋되는 API 호출(업로드·저장)과 핀
고정 쓰기를 **먼저** 수행하고, 그다음 `archival_sweep.sweep(now)` 를, 마지막에 GET/DB 관찰을
한다(앱 코드 수정 불필요 — 실 스케줄러는 전용 신규 세션으로 스윕한다).
"""

from datetime import datetime

from sqlalchemy import func, select

from app.attachment.schemas import AttachmentKind
from app.models import Attachment, Document, DocumentVersion
from tests.integration_L4 import helpers as l4_helpers

# 업로드 바이너리(작은 PNG 시그니처 + 페이로드; 25MiB 한도 이하라 저장·이동 경로만 관찰).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-dereference-seam-image-payload"
# 일반 파일 바이너리(kind=file 은 8.7 image 한정 스코프에서 제외 → 보관 이동 경로 부재 관찰).
_FILE_BYTES = b"%PDF-1.4 dereference-seam-file-payload\n%%EOF"

# 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 8.7 은 now 에 직접 의존하지 않으나 API 가 받는다.
_NOW = datetime(2026, 7, 17, 12, 0, 0)

# 첨부 created_at 핀 값(마이크로초 0). 저장 후 참조 소멸 후보는 현재 버전 이전(_EARLY, <=),
# 붙여넣기 보호 대상은 현재 버전 이후(_LATE, >)로 고정해 초 정밀도 비교를 명확히 한다.
_EARLY = datetime(2026, 1, 1, 0, 0, 0)
_LATE = datetime(2027, 1, 1, 0, 0, 0)


def _upload_image(client, document_id, *, filename="paste.png", data=_IMAGE_BYTES):
    """``POST /documents/{id}/attachments`` 로 이미지 붙여넣기 첨부를 업로드하고 응답을 반환한다.

    content-type ``image/png`` 이 라우터의 kind 추론을 image 로 구동한다(8.1). 응답 url
    (`/attachments/{id}`)이 이후 본문 참조 토큰이 된다.
    """
    return client.post(
        f"/documents/{document_id}/attachments",
        files={"file": (filename, data, "image/png")},
    )


def _upload_file(client, document_id, *, filename="doc.pdf", data=_FILE_BYTES):
    """``POST /documents/{id}/attachments`` 로 일반 파일 첨부(kind=file)를 업로드하고 응답을 반환한다.

    명시 ``kind=file`` 로 일반 파일 종류를 강제한다(8.7 image 한정 스코프에서 제외 → 참조 소멸로
    보관 이동되지 않음을 격리 검증).
    """
    return client.post(
        f"/documents/{document_id}/attachments",
        files={"file": (filename, data, "application/pdf")},
        data={"kind": "file"},
    )


def _ref_body(url: str) -> str:
    """현재 버전 본문에 첨부 참조 토큰(`/attachments/{id}`)을 포함하는 저장 본문."""
    return f"# 문서\n\n![붙여넣은 이미지]({url})\n\n본문 텍스트."


def _no_ref_body() -> str:
    """어떤 첨부도 참조하지 않는 저장 본문(참조 소멸·미참조 상태 구성용)."""
    return "# 문서\n\n본문에는 이미지 참조가 없다.\n"


def _save_version(editor, document_id, content):
    """실제 s09 경로(잠금→저장)로 새 현재 버전을 만들고 파싱된 ``DocumentVersionRead`` 를 반환한다.

    s12 는 이 저장·버전 생성을 소유하지 않는다 — s09 가 만든 `current_version_id`·현재 버전
    본문 참조라는 관측 가능한 결과를 뒤에서 관측할 뿐이다(Req 5.4·7.7).
    """
    l4_helpers.lock(editor, document_id)
    return l4_helpers.save(editor, document_id, content)


def _pin_attachment_created_at(harness, attachment_id, ts):
    """첨부 ``created_at`` 을 결정적 초단위(마이크로초 0) 값으로 핀 고정한다(붙여넣기 보호 결정성).

    업로드·저장이 같은 벽시계 초에 떨어져 `att.created_at` vs `current_version.created_at`
    비교가 비결정적이 되는 것을 막으려, 부팅 앱과 동일 세션 팩토리로 직접 DATETIME(0) 정합 값을
    부여한다(테스트 시드 조작 — 스윕 서비스는 이 값을 저장하지 않는다).
    """
    ts = ts.replace(microsecond=0)
    with harness.session_local() as db:
        att = db.get(Attachment, attachment_id)
        assert att is not None, f"핀 대상 첨부가 있어야 한다: id={attachment_id}"
        att.created_at = ts
        db.commit()


def _doc_version_state(harness, document_id):
    """부팅 앱과 동일 세션으로 문서의 ``(current_version_id, 버전 수)`` 를 신규 세션으로 관측한다."""
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
# (1) 참조 유지 → 보관 안 함 (Req 5.5)
# =============================================================================


def test_current_version_still_references_image_is_kept(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """현재 버전이 여전히 참조하는 이미지는 참조 소멸 스윕에서 보관되지 않는다(Req 5.5).

    이미지 업로드 → 참조를 포함한 본문으로 s09 저장(현재 버전이 참조) → att.created_at 을 현재
    버전 이전으로 핀(붙여넣기 보호 통과) → 스윕은 이 이미지를 보관하지 않는다. 이 이미지가 8.7
    유일 후보이므로 스윕은 0 을 반환하고(참조 유지 → 보관 없음), GET 은 계속 200 이다.
    """
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    created = _upload_image(editor, doc_id)
    assert created.status_code == 201, (
        f"editor 이미지 업로드 201: {created.status_code} {created.text}"
    )
    att_id = created.json()["id"]
    url = created.json()["url"]
    assert created.json()["kind"] == AttachmentKind.IMAGE.value, "붙여넣기 이미지 kind=image"

    # 현재 버전이 이미지를 참조하도록 저장(s09). att.created_at <= 현재 버전(붙여넣기 보호 통과).
    _save_version(editor, doc_id, _ref_body(url))
    _pin_attachment_created_at(harness, att_id, _EARLY)

    # 스윕 먼저(REPEATABLE READ 정합) — 유일 후보가 참조 유지 이미지이므로 보관 없음(0).
    assert archival_sweep.sweep(_NOW) == 0, (
        "현재 버전이 여전히 참조하는 이미지는 보관되지 않아야 한다(sweep 0, Req 5.5)"
    )

    # 미보관 유지 + 서빙 200(참조 유지 → 아카이브 아님).
    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is False, "참조 유지 이미지는 미보관 상태 유지(Req 5.5)"
    assert viewer.get(url).status_code == 200, "참조 유지 이미지는 계속 조회 가능(200)"


# =============================================================================
# (2) 참조 소멸 → 보관 (Req 5.1/5.2, wrong-version-join 경화)
# =============================================================================


def test_dereferenced_image_is_archived_current_version_only(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """새 버전 저장으로 현재 버전이 더 이상 참조하지 않게 된 이미지는 보관된다(Req 5.1·5.2).

    v1(참조 포함) 저장 → v2(참조 제거) 저장으로 현재 버전은 이미지를 참조하지 않는다. att.created_at
    을 현재 버전 이전으로 핀(붙여넣기 보호 통과) → 스윕이 이미지를 보관 폴더로 이동하고
    `is_archived=true` 로 표시한다(파일이 보관 루트로 이동·저장 루트에서 소멸·GET 404).

    **wrong-version-join 경화**: 더 오래된 v1 은 여전히 이미지를 참조하지만, 판정은 현재 버전(v2)
    본문만 관측하므로 보관된다 — 잘못된 버전 조인(예: 문서의 모든 버전·과거 버전 참조)이면 이
    이미지를 유지했을 것이다.
    """
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    created = _upload_image(editor, doc_id)
    assert created.status_code == 201, (
        f"editor 이미지 업로드 201: {created.status_code} {created.text}"
    )
    att_id = created.json()["id"]
    url = created.json()["url"]

    # v1: 참조 포함. v2(현재): 참조 제거 → 현재 버전은 이미지를 참조하지 않는다.
    v1 = _save_version(editor, doc_id, _ref_body(url))
    v2 = _save_version(editor, doc_id, _no_ref_body())
    _pin_attachment_created_at(harness, att_id, _EARLY)

    # (전제) 더 오래된 v1 은 여전히 참조하지만 현재 버전은 v2 다(wrong-version-join 경화 근거).
    with harness.session_local() as db:
        doc = db.get(Document, doc_id)
        assert doc.current_version_id == v2["id"], "현재 버전은 마지막 저장(v2)이어야 한다"
        v1_row = db.get(DocumentVersion, v1["id"])
        assert url in v1_row.content, (
            "더 오래된 v1 은 여전히 이미지를 참조한다(현재 버전만 관측함을 대조하는 근거)"
        )
        stored_rel_path = db.get(Attachment, att_id).file_path
    stored_file = tmp_attachment_roots.file_storage_root / stored_rel_path
    assert stored_file.is_file(), "스윕 전 이미지 파일은 저장 루트에 존재해야 한다"

    # 스윕 — 현재 버전(v2)이 참조하지 않으므로 이 이미지 1건이 보관 이동된다.
    processed = archival_sweep.sweep(_NOW)
    assert processed == 1, (
        f"현재 버전이 참조하지 않는 이미지 1건만 보관 이동되어야 한다(결정적 하네스): {processed}"
    )

    # (DB) is_archived=true·file_path 가 보관 루트 하위 WS 격리 상대 경로로 갱신(Req 5.1).
    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is True, "참조 소멸 이미지는 보관됨(is_archived=true, Req 5.1)"
        archived_rel_path = att.file_path

    archived_file = tmp_attachment_roots.attachment_archive_root / archived_rel_path
    stored_file_after = tmp_attachment_roots.file_storage_root / stored_rel_path

    # (디스크·INV-4) 물리 삭제 없이 이동 — 보관 위치에 원본 바이트로 존재, 저장 위치에서는 소멸.
    assert archived_file.is_file(), (
        "보관 이동된 이미지는 보관 루트의 WS 격리 위치에 물리적으로 존재해야 한다(INV-4, 삭제 아님)"
    )
    assert archived_file.read_bytes() == _IMAGE_BYTES, (
        "보관된 이미지 내용은 원본과 동일해야 한다(이동일 뿐 삭제·훼손 아님)"
    )
    assert not stored_file_after.exists(), (
        "이동 후 저장 루트에는 파일이 남아 있지 않아야 한다(보관 위치로 옮겨짐)"
    )
    assert archived_rel_path.startswith(f"{ws_id}/"), (
        "보관 경로도 WS 격리 상대 경로여야 한다(8.8)"
    )

    # 보관 첨부는 조회 불가(404, Req 6.2).
    assert viewer.get(url).status_code == 404, "보관된 이미지는 조회 불가(404)"


# =============================================================================
# (3) 붙여넣기 보호 — 미저장 새 붙여넣기는 보관 안 함 (Req 5.3)
# =============================================================================


def test_unsaved_paste_is_protected(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """어떤 저장 버전에도 반영되지 않은 새 붙여넣기 이미지는 참조 소멸로 간주하지 않는다(Req 5.3).

    문서에 현재 버전(참조 없음)을 만든 뒤 이미지를 붙여넣고, att.created_at 을 현재 버전보다
    **엄격히 나중**으로 핀 고정한다(미저장 새 붙여넣기 상태). 현재 버전이 이 이미지를 참조하지
    않지만, 붙여넣기 보호(`att.created_at > current_version.created_at`)가 참조 판정보다 먼저
    적용되어 보관하지 않는다 → is_archived 유지·GET 200. 편집 중 붙여넣기 직후 오아카이브 방지.
    """
    doc_id = doc_tree_scenario.child_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    # 현재 버전을 먼저 만든다(참조 없음) → 이미지가 8.7 스코프(현재 버전 존재)에는 들되,
    # 붙여넣기 보호로 걸러지는 경로를 명확히 격리한다.
    _save_version(editor, doc_id, _no_ref_body())

    created = _upload_image(editor, doc_id)
    assert created.status_code == 201, (
        f"editor 이미지 업로드 201: {created.status_code} {created.text}"
    )
    att_id = created.json()["id"]
    url = created.json()["url"]

    # 붙여넣기 보호: att.created_at 을 현재 버전보다 엄격히 나중으로 핀(미저장 새 붙여넣기).
    _pin_attachment_created_at(harness, att_id, _LATE)

    # 스윕 — 붙여넣기 보호로 보관되지 않음(0).
    assert archival_sweep.sweep(_NOW) == 0, (
        "현재 버전보다 나중 생성된 미저장 붙여넣기 이미지는 보관되지 않아야 한다(sweep 0, Req 5.3)"
    )

    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is False, "미저장 붙여넣기 이미지는 미보관 유지(붙여넣기 보호, Req 5.3)"
    assert viewer.get(url).status_code == 200, "붙여넣기 보호 이미지는 계속 조회 가능(200)"


# =============================================================================
# (4) 이미지 한정 — 일반 파일은 참조 소멸로 보관 안 함 (Req 5.6)
# =============================================================================


def test_general_file_not_archived_by_dereference(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """일반 파일 첨부(kind=file)는 참조 소멸 아카이브(8.7) 대상이 아니다(Req 5.6).

    active 문서에 일반 파일을 첨부하고(현재 버전이 참조하지 않음) 스윕해도, 8.7 은 이미지 종류에
    한정되므로 파일은 보관되지 않는다(파일의 보관 이동은 8.6 완전삭제 반응 전용이며 문서는
    삭제되지 않았다). is_archived 유지·GET 200.
    """
    doc_id = doc_tree_scenario.grandchild_id
    editor = doc_tree_scenario.editor_client
    viewer = doc_tree_scenario.scenario.viewer_client

    # 현재 버전을 만들되 파일을 참조하지 않는다(참조 소멸 상태를 파일에 대해 재현).
    _save_version(editor, doc_id, _no_ref_body())

    created = _upload_file(editor, doc_id)
    assert created.status_code == 201, (
        f"editor 파일 업로드 201: {created.status_code} {created.text}"
    )
    att_id = created.json()["id"]
    url = created.json()["url"]
    assert created.json()["kind"] == AttachmentKind.FILE.value, "일반 파일 kind=file"

    # 스윕 — 파일은 8.7 스코프(image 한정) 밖이고 문서도 삭제되지 않아 보관되지 않는다(0).
    assert archival_sweep.sweep(_NOW) == 0, (
        "일반 파일 첨부는 참조 소멸(8.7)로 보관되지 않아야 한다(sweep 0, Req 5.6)"
    )

    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att.is_archived is False, "일반 파일은 참조 소멸로 보관되지 않는다(Req 5.6)"
    assert viewer.get(url).status_code == 200, "미보관 파일은 계속 조회 가능(200)"


# =============================================================================
# (5) 관측 전용 — s12 는 버전·현재 버전을 바꾸지 않는다 (Req 5.4/7.7)
# =============================================================================


def test_sweep_is_observation_only_versions_unchanged(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """s12 스윕은 저장·버전 생성·전이를 수행하지 않고 현재 버전 참조 관측으로만 판정한다
    (Req 5.4·7.7).

    v1(참조)·v2(참조 제거) 를 s09 저장 경로로 만든다 → 스윕이 참조 소멸 이미지를 보관하더라도,
    문서의 `current_version_id` 와 버전 수는 스윕 **전·후 동일**하다(s12 가 새 버전·전이를 만들지
    않음). 저장 경로가 만든 버전 상태(v2 가 현재·버전 2개)를 API 응답으로 포착하고, 스윕 후 DB
    관측이 그와 동일함을 단언한다.
    """
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client

    created = _upload_image(editor, doc_id)
    att_id = created.json()["id"]
    url = created.json()["url"]

    # s09 저장 경로가 버전을 만든다: v2 가 현재, 버전 2개(관측 기준값을 API 응답으로 포착).
    _v1 = _save_version(editor, doc_id, _ref_body(url))
    v2 = _save_version(editor, doc_id, _no_ref_body())
    _pin_attachment_created_at(harness, att_id, _EARLY)
    expected_current = v2["id"]
    expected_count = 2

    # 스윕 — 참조 소멸 이미지 1건이 보관됨(스윕이 실제로 동작했음을 확인).
    assert archival_sweep.sweep(_NOW) == 1, "참조 소멸 이미지 1건이 보관되어야 한다(스윕 동작)"

    # (관측 전용) 스윕 후에도 현재 버전·버전 수는 s09 저장이 만든 값 그대로 — s12 는 버전·전이를
    # 만들지 않는다(Req 5.4·7.7).
    after_current, after_count = _doc_version_state(harness, doc_id)
    assert after_current == expected_current, (
        "s12 스윕은 새 버전을 만들지 않으므로 current_version_id 는 v2 그대로여야 한다(Req 7.7)"
    )
    assert after_count == expected_count, (
        "s12 스윕은 버전을 추가하지 않으므로 버전 수는 s09 저장 결과(2)와 동일해야 한다(Req 5.4)"
    )

    # 보관은 되었으되(관측 판정 결과) 저장·버전 상태는 s12 가 건드리지 않았음을 함께 확인.
    with harness.session_local() as db:
        assert db.get(Attachment, att_id).is_archived is True, (
            "관측 판정으로 참조 소멸 이미지는 보관됨(저장·버전은 불변)"
        )
