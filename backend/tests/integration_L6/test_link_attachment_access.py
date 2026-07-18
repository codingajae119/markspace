"""링크 경유 첨부 접근·연동 차단 스위트 (Task 2.4 / Req 5.1, 5.2, 5.3, 5.4, 5.5,
design §LinkAttachmentAccessSuite · §System Flows(링크 경유 첨부 접근·연동 차단 8.4·8.5)).

실제 결합된 런타임(마이그레이션 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕**s12**⊕**s14**) +
role별 실 세션 + 익명 공개 클라이언트 + 저장/보관 루트만 tmp 로 격리(`tmp_attachment_roots`) +
부팅 앱과 동일 세션 팩토리로 조립한 실제 s12 `ArchivalSweepService`)에서 **링크 경유 첨부 접근
(8.4)과 게이트·status·보관·격리 연동 차단(8.5, L5↔L6)** 을 mock 없이 e2e 로 관찰한다. 대조
기준은 s14 design 이 아니라 s01 단일 소스(카탈로그 행 37 `GET /public/{token}/attachments/{aid}`·
공개 경로 404 통일·불변식 INV-6·INV-7)다.

다섯 개의 단언 그룹(task 2.4):

- **Group 1 — 링크 경유 스트리밍 + 참조 재작성(5.1 / 8.4)**: 공유 문서에 s12 로 올린 첨부를 익명
  `GET /public/{token}/attachments/{aid}` 로 조회 → 200 바이너리 스트림(업로드 바이트 일치·
  content-type 비-JSON); 공개 렌더 HTML 의 `/attachments/{id}` 참조가 링크 스코프 경로
  `/public/{token}/attachments/{id}` 로 재작성됨(id 경계 정확 매칭).
- **Group 2 — 연동 차단(5.2 / 8.5)**: 게이트 off·문서 trashed 시 링크 경유 첨부 접근도 공개 렌더와
  동일한 실시간 게이트로 404 로 함께 차단.
- **Group 3 — 보관 차단(5.3 / INV-7)**: 참조 소멸(dereference) 경로로 문서는 active·공유 상태를
  유지한 채 첨부만 실제 아카이브 스윕으로 `is_archived=true` 로 만들면, 링크 경유 접근이 s12
  규약대로 role·경로 무관 404(보관 차단이 게이트·범위가 아니라 INV-7 때문임을 200-전/404-후
  대조로 격리).
- **Group 4 — 범위·격리 404(5.4 / INV-6)**: 공유 서브트리 밖 문서 첨부·다른 워크스페이스 첨부는
  링크 경유로 404(범위 밖·다른 WS 비노출).
- **Group 5 — s12 재사용(5.5)**: 링크 경유 바이너리가 s12 인증 서빙(`GET /attachments/{aid}`)이
  같은 첨부에 대해 돌려주는 바이트와 **동일**함을 관찰해, s14 가 저장·격리·보관 판정을 재구현하지
  않고 s12 `serve_attachment`·`AttachmentRepository.get` 을 재사용함을 확인.

**보관 차단 격리(Group 3, L5 `test_save_dereference_combination` 패턴 답습)**: INV-7 로 인한 404 를
게이트/범위 404 와 혼동하지 않도록, 문서를 삭제·trashed 하지 않고 **active·공유 상태로 유지한 채**
첨부만 보관시킨다. 이를 위해 v1(참조 포함)→v2(참조 제거) 실제 저장(s09)으로 현재 버전이 이미지를
참조하지 않게 만들고, `att.created_at` 을 현재 버전 이전(_EARLY)으로 핀 고정(붙여넣기 보호 통과·
초 정밀도 결정성)한 뒤 실제 아카이브 스윕(8.7 참조 소멸)으로 보관 이동시킨다. 붙여넣기 보호는
`att.created_at > current_version.created_at` 을 DATETIME(0) 초 정밀도로 비교하므로, 업로드·저장이
같은 초에 떨어질 때의 비결정성을 막으려 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로
직접 초단위 값을 핀 고정한다(L4 `pin_trashed_at` 규약 답습 — 테스트 시드 조작이며 스윕 대역이 아님).

첨부 업로드·저장(s09)·아카이브 스윕(s12)·게이트 토글(s05)·문서 삭제(s10)는 모두 실제 라우트·실제
스윕·실제 엔진 코드다(L5→L4/L3/L2 헬퍼 재사용, mock 없음). 실 동작이 계약과 다르면(예: 보관 첨부가
링크 경유로 서빙되거나 다른 WS 파일이 노출) 단언을 약화시키지 않고 그대로 실패시킨다 — 그것은
원인 spec(s14/s12)에서 고쳐야 할 실제 INV-6/INV-7 위반이다.

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
`s12`·`s14` 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행한다(`s01` 수정 시
모든 체크포인트).
"""

import re
from datetime import datetime

from app.models import Attachment
from tests.integration_L6 import helpers

# 업로드 바이너리(작은 PNG 시그니처 + 페이로드; 25MiB 한도 이하라 서빙·보관 경로만 관찰).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l6-link-attachment-image-payload"

# 아카이브 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 8.7 은 now 에 직접 의존하지 않으나
# 배치 계약 일관성상 API 가 받는다(붙여넣기 보호 경계 판정은 att.created_at vs 현재 버전으로 함).
_NOW = datetime(2026, 7, 17, 12, 0, 0)

# 첨부 created_at 핀 값(마이크로초 0). 참조 소멸 후보는 현재 버전 이전(_EARLY, <=)으로 고정해
# 붙여넣기 보호를 통과시키고 초 정밀도 비교를 결정적으로 만든다(현재 버전은 실제 저장 시각 ~2026-07).
_EARLY = datetime(2026, 1, 1, 0, 0, 0)


def _pin_attachment_created_at(harness, attachment_id: int, ts: datetime) -> None:
    """첨부 ``created_at`` 을 결정적 초단위(마이크로초 0) 값으로 핀 고정한다(붙여넣기 보호 결정성).

    업로드·저장이 같은 벽시계 초에 떨어져 `att.created_at` vs `current_version.created_at`
    비교가 비결정적이 되는 것을 막으려, 부팅 앱과 동일 세션 팩토리(`harness.session_local`)로
    직접 DATETIME(0) 정합 값을 부여한다(L5 `test_save_dereference_combination`
    `_pin_attachment_created_at` 규약 답습 — 테스트 시드 조작이며 스윕 서비스는 이 값을 저장하지
    않는다).
    """
    ts = ts.replace(microsecond=0)
    with harness.session_local() as db:
        att = db.get(Attachment, attachment_id)
        assert att is not None, f"핀 대상 첨부가 있어야 한다: id={attachment_id}"
        att.created_at = ts
        db.commit()


def _assert_reference_rewritten(html: str, token: str, attachment_id: int) -> None:
    """공개 렌더 HTML 의 첨부 참조가 링크 스코프 경로로 재작성됐음을 id 경계 정확히 단언한다(8.4).

    `/attachments/{id}` 는 `/public/{token}/attachments/{id}` 로 재작성되어야 한다. 검증 teeth:
    (1) `/public/{token}/attachments/{id}` 가 최소 1회 등장(재작성 성립),
    (2) `/attachments/{id}`(id 경계 `(?![0-9])`, `/attachments/5` vs `/attachments/50` 비오염)
        의 **모든** 등장이 `/public/{token}` 접두로 감싸여 있어(= bare 개수 == public 개수) 재작성
        안 된 bare 참조가 하나도 남지 않았음을 확인한다.
    """
    bare = re.compile(rf"/attachments/{attachment_id}(?![0-9])")
    scoped = re.compile(
        rf"/public/{re.escape(token)}/attachments/{attachment_id}(?![0-9])"
    )
    scoped_count = len(scoped.findall(html))
    bare_count = len(bare.findall(html))
    assert scoped_count >= 1, (
        f"공개 렌더 HTML 에 링크 스코프 참조 /public/{token}/attachments/{attachment_id} 가 "
        f"있어야 한다(8.4 재작성): {html!r}"
    )
    # 모든 /attachments/{id} 등장이 /public/{token}/... 안에 있어야 한다(bare 잔존 0).
    assert bare_count == scoped_count, (
        f"모든 /attachments/{attachment_id} 참조는 /public/{token}/... 로 재작성되어야 한다"
        f"(bare={bare_count} scoped={scoped_count}): {html!r}"
    )


# =============================================================================
# Group 1 — 링크 경유 첨부 스트리밍 + 참조 재작성 (Req 5.1 / 8.4)
# =============================================================================


def test_link_via_file_streams_binary(share_scenario, tmp_attachment_roots):
    """활성 링크로 공유 문서 첨부를 익명 조회 → 200 바이너리 스트림(업로드 바이트 일치, 비-JSON) (5.1, 8.4).

    editor 가 공유 루트 문서에 이미지를 업로드(s12) → 익명 `GET /public/{token}/attachments/{aid}`
    가 인증 없이 200 으로 그 첨부 바이너리를 스트리밍한다. 응답 바이트가 업로드 바이트와 정확히
    일치하고 content-type 이 JSON 이 아님을 확인한다(스키마 본문이 아니라 binary 스트림).
    """
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    doc_id = share_scenario.document_id
    token = share_scenario.token

    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]

    resp = helpers.attempt_public_attachment(public, token, aid)
    assert resp.status_code == 200, (
        f"활성 링크 경유 첨부 조회는 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.content == _IMAGE_BYTES, (
        "링크 경유 첨부 응답 바이트는 업로드 바이트와 정확히 일치해야 한다(8.4 이미지 로딩)"
    )
    content_type = resp.headers.get("content-type", "")
    assert not content_type.startswith("application/json"), (
        f"링크 경유 파일 응답은 JSON 본문이 아니라 binary 스트림이어야 한다: {content_type!r}"
    )


def test_public_render_rewrites_attachment_reference(
    share_scenario, tmp_attachment_roots
):
    """공개 렌더 HTML 의 `/attachments/{id}` 참조가 `/public/{token}/attachments/{id}` 로 재작성됨 (5.1, 8.4).

    이미지 업로드 → `save_with_reference`(s09 실제 저장)로 현재 버전 본문에 `/attachments/{id}`
    참조를 남긴다 → 익명 `GET /public/{token}` 공개 렌더의 루트 `content_html` 이 링크 스코프
    경로로 재작성된 참조를 담고(id 경계 정확), 재작성 안 된 bare 참조가 하나도 남지 않음을 확인한다.
    """
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    doc_id = share_scenario.document_id
    token = share_scenario.token

    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]

    # 현재 버전 본문에 `/attachments/{id}` 참조를 남긴다(s09 실제 저장, L5 헬퍼 재사용).
    helpers.l5_helpers.save_with_reference(editor, doc_id, aid)

    tree = helpers.public_render(public, token)
    root = tree["root"]
    assert root["id"] == doc_id, "공개 렌더 루트는 공유 문서여야 한다"
    _assert_reference_rewritten(root["content_html"], token, aid)


# =============================================================================
# Group 2 — 연동 차단 (Req 5.2 / 8.5): 게이트 off · 문서 trashed
# =============================================================================


def test_gate_off_blocks_link_via_file(share_scenario, tmp_attachment_roots):
    """게이트 off 시 링크 경유 첨부 접근이 공개 렌더와 동일하게 404 로 함께 차단됨 (5.2, 8.5).

    공유 문서에 이미지 업로드 → (대조) 게이트 on 상태에서 링크 경유 200 → owner 가 s05 경로로
    게이트 off(`is_shareable=false`) → 익명 `GET /public/{token}/attachments/{aid}` 가 실시간
    게이트로 404 로 차단됨(공개 렌더와 동일 게이트)을 확인한다.
    """
    owner = share_scenario.owner_client
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id
    token = share_scenario.token

    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]

    # (대조) 게이트 on 상태에서 링크 경유 200.
    assert helpers.attempt_public_attachment(public, token, aid).status_code == 200, (
        "게이트 off 이전 링크 경유 첨부 접근은 200 이어야 한다(대조 기준)"
    )

    # 게이트 off(s05 실제 라우트).
    helpers.set_gate(owner, ws_id, is_shareable=False)

    resp = helpers.attempt_public_attachment(public, token, aid)
    assert resp.status_code == 404, (
        f"게이트 off 후 링크 경유 첨부 접근은 404 로 차단되어야 한다(8.5): "
        f"{resp.status_code} {resp.text}"
    )


def test_trashed_document_blocks_link_via_file(share_scenario, tmp_attachment_roots):
    """공유 문서 trashed 시 링크 경유 첨부 접근도 공개 렌더와 동일하게 404 로 함께 차단됨 (5.2, 8.5).

    공유 문서에 이미지 업로드 → (대조) 200 → editor 가 `DELETE /documents/{id}`(s10 trashed
    캐스케이드) → 익명 링크 경유 첨부 접근이 문서 status 관측으로 404 로 차단됨을 확인한다(실시간
    게이트, 스윕 불필요).
    """
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    doc_id = share_scenario.document_id
    token = share_scenario.token

    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]

    # (대조) trashed 이전 200.
    assert helpers.attempt_public_attachment(public, token, aid).status_code == 200, (
        "문서 trashed 이전 링크 경유 첨부 접근은 200 이어야 한다(대조 기준)"
    )

    # 문서 trashed(s10 실제 라우트).
    helpers.l3_helpers.delete_document(editor, doc_id)

    resp = helpers.attempt_public_attachment(public, token, aid)
    assert resp.status_code == 404, (
        f"문서 trashed 후 링크 경유 첨부 접근은 스윕 없이 즉시 404 여야 한다(8.5, 실시간 게이트): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 3 — 보관 차단 (Req 5.3 / INV-7)
# =============================================================================


def test_archived_attachment_blocked_while_document_active(
    share_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """문서를 active·공유로 유지한 채 첨부만 보관되면 링크 경유 접근이 404(INV-7, 게이트 아님) (5.3).

    보관 차단이 게이트·범위가 아니라 오직 보관(INV-7) 때문임을 **독립 관측**으로 격리한다:
    (1) 공유 루트에 이미지 업로드(첨부는 공유 문서 소속 = 범위 안),
    (2) `save_with_reference`(v1 참조 포함) → `save_without_reference`(v2 참조 제거)로 현재 버전이
        이미지를 참조하지 않게 만든다(s09 실제 저장; 문서는 active·공유 유지),
    (3) `att.created_at` 을 현재 버전 이전(_EARLY)으로 핀(붙여넣기 보호 통과),
    (4) 실제 아카이브 스윕(8.7 참조 소멸)으로 이미지 1건 보관 이동 → `is_archived=true` 확정,
    (5) 문서가 여전히 active·공유(게이트 on) — 공개 렌더 200 으로 게이트·status 정상을 독립 확인,
    (6) 그럼에도 링크 경유 첨부 접근이 s12 규약대로 404 → 이 404 는 게이트·범위가 아니라 오직
        보관(INV-7) 때문임이 격리된다(공개 렌더 200 + 범위 안 첨부 + is_archived=true → 404=보관).

    보관 이동 직전에 대상 첨부를 서빙하지 않는다: `StreamingResponse` 가 남긴 파일 핸들이 Windows
    에서 `move_to_archive`(os.rename)를 간헐 실패시켜 스윕이 그 첨부를 건너뛰는(processed=0) 비결정
    성을 유발하기 때문이다(L5 결정적 아카이브 스위트가 스윕 직전 서빙을 하지 않는 규약 답습).
    보관 전 링크 경유 200 자체는 :func:`test_link_via_file_streams_binary` 가 이미 독립 증명한다.
    """
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    doc_id = share_scenario.document_id
    token = share_scenario.token

    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]

    # (2) v1(참조 포함) → v2(참조 제거) 실제 저장 → 현재 버전이 이미지를 참조하지 않는다(문서 active 유지).
    helpers.l5_helpers.save_with_reference(editor, doc_id, aid)
    helpers.l5_helpers.save_without_reference(editor, doc_id)
    # (3) 붙여넣기 보호 통과(att.created_at <= 현재 버전).
    _pin_attachment_created_at(harness, aid, _EARLY)

    # (4) 실제 아카이브 스윕 — 참조 소멸 이미지 1건 보관 이동.
    processed = helpers.l5_helpers.run_archival_sweep(archival_sweep, _NOW)
    assert processed == 1, (
        f"참조 소멸 이미지 1건만 보관 이동되어야 한다(결정적 하네스): {processed}"
    )
    assert helpers.l5_helpers.attachment_is_archived(harness.session_local, aid) is True, (
        "참조 소멸 이미지는 보관됨(is_archived=true, INV-7 보관 차단의 전제)"
    )

    # 문서는 여전히 active·공유(게이트 on) — 공개 렌더는 200(보관 차단이 게이트·status 아님을 확증).
    assert helpers.attempt_public_render(public, token).status_code == 200, (
        "첨부만 보관됐을 뿐 문서는 active·공유 유지이므로 공개 렌더는 여전히 200 이어야 한다"
    )

    # (5) 보관 첨부는 링크 경유로 role·경로 무관 404(INV-7, s12 serve 차단).
    resp = helpers.attempt_public_attachment(public, token, aid)
    assert resp.status_code == 404, (
        f"보관 첨부는 링크 경유로도 404 여야 한다(INV-7, 게이트·범위 아님): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 4 — 범위·격리 404 (Req 5.4 / INV-6)
# =============================================================================


def test_out_of_subtree_attachment_404(share_scenario, tmp_attachment_roots):
    """공유 서브트리 밖 문서의 첨부는 링크 경유로 404(링크 범위 밖 비노출, INV-6) (5.4).

    같은 워크스페이스에 공유 문서 서브트리(root←child←grandchild) 밖의 **별도 루트 문서**를 만들고
    거기에 이미지를 업로드한다. 링크는 여전히 유효(root active·게이트 on)하지만 그 첨부는 공유
    서브트리 구성원이 아니므로 `GET /public/{token}/attachments/{other_aid}` 는 404 로 비노출된다.
    """
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    ws_id = share_scenario.workspace_id
    token = share_scenario.token

    # 같은 WS, 공유 서브트리 밖의 별도 루트 문서(parent 없음) + 이미지 업로드.
    other_doc = helpers.l3_helpers.create_document(editor, ws_id, "범위밖-별도문서")
    other_att = helpers.l5_helpers.upload_image(editor, other_doc["id"], content=_IMAGE_BYTES)
    other_aid = other_att["id"]

    resp = helpers.attempt_public_attachment(public, token, other_aid)
    assert resp.status_code == 404, (
        f"공유 서브트리 밖 문서의 첨부는 링크 경유로 404 여야 한다(INV-6 범위 밖 비노출): "
        f"{resp.status_code} {resp.text}"
    )


def test_other_workspace_attachment_404(share_scenario, tmp_attachment_roots):
    """다른 워크스페이스의 첨부는 링크 경유로 404(WS 격리 비노출, INV-6) (5.4).

    owner 가 **다른 워크스페이스**를 만들고(같은 authed owner 가 두 WS 소유) 거기에 문서·이미지를
    올린다. 공유 링크는 원래 워크스페이스 문서에 대한 것이므로, 다른 WS 첨부에 대한 `GET
    /public/{token}/attachments/{other_ws_aid}` 는 WS 격리로 404 로 비노출된다(INV-6).
    """
    owner = share_scenario.owner_client
    public = share_scenario.public_client
    token = share_scenario.token

    # 다른 워크스페이스 + 문서 + 이미지(owner 는 새 WS 의 owner 로 자동 등록되어 업로드 가능).
    other_ws_id = helpers.l2_helpers.create_workspace(owner, "다른워크스페이스-격리")
    other_doc = helpers.l3_helpers.create_document(owner, other_ws_id, "다른WS-문서")
    other_att = helpers.l5_helpers.upload_image(owner, other_doc["id"], content=_IMAGE_BYTES)
    other_ws_aid = other_att["id"]

    resp = helpers.attempt_public_attachment(public, token, other_ws_aid)
    assert resp.status_code == 404, (
        f"다른 워크스페이스의 첨부는 링크 경유로 404 여야 한다(INV-6 WS 격리 비노출): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 5 — s12 재사용 (Req 5.5): 링크 경유 바이너리 == s12 인증 서빙 바이너리
# =============================================================================


def test_link_via_file_reuses_s12_serving_byte_identical(
    share_scenario, tmp_attachment_roots
):
    """링크 경유 바이너리가 s12 인증 서빙 바이너리와 byte-identical — s14 가 s12 서빙 재사용 (5.5).

    s14 는 저장·격리·보관 판정을 재구현하지 않고 s12 `AttachmentService.serve_attachment`·
    `AttachmentRepository.get` 을 재사용한다. 이를 관측으로 확인한다: 같은 첨부에 대해
    (1) 익명 링크 경유 `GET /public/{token}/attachments/{aid}` 의 바이트와
    (2) s12 인증 `GET /attachments/{aid}`(viewer 세션) 의 바이트가 **동일**하고, 둘 다 업로드
    바이트와 일치함을 확인한다(같은 저장 서빙 경로 → 재구현이 아니라 재사용).
    """
    editor = share_scenario.editor_client
    viewer = share_scenario.viewer_client
    public = share_scenario.public_client
    doc_id = share_scenario.document_id
    token = share_scenario.token

    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]

    # (1) 링크 경유 익명 서빙(s14 공개 경로 → s12 위임).
    link_resp = helpers.public_attachment(public, token, aid)
    # (2) s12 인증 서빙(viewer 세션, 같은 첨부).
    s12_resp = helpers.l5_helpers.get_attachment(viewer, aid)

    assert link_resp.content == s12_resp.content, (
        "링크 경유 바이너리는 s12 인증 서빙 바이너리와 byte-identical 해야 한다"
        "(s14 가 s12 serve_attachment 재사용, 재구현 아님)"
    )
    assert link_resp.content == _IMAGE_BYTES, (
        "링크 경유·s12 서빙 바이너리는 업로드 바이트와도 일치해야 한다(동일 저장 서빙 경로)"
    )
