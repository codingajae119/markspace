"""L5 하네스 스모크 — Task 1.1 관찰 가능 완료 기준 (Req 1.1·1.2·1.3·1.4·1.6, design §L5TestHarness).

이 스위트는 태스크 1.1 하네스가 실제로 결합 환경(L4 하네스 재사용 + s12 첨부 업로드/서빙·
아카이브 스윕·파일시스템 관찰)을 제공하는지 mock 없이 확인한다("역-RED": 새 테스트가 실제
구현 위에서 **통과**하는 것이 검증). 검증 대상은 conftest 신규 픽스처
(``tmp_attachment_roots``·``archival_sweep``)와 재-import 된 L4/L3 픽스처
(``doc_tree_scenario``·``lock_scenario``·``sweep_access``)이며, 각 픽스처가 부팅 앱
(s02·s03·s05·s07·s09·s10·**s12 첨부 라우터 + 아카이브 스케줄러**가 조립된 상태)·마이그레이션
DB·실제 엔진/스윕·실제 파일시스템과 결합됨을 관찰한다. 관찰 가능 완료 기준(tasks.md 1.1):

1. editor 가 ``POST /documents/{id}/attachments`` 에서 201 과 ``AttachmentRead.url``
   (=`/attachments/{id}`, kind=image)을 받는다(첨부 라우터 결합 증거).
2. ``GET /attachments/{id}`` 가 바이너리(200 + content bytes)를 돌려준다(서빙 라우터 결합).
3. ``archival_sweep.sweep(now)`` 가 ``now`` 주입 호출에서 결과(처리 건수 int)를 반환한다
   (실제 s12 `ArchivalSweepService` 결합, mock 아님).
4. 재-import 된 L4 픽스처(``lock_scenario``·``sweep_access``)가 수집 가능하다(두 editor 구성·
   retention 스윕 결과 int).

L4(및 그것이 재사용하는 L3/L2/L1) 하네스를 재사용·확장하며 애플리케이션 코드·config.yml·
하위 하네스는 만지지 않는다. mock·stub·pytest.skip 미사용. 저장 루트는 ``tmp_attachment_roots``
로 격리해 실제 ``./var/attachments`` 를 오염시키지 않는다.
"""

import io
from datetime import datetime

from tests.integration_L3 import helpers as l3_helpers

# 업로드 스모크 바이너리(작은 PNG 시그니처 + 페이로드; 25MiB 한도 이하라 저장/서빙 경로만 검증).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l5-harness-smoke-image-payload"

# 아카이브 스윕에 주입할 고정 기준 시각(결정성; 마이크로초 0, DATETIME(0) 정합).
_SWEEP_NOW = datetime(2026, 7, 17, 0, 0, 0)


def _upload_image(client, document_id):
    """``POST /documents/{id}/attachments`` 로 이미지 하나를 multipart 업로드하고 응답을 반환한다.

    파일 필드명은 계약상 ``file`` 이며, content-type ``image/png`` 이 라우터의 kind 추론
    (image/* → image)을 구동한다. 상태는 호출자가 단언한다.
    """
    return client.post(
        f"/documents/{document_id}/attachments",
        files={"file": ("pic.png", io.BytesIO(_IMAGE_BYTES), "image/png")},
    )


# =============================================================================
# 1) 첨부 업로드·서빙 왕복 — s12 첨부 라우터 결합 (관찰 가능 완료 ①②)
# =============================================================================


def test_editor_uploads_image_and_serves_binary(
    doc_tree_scenario, tmp_attachment_roots
):
    """editor 가 이미지를 업로드하면 201 + ``AttachmentRead.url``(=/attachments/{id},
    kind=image)을 받고, 그 url 로 ``GET`` 하면 업로드한 바이너리를 200 으로 돌려받는다
    (s12 첨부 업로드·서빙 라우터가 부팅 앱에 조립됨을 관찰, 저장은 tmp 루트로 격리).
    """
    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client

    resp = _upload_image(editor, doc_id)
    assert resp.status_code == 201, (
        f"editor 이미지 업로드 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    att_id = body["id"]
    assert body["url"] == f"/attachments/{att_id}", "url 은 /attachments/{id} 파생 규약"
    assert body["kind"] == "image", "image/png 업로드 kind=image"

    # 응답 url 로 viewer(멤버)가 바이너리를 왕복 조회한다(서빙 라우터 결합).
    viewer = doc_tree_scenario.scenario.viewer_client
    serve = viewer.get(body["url"])
    assert serve.status_code == 200, (
        f"viewer 조회 200 이어야 한다: {serve.status_code} {serve.text}"
    )
    assert serve.content == _IMAGE_BYTES, "업로드한 정확한 바이너리를 돌려받아야 한다"


def test_tmp_attachment_roots_isolate_storage_on_disk(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """``tmp_attachment_roots`` 가 저장 루트를 tmp 로 격리해, 업로드 파일이 실제
    ``./var/attachments`` 가 아니라 tmp 저장 루트의 WS 격리 경로에 물리적으로 쓰인다
    (파일시스템 관찰 픽스처 결합 증거).
    """
    from app.models import Attachment

    doc_id = doc_tree_scenario.root_id
    editor = doc_tree_scenario.editor_client

    resp = _upload_image(editor, doc_id)
    assert resp.status_code == 201, f"{resp.status_code} {resp.text}"
    att_id = resp.json()["id"]

    with harness.session_local() as db:
        att = db.get(Attachment, att_id)
        assert att is not None, "첨부 레코드가 커밋되어 있어야 한다"
        stored_path = att.file_path

    disk_file = tmp_attachment_roots.file_storage_root / stored_path
    assert disk_file.is_file(), "저장 파일이 tmp 저장 루트의 WS 격리 위치에 존재해야 한다"
    assert disk_file.read_bytes() == _IMAGE_BYTES, "디스크 저장 내용은 업로드와 동일"


# =============================================================================
# 2) 아카이브 스윕 접근 — sweep(now) 결과 반환 (관찰 가능 완료 ③)
# =============================================================================


def test_archival_sweep_returns_result_from_injected_now(archival_sweep):
    """``archival_sweep`` 픽스처가 부팅 앱과 동일 세션으로 **주입된 now** 기준 실제 s12
    ``ArchivalSweepService.sweep(db, now)`` 를 1회 구동해 처리 건수(int)를 반환한다
    (실제 s12 코드 결합, mock 아님). 대상이 없으면 0 이며 오류 없이 완료된다.
    """
    processed = archival_sweep.sweep(_SWEEP_NOW)

    assert isinstance(processed, int), "아카이브 스윕은 처리 건수(int)를 반환해야 한다"
    assert processed >= 0, "처리 건수는 음수가 아니어야 한다"


# =============================================================================
# 3) 재-import 된 L4 픽스처 수집성 — 두 editor·retention 스윕 (관찰 가능 완료 ④)
# =============================================================================


def test_lock_scenario_provides_two_distinct_editors(lock_scenario):
    """재-import 된 L4 ``lock_scenario`` 픽스처가 수집 가능하며 동일 워크스페이스에 서로 다른
    두 editor(A·B)를 제공한다(L4 하네스 재사용 증거).
    """
    assert lock_scenario.editor_a_user_id != lock_scenario.editor_b_user_id, (
        "editor A·B 는 서로 다른 사용자여야 한다(L4 하네스 재사용 확인)"
    )


def test_sweep_access_returns_int_from_injected_now(sweep_access):
    """재-import 된 L4 ``sweep_access`` 픽스처가 수집 가능하며 주입된 ``now`` 기준 실제 s10
    ``RetentionSweepService`` 를 구동해 int 결과를 반환한다(L4 하네스 재사용 증거).
    """
    purged = sweep_access.sweep(_SWEEP_NOW)

    assert isinstance(purged, int), "retention 스윕은 전환 묶음 수(int)를 반환해야 한다"


# 미사용 경고 방지용 참조(재-export 확인). l3_helpers 는 후속 스위트가 재사용한다.
assert l3_helpers is not None
