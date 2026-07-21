"""전 계층 불변식 회귀 스위트 (Task 2.5 / Req 6.1, 6.2, 6.3, 6.4, 6.5,
design §FullStackInvariantSuite · §Requirements Traceability 6.1~6.5).

완전히 조립된 전체 시스템(마이그레이션 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12⊕
**s14 공유 라우터·무효화 스케줄러**) + role별 실 세션 + 익명 공개 클라이언트 + 실제
`ShareInvalidationSweep`/`RetentionSweepService`/`ArchivalSweepService`)에서 s01 불변식
카탈로그 INV-1~12(design.md §Invariants Catalog, s01-contract-foundation)가 최상위 계층(공유)
결합 이후에도 **회귀 없이** 모두 성립함을 mock 없이 관찰한다. 대조 기준은 개별 spec design 이
아니라 s01 단일 소스(INV-1~12 원문)다.

이 스위트는 각 하위 체크포인트(L1~L5)가 이미 소유한 세부 증명을 **전부 재증명하지 않고**,
공유 계층이 얹힌 실제 조립 시스템에서 12개 불변식을 각각 최소 1회 재확인한다(공유가 건드리는
seam — INV-2 공유 발급/토글·INV-3 admin 공유·INV-4 share_link·INV-6 링크 경유 파일·INV-8 —
에 특히 주의). 실 동작이 계약과 다르면(불변식 위반) 단언을 약화시키지 않고 그대로 실패시킨다 —
그것은 원인 upstream spec 에서 고쳐야 할 실제 불변식 위반이다(BLOCKED 라우팅).

s01 INV-1~12 원문(design.md §Contract / Invariants Catalog):
- INV-1  권한은 워크스페이스 단위만, 문서별 개별 권한 없음
- INV-2  viewer 는 문서·휴지통 변경 불가(읽기 전용) — 공유 링크 변경 포함
- INV-3  admin 접근은 어떤 권한 검사로도 차단 안 됨(비멤버 WS bypass)
- INV-4  user·document·attachment·share_link 물리 삭제 없음(dangling FK 없음)
- INV-5  문서 이동 시 사이클 없음
- INV-6  문서·이동·공유·링크 경유 파일은 WS 경계를 넘지 않음
- INV-7  deleted 문서·보관 파일 복원 경로 없음
- INV-8  무효화된 공유 링크는 재발급 없이 접근 불가
- INV-9  문서당 편집 잠금 최대 1인(`document.lock_user_id` 단일 컬럼)
- INV-10 삭제/복구/완전삭제는 묶음 단위 원자적·비병합
- INV-11 독립 묶음 자식은 부모보다 먼저 trash(child.trashed_at ≤ parent.trashed_at)
- INV-12 묶음 보관 만료는 각 trashed_at 기준 독립 산정

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
`s12`·`s14` 중 하나라도 수정되면 이 최종 체크포인트를 누적 집합 기준으로 재실행한다(`s01`
수정 시 모든 체크포인트).
"""

from datetime import datetime

from sqlalchemy import select

from app.models import (
    Attachment,
    Document,
    ShareLink,
    User,
    Workspace,
    WorkspaceMember,
)
from tests.integration_L6 import helpers

# 첨부 업로드 바이너리(작은 PNG 시그니처 + 페이로드; 25MiB 한도 이하라 서빙·보관 경로만 관찰).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l6-full-stack-invariant-image"

# 아카이브 스윕 주입 now(whole-second, DATETIME(0)). 붙여넣기 보호 경계 판정은 att.created_at
# vs 현재 버전으로 하므로 now 는 배치 계약 일관성상만 받는다(L5/2.4 규약 답습).
_NOW = datetime(2026, 7, 17, 12, 0, 0)

# 참조 소멸 후보 첨부 created_at 핀 값(마이크로초 0, 현재 버전 이전 → 붙여넣기 보호 통과).
_EARLY = datetime(2026, 1, 1, 0, 0, 0)


# =============================================================================
# 공용 관측 헬퍼 — 부팅 앱과 동일 세션 팩토리(harness.session_local)로 라이브 DB 관찰
# =============================================================================


def _admin_user_id(harness) -> int:
    """시드된 단일 admin(`is_admin=True`)의 사용자 id 를 라이브 DB 로 관측한다(INV-3 비멤버 확인용)."""
    with harness.session_local() as db:
        admin = db.execute(select(User).where(User.is_admin.is_(True))).scalars().first()
        assert admin is not None, "시드 admin 사용자가 존재해야 한다"
        return admin.id


def _membership_role(harness, workspace_id: int, user_id: int) -> str | None:
    """(workspace, user) 멤버십 role 을 실제 `workspace_member` DB 질의로 관측한다(비멤버면 None)."""
    with harness.session_local() as db:
        member = (
            db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
            )
            .scalars()
            .first()
        )
        return None if member is None else member.role


def _document_status(harness, document_id: int) -> str | None:
    """문서 `status`(active/trashed/deleted)를 라이브 DB 로 관측한다(없으면 None)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.status


def _document_trashed_at(harness, document_id: int) -> datetime | None:
    """문서 `trashed_at` 을 라이브 DB 로 관측한다(INV-11 자식-먼저-trash 관찰)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        assert doc is not None, f"문서 {document_id} 가 존재해야 한다"
        return doc.trashed_at


def _document_lock_user_id(harness, document_id: int) -> int | None:
    """문서 `lock_user_id`(단일 컬럼)를 라이브 DB 로 관측한다(INV-9 잠금 단일성)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        assert doc is not None, f"문서 {document_id} 가 존재해야 한다"
        return doc.lock_user_id


def _bundle_id_for_root(editor, workspace_id: int, root_document_id: int) -> int:
    """휴지통 목록에서 루트 문서 id 로 묶음을 찾아 `bundle_id` 를 반환한다(2.3 패턴 답습)."""
    page = helpers.l4_helpers.list_trash(editor, workspace_id)
    for item in page["items"]:
        if item["root_document_id"] == root_document_id:
            return item["bundle_id"]
    raise AssertionError(
        f"루트 문서 {root_document_id} 의 휴지통 묶음을 찾지 못했다: items={page['items']!r}"
    )


def _pin_attachment_created_at(harness, attachment_id: int, ts: datetime) -> None:
    """첨부 `created_at` 을 결정적 초단위(마이크로초 0) 값으로 핀 고정한다(붙여넣기 보호 결정성, 2.4 답습)."""
    ts = ts.replace(microsecond=0)
    with harness.session_local() as db:
        att = db.get(Attachment, attachment_id)
        assert att is not None, f"핀 대상 첨부가 있어야 한다: id={attachment_id}"
        att.created_at = ts
        db.commit()


# =============================================================================
# Group 6.1 — 권한 WS 단위(INV-1) · viewer 읽기 전용(INV-2) · admin bypass(INV-3)
# =============================================================================


def test_inv1_edit_is_workspace_scoped_not_per_document_reads_open(share_scenario):
    """INV-1(편집): 편집 권한은 WS 단위로만 판정되고 문서별 개별 권한이 없다 — 균일 (6.1).
    아울러 s26 읽기 전역 개방으로 읽기는 멤버십과 무관하게 모든 문서에 균일 200 (Req 3.1·3.8).

    비멤버 활성 사용자(viewer·nonmember)는 워크스페이스의 **모든** 문서(root·child)를 균일하게
    읽을 수 있으나(읽기 개방 — 문서별 예외 없음), 어느 문서도 편집할 수 없다(편집은 멤버십
    요구 — 문서별 승격 없음). 편집 권한이 문서가 아니라 워크스페이스 멤버십에만 근거함을 확인한다
    (문서별 개별 권한 부여 경로 부재).
    """
    viewer = share_scenario.viewer_client
    nonmember = share_scenario.nonmember_client
    root_id = share_scenario.root_id
    child_id = share_scenario.child_id

    # 읽기 전역 개방: 두 비멤버 활성 사용자 모두 WS 의 모든 문서를 균일하게 읽는다(200, 예외 없음).
    for label, client in (("viewer(비멤버)", viewer), ("nonmember", nonmember)):
        assert helpers.l3_helpers.attempt_get_document(client, root_id).status_code == 200, (
            f"{label} root 읽기 개방 200(3.8)"
        )
        assert helpers.l3_helpers.attempt_get_document(client, child_id).status_code == 200, (
            f"{label} child 읽기 개방 200(3.8)"
        )

    # 편집은 WS 멤버십 요구: 두 비멤버 모두 어느 문서도 편집할 수 없다(균일 403, 문서별 승격 없음).
    for label, client in (("viewer(비멤버)", viewer), ("nonmember", nonmember)):
        assert helpers.l3_helpers.attempt_patch_title(client, root_id, "x").status_code == 403, (
            f"{label} root 편집 403(멤버십 요구, Req 4.6)"
        )
        assert helpers.l3_helpers.attempt_patch_title(client, child_id, "x").status_code == 403, (
            f"{label} child 편집 403(멤버십 요구, Req 4.6)"
        )


def test_inv2_viewer_is_read_only_including_share_links(share_scenario):
    """INV-2: viewer 는 문서·휴지통·**공유 링크** 변경을 할 수 없다 — 읽기 전용 (6.1).

    공유가 얹힌 시스템에서 viewer 의 읽기 전용 경계에 **공유 발급·토글**이 포함됨을 확인한다:
    viewer `POST /documents/{id}/share` 403·`PATCH .../share` 403·문서 편집(PATCH) 403·
    trash(DELETE) 403. 공유는 `require_ws_role(EDITOR)` 로 게이팅되므로 viewer 는 링크를 만들거나
    바꿀 수 없다(재발급 통일 원칙의 상위 게이트).
    """
    viewer = share_scenario.viewer_client
    doc_id = share_scenario.document_id

    # 문서 변경 불가.
    assert helpers.l3_helpers.attempt_patch_title(viewer, doc_id, "x").status_code == 403
    # 휴지통(삭제) 변경 불가.
    assert helpers.l3_helpers.attempt_delete_document(viewer, doc_id).status_code == 403
    # 공유 링크 발급 불가(INV-2 의 공유 aspect).
    assert helpers.attempt_issue_share(viewer, doc_id).status_code == 403, (
        "viewer 는 공유 링크를 발급할 수 없다(INV-2 읽기 전용, 공유는 EDITOR 게이트)"
    )
    # 공유 링크 토글 불가.
    assert (
        helpers.attempt_toggle_share(viewer, doc_id, is_enabled=False).status_code == 403
    ), "viewer 는 공유 링크를 토글할 수 없다(INV-2 읽기 전용)"


def test_inv3_admin_bypasses_membership_for_docs_attachments_sharing(
    share_scenario, harness, tmp_attachment_roots
):
    """INV-3: admin(비멤버)이 WS 문서·첨부·공유를 접근·조작한다 — 어떤 권한 검사로도 차단 안 됨 (6.1).

    (1) admin 이 이 워크스페이스의 멤버가 **아님**을 실제 `workspace_member` DB 질의(role=None)로
    확증하고, (2) 그럼에도 admin 세션이 문서 조회(200)·휴지통 목록(200)·첨부 업로드(201)·공유
    발급(200)·공유 토글(200)을 모두 성공시킴을 확인한다(admin bypass — 멤버십·role 무관).
    """
    admin = share_scenario.admin_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id

    # (1) admin 은 이 WS 의 멤버가 아니다(실제 workspace_member 질의 → None).
    admin_id = _admin_user_id(harness)
    assert _membership_role(harness, ws_id, admin_id) is None, (
        "admin 은 이 워크스페이스의 workspace_member 행이 없어야 한다(비멤버 bypass 관찰의 전제)"
    )

    # (2) 비멤버 admin 이 문서·첨부·공유를 모두 조작·접근한다(bypass).
    assert helpers.l3_helpers.attempt_get_document(admin, doc_id).status_code == 200, (
        "admin 은 비멤버 WS 문서를 조회할 수 있어야 한다(INV-3)"
    )
    assert helpers.l4_helpers.attempt_list_trash(admin, ws_id).status_code == 200, (
        "admin 은 비멤버 WS 휴지통을 조회할 수 있어야 한다(INV-3)"
    )
    att = helpers.l5_helpers.upload_image(admin, doc_id, content=_IMAGE_BYTES)
    assert att["id"] is not None, "admin 은 비멤버 WS 문서에 첨부를 올릴 수 있어야 한다(INV-3)"
    assert helpers.attempt_issue_share(admin, doc_id).status_code == 200, (
        "admin 은 비멤버 WS 문서 공유를 발급할 수 있어야 한다(INV-3, 공유 bypass)"
    )
    assert (
        helpers.attempt_toggle_share(admin, doc_id, is_enabled=False).status_code == 200
    ), "admin 은 비멤버 WS 문서 공유를 토글할 수 있어야 한다(INV-3, 공유 bypass)"


# =============================================================================
# Group 6.2 — 물리 삭제 부재(INV-4): user·document·attachment·share_link
# =============================================================================


def test_inv4_no_physical_delete_user_and_document(share_scenario, harness):
    """INV-4: user(`is_deleted`)·document(`status`) soft-delete 후에도 행이 물리적으로 존속 (6.2).

    (1) admin 이 사용자를 `is_deleted=true` 로 만들어도 `user` 행은 DELETE 되지 않고 남는다,
    (2) 문서를 trashed→deleted(완전삭제)로 종착시켜도 `document` 행은 status 전환으로만 표현되고
    물리 삭제되지 않는다(dangling FK 없음). 라이브 DB 로 행 존속을 확인한다.
    """
    admin = share_scenario.admin_client
    editor = share_scenario.editor_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id
    viewer_user_id = share_scenario.doc_tree.scenario.viewer_user_id

    # (1) user soft-delete — is_deleted=true 전환, 행 존속.
    updated = helpers.l1_helpers.set_deleted(admin, viewer_user_id, True)
    assert updated["is_deleted"] is True, "set_deleted 는 is_deleted=true 여야 한다"
    with harness.session_local() as db:
        user_row = db.get(User, viewer_user_id)
        assert user_row is not None, "삭제된 사용자 행이 물리적으로 존속해야 한다(INV-4)"
        assert user_row.is_deleted is True, "삭제는 is_deleted 플래그로만 표현되어야 한다(INV-4)"

    # (2) document soft-delete — trashed → deleted 종착, 행 존속.
    helpers.l3_helpers.delete_document(editor, doc_id)
    bundle_id = _bundle_id_for_root(editor, ws_id, doc_id)
    helpers.l4_helpers.purge_bundle_via_api(editor, bundle_id)
    with harness.session_local() as db:
        doc_row = db.get(Document, doc_id)
        assert doc_row is not None, "완전삭제된 문서 행이 물리적으로 존속해야 한다(INV-4)"
        assert doc_row.status == "deleted", (
            "완전삭제는 status=deleted 로만 표현되어야 한다(물리 삭제 아님, INV-4)"
        )


def test_inv4_no_physical_delete_attachment_and_share_link(
    share_scenario, harness, archival_sweep, invalidation_sweep, share_link_observation,
    tmp_attachment_roots,
):
    """INV-4: attachment(`is_archived`)·share_link(`is_enabled`+토큰 교체) soft-delete 후 행 존속 (6.2).

    (1) 참조 소멸된 이미지 첨부를 실제 아카이브 스윕으로 보관 이동해도 `attachment` 행은 삭제되지
    않고 `is_archived=true` 로만 표시된다, (2) 무효 문서의 공유 링크를 무효화 스윕으로 retire 해도
    `share_link` 행은 삭제되지 않고 `is_enabled=false` + 토큰 교체로만 표현된다. 라이브 DB 로 행
    존속을 확인한다(retire·archive ≠ DELETE row).
    """
    editor = share_scenario.editor_client
    doc_id = share_scenario.document_id

    # (1-a) 참조 소멸 첨부 구성: 업로드 → v1(참조) → v2(참조 제거) → created_at 핀.
    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]
    helpers.l5_helpers.save_with_reference(editor, doc_id, aid)
    helpers.l5_helpers.save_without_reference(editor, doc_id)
    _pin_attachment_created_at(harness, aid, _EARLY)

    # (1-b) 실제 아카이브 스윕 → 보관 이동(is_archived=true) · 행 존속.
    processed = helpers.l5_helpers.run_archival_sweep(archival_sweep, _NOW)
    assert processed == 1, f"참조 소멸 이미지 1건만 보관 이동되어야 한다: {processed}"
    assert (
        helpers.l5_helpers.attachment_is_archived(harness.session_local, aid) is True
    ), "보관 후 attachment.is_archived 는 true 여야 한다(INV-4)"
    with harness.session_local() as db:
        att_row = db.get(Attachment, aid)
        assert att_row is not None, "보관된 첨부 행이 물리적으로 존속해야 한다(INV-4)"

    # (2) share_link retire: 문서 trashed → (공개 GET 없이) 무효화 스윕 → is_enabled False + 토큰 교체.
    t1 = share_scenario.token
    helpers.l3_helpers.delete_document(editor, doc_id)
    assert helpers.run_invalidation_sweep(invalidation_sweep) >= 1
    assert helpers.share_is_enabled(share_link_observation, doc_id) is False, (
        "retire 후 share_link.is_enabled 는 False 여야 한다(INV-4·INV-8)"
    )
    assert helpers.share_token(share_link_observation, doc_id) != t1, (
        "retire 는 토큰을 교체해야 한다(INV-8)"
    )
    with harness.session_local() as db:
        link_row = (
            db.execute(select(ShareLink).where(ShareLink.document_id == doc_id))
            .scalars()
            .first()
        )
        assert link_row is not None, "retire 된 share_link 행이 물리적으로 존속해야 한다(INV-4)"


# =============================================================================
# Group 6.3 — 이동 사이클 없음(INV-5) · WS 경계(INV-6)
# =============================================================================


def test_inv5_move_creating_cycle_is_rejected(share_scenario):
    """INV-5: 문서를 자신의 후손 밑으로 이동하면 순환으로 거부된다 (6.3).

    공유 트리(root←child←grandchild)에서 root 를 자신의 후손(grandchild) 밑으로 이동하려 하면
    실제 이동 서비스가 순환을 판정해 409 로 거부한다(자기/후손 밑 이동 금지). 실제 라우트로
    거부 상태를 관찰한다(계약: `POST /documents/{id}/move` 순환 → 409).
    """
    editor = share_scenario.editor_client
    resp = helpers.l3_helpers.attempt_move_document(
        editor, share_scenario.root_id, new_parent_id=share_scenario.grandchild_id
    )
    assert resp.status_code == 409, (
        f"root 를 자신의 후손 밑으로 이동하면 순환으로 409 거부되어야 한다(INV-5): "
        f"{resp.status_code} {resp.text}"
    )


def test_inv6_cross_workspace_move_is_rejected(share_scenario):
    """INV-6: 문서 이동이 워크스페이스 경계를 넘지 않는다 — 타 WS 부모로 이동 거부 (6.3).

    owner 가 **다른 워크스페이스**와 그 안의 문서를 만든 뒤, 공유 문서(root)를 그 타 WS 문서를
    부모로 이동하려 하면 실제 이동 서비스가 동일 WS 계약을 강제해 409 로 거부한다(WS 경계 유지,
    INV-6). 실제 라우트로 거부를 관찰한다.
    """
    owner = share_scenario.owner_client
    editor = share_scenario.editor_client

    other_ws_id = helpers.l2_helpers.create_workspace(owner, "INV6-다른워크스페이스")
    other_doc = helpers.l3_helpers.create_document(owner, other_ws_id, "INV6-타WS-문서")

    resp = helpers.l3_helpers.attempt_move_document(
        editor, share_scenario.root_id, new_parent_id=other_doc["id"]
    )
    assert resp.status_code == 409, (
        f"타 WS 문서를 부모로 이동하면 WS 경계로 409 거부되어야 한다(INV-6): "
        f"{resp.status_code} {resp.text}"
    )


def test_inv6_link_via_file_does_not_cross_workspace(
    share_scenario, tmp_attachment_roots
):
    """INV-6: 링크 경유 첨부 접근이 WS 경계를 넘지 않는다 — 다른 WS 첨부는 404 (6.3, 공유 seam).

    owner 가 다른 워크스페이스·문서·이미지를 만든 뒤, 원래 WS 문서에 대한 공유 링크로 그 다른 WS
    첨부를 `GET /public/{token}/attachments/{aid}` 로 요청하면 WS 격리로 404(비노출)된다. 링크
    스코프가 발급 문서의 WS 를 넘지 않음을 확인한다(2.4 와 중복이나 조립 시스템 회귀로 재확인).
    """
    owner = share_scenario.owner_client
    public = share_scenario.public_client
    token = share_scenario.token

    other_ws_id = helpers.l2_helpers.create_workspace(owner, "INV6-링크격리-WS")
    other_doc = helpers.l3_helpers.create_document(owner, other_ws_id, "INV6-링크격리-문서")
    other_att = helpers.l5_helpers.upload_image(owner, other_doc["id"], content=_IMAGE_BYTES)

    resp = helpers.attempt_public_attachment(public, token, other_att["id"])
    assert resp.status_code == 404, (
        f"다른 WS 첨부는 링크 경유로 404(WS 격리)여야 한다(INV-6): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 6.4 — 복원 없음(INV-7) · 무효화 재발급(INV-8) · 잠금 단일성(INV-9)
# =============================================================================


def test_inv7_deleted_bundle_and_archived_attachment_have_no_restore_path(
    share_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """INV-7: deleted 문서·보관 첨부에 복원 경로가 없다 (6.4).

    (1) 첨부를 실제 아카이브 스윕으로 보관(is_archived=true)시키면 보관 첨부는 다시 서빙되지
    않는다(un-archive 경로 부재 — `GET /attachments/{aid}` 404, role·경로 무관 INV-7),
    (2) 문서를 완전삭제(deleted 종착)한 뒤 그 묶음을 복구하려 하면 복구가 불가하다(휴지통에 더
    이상 유효 묶음이 없으므로 `POST /trash/{bundleId}/restore` 404). deleted·보관은 종착 상태다.

    주의: 보관 대상 첨부는 스윕 이전에 **서빙하지 않는다**. 서빙(`FileResponse`)이 남기는 파일
    핸들이 아직 열려 있으면 Windows 에서 후속 `move_to_archive`(파일 이동)가 sharing 위반으로
    실패할 수 있어(예외 격리 → 보관 0건) 비결정적이 된다. 보관이 실제로 동작함은 INV-4 첨부
    테스트가 이미 관찰하며, 이 테스트의 teeth 는 보관 **이후** 재서빙 404(un-archive 부재)다.
    """
    editor = share_scenario.editor_client
    viewer = share_scenario.viewer_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id

    # (1) 참조 소멸 첨부를 실제 아카이브 스윕으로 보관(스윕 이전 서빙 없음 — 핸들 오픈 회피).
    att = helpers.l5_helpers.upload_image(editor, doc_id, content=_IMAGE_BYTES)
    aid = att["id"]
    helpers.l5_helpers.save_with_reference(editor, doc_id, aid)
    helpers.l5_helpers.save_without_reference(editor, doc_id)
    _pin_attachment_created_at(harness, aid, _EARLY)
    assert helpers.l5_helpers.run_archival_sweep(archival_sweep, _NOW) == 1, (
        "참조 소멸 이미지 1건이 보관 이동되어야 한다(보관 전제 구성)"
    )
    assert (
        helpers.l5_helpers.attachment_is_archived(harness.session_local, aid) is True
    ), "보관 후 attachment.is_archived 는 true 여야 한다(INV-7 전제)"

    # 보관 첨부는 재서빙 경로가 없다 — role 무관 404(un-archive 부재, INV-7).
    assert helpers.l5_helpers.attempt_get_attachment(editor, aid).status_code == 404, (
        "보관된 첨부는 editor 에게도 재서빙되지 않아야 한다(INV-7 복원 경로 부재)"
    )
    assert helpers.l5_helpers.attempt_get_attachment(viewer, aid).status_code == 404, (
        "보관된 첨부는 viewer 에게도 재서빙되지 않아야 한다(INV-7)"
    )

    # (2) deleted 문서(묶음)는 복구 경로가 없다.
    helpers.l3_helpers.delete_document(editor, doc_id)
    bundle_id = _bundle_id_for_root(editor, ws_id, doc_id)
    helpers.l4_helpers.purge_bundle_via_api(editor, bundle_id)  # deleted 종착
    assert _document_status(harness, doc_id) == "deleted"
    # 완전삭제된 묶음의 복구 시도 → 유효 묶음 부재로 404(복원 경로 없음, INV-7).
    resp = helpers.l4_helpers.attempt_restore_bundle(editor, bundle_id)
    assert resp.status_code == 404, (
        f"deleted 종착 묶음은 복구할 수 없어야 한다(INV-7 복원 경로 부재): "
        f"{resp.status_code} {resp.text}"
    )


def test_inv8_invalidated_link_needs_reissue_to_be_accessible(share_scenario):
    """INV-8: 무효화된 공유 링크는 재발급 없이 접근 불가 (6.4).

    (1) 문서 trashed 로 링크 실시간 무효화 → 이전 토큰 공개 렌더 404, (2) 복구 후에도 이전 토큰
    여전히 404(자동 복원 없음), (3) 재발급이 이전 토큰과 **다른** 새 토큰을 발급해야만 그 새
    토큰으로 200 이 되고 이전 토큰은 계속 404 임을 확인한다(재발급 통일 원칙, 2.3 의 compact 회귀).
    """
    editor = share_scenario.editor_client
    public = share_scenario.public_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id
    t1 = share_scenario.token

    # (0) 무효화 전 유효 토큰 200(대조).
    assert helpers.attempt_public_render(public, t1).status_code == 200

    # (1) 문서 trashed → 실시간 무효화 → 이전 토큰 404.
    helpers.l3_helpers.delete_document(editor, doc_id)
    assert helpers.attempt_public_render(public, t1).status_code == 404, (
        "trashed 후 이전 토큰 공개 렌더는 404(무효화)여야 한다(INV-8)"
    )

    # (2) 복구 후에도 이전 토큰 여전히 404(자동 복원 없음).
    bundle_id = _bundle_id_for_root(editor, ws_id, doc_id)
    helpers.l4_helpers.restore_bundle_via_api(editor, bundle_id)
    assert helpers.attempt_public_render(public, t1).status_code == 404, (
        "복구 후에도 이전 토큰은 재발급 없이 되살아나면 안 된다(INV-8)"
    )

    # (3) 재발급(새 토큰)만이 다시 공유를 가능케 한다.
    reissued = helpers.issue_share(editor, doc_id)
    t2 = reissued["token"]
    assert t2 != t1, f"재발급 토큰은 이전 토큰과 달라야 한다(INV-8): t1={t1!r} t2={t2!r}"
    assert helpers.attempt_public_render(public, t2).status_code == 200, (
        "재발급 새 토큰만이 200 이어야 한다(INV-8)"
    )
    assert helpers.attempt_public_render(public, t1).status_code == 404, (
        "재발급 이후에도 이전 토큰은 계속 404 여야 한다(INV-8)"
    )


def test_inv9_at_most_one_edit_lock_per_document(lock_scenario, harness):
    """INV-9: 문서당 편집 잠금은 최대 1인 — `document.lock_user_id` 단일 컬럼 (6.4).

    같은 워크스페이스의 두 editor(A·B)로: (1) editor A 가 문서를 잠그면, (2) editor B 의 잠금
    시도는 409(이미 편집 중)로 거부되고, (3) DB `lock_user_id` 는 editor A 의 사용자 id 단일
    값으로 유지된다(두 홀더 불가능 — 단일 컬럼). 실제 s09 잠금 라우트로 관찰한다.
    """
    editor_a = lock_scenario.editor_a_client
    editor_b = lock_scenario.editor_b_client
    ws_id = lock_scenario.workspace_id

    doc = helpers.l3_helpers.create_document(editor_a, ws_id, "INV9-잠금대상")
    doc_id = doc["id"]

    # (1) editor A 잠금.
    helpers.l4_helpers.lock(editor_a, doc_id)

    # (2) editor B 잠금 시도 → 409(이미 잠김).
    resp = helpers.l4_helpers.attempt_lock(editor_b, doc_id)
    assert resp.status_code == 409, (
        f"editor A 가 잠근 문서에 editor B 의 잠금은 409(이미 편집 중)여야 한다(INV-9): "
        f"{resp.status_code} {resp.text}"
    )

    # (3) DB lock_user_id 는 단일 홀더(editor A)뿐.
    assert _document_lock_user_id(harness, doc_id) == lock_scenario.editor_a_user_id, (
        "잠금 단일성: lock_user_id 는 editor A 의 사용자 id 여야 한다(단일 컬럼, INV-9)"
    )


# =============================================================================
# Group 6.5 — 묶음 원자·비병합(INV-10) · 자식 먼저 trash(INV-11) · 보관 만료 독립(INV-12)
# =============================================================================


def test_inv10_bundles_are_atomic_and_non_merging(trash_scenario, engine_access):
    """INV-10: 삭제 묶음은 원자적이고 서로 다른 시점의 묶음이 병합되지 않는다 (6.5).

    `trash_scenario` 는 손자를 단독 삭제(손자 묶음)한 뒤 루트를 삭제(루트+자식 묶음)해 서로 다른
    `trashed_at` 의 **두 독립 묶음**을 만든다. 실제 엔진 `identify_bundles` 로 열거하면 손자 묶음이
    루트 묶음에 **흡수되지 않고**(비병합) 정확히 두 묶음(구성원 {손자}, {루트,자식})으로 유지됨을
    확인한다(묶음 원자·비병합).
    """
    bundles = helpers.l3_helpers.identify_bundles(
        engine_access, trash_scenario.workspace_id
    )
    member_sets = sorted((sorted(b.member_ids) for b in bundles), key=len)

    assert len(bundles) == 2, (
        f"서로 다른 시점의 두 독립 묶음이 병합되지 않고 2개로 유지되어야 한다(INV-10): "
        f"{[sorted(b.member_ids) for b in bundles]!r}"
    )
    assert member_sets == [
        [trash_scenario.grandchild_id],
        sorted([trash_scenario.root_id, trash_scenario.child_id]),
    ], (
        f"묶음 구성원은 {{손자}} 와 {{루트,자식}} 으로 원자적이어야 한다(비흡수·비병합, INV-10): "
        f"{member_sets!r}"
    )


def test_inv11_independent_child_trashed_before_parent(trash_scenario, harness):
    """INV-11: 독립 묶음의 자식은 부모보다 먼저 trash 된다 — child.trashed_at ≤ parent.trashed_at (6.5).

    `trash_scenario` 에서 손자는 부모 체인(손자→자식→루트)보다 먼저 단독 삭제되어 더 이른
    `trashed_at`(기준시각 40일 전)을 갖고, 루트+자식은 더 늦은 `trashed_at`(5일 전)을 갖는다.
    라이브 DB 로 `grandchild.trashed_at ≤ child.trashed_at` 을 확인한다(자식이 부모보다 먼저 trash).
    """
    gc_trashed = _document_trashed_at(harness, trash_scenario.grandchild_id)
    child_trashed = _document_trashed_at(harness, trash_scenario.child_id)

    assert gc_trashed is not None and child_trashed is not None, (
        "trashed 문서는 trashed_at 이 설정되어 있어야 한다"
    )
    assert gc_trashed <= child_trashed, (
        f"먼저 삭제된 손자의 trashed_at 이 부모(자식)의 trashed_at 보다 이르거나 같아야 한다"
        f"(INV-11): grandchild={gc_trashed!r} child={child_trashed!r}"
    )


def test_inv12_bundle_retention_expiry_is_independent_per_trashed_at(
    trash_scenario, sweep_access
):
    """INV-12: 묶음 보관 만료는 각 `trashed_at` 기준으로 독립 산정된다 (6.5).

    `trash_scenario`: retention=30일, 손자 묶음 trashed_at=기준시각 40일 전(만료), 루트+자식 묶음
    trashed_at=5일 전(미만료). 기준시각을 `now` 로 주입해 실제 s10 보관 만료 스윕을 구동하면 손자
    묶음만 deleted 로 종착되고 루트+자식 묶음은 여전히 trashed 로 남는다(각 묶음 타이머 독립).
    """
    # 만료 경계 확정: 스윕 이전 두 묶음 모두 trashed.
    assert trash_scenario.status_of(trash_scenario.grandchild_id) == "trashed"
    assert trash_scenario.status_of(trash_scenario.root_id) == "trashed"

    # 기준시각 now 로 실제 보관 만료 스윕 구동(손자 묶음만 만료).
    purged = sweep_access.sweep(trash_scenario.reference)
    assert purged >= 1, f"만료된 손자 묶음이 최소 1건 전이되어야 한다: {purged}"

    # 손자 묶음만 deleted, 루트+자식 묶음은 독립적으로 미만료(trashed 유지).
    assert trash_scenario.status_of(trash_scenario.grandchild_id) == "deleted", (
        "40일 전 손자 묶음은 retention(30일) 초과로 deleted 로 만료되어야 한다(INV-12)"
    )
    assert trash_scenario.status_of(trash_scenario.root_id) == "trashed", (
        "5일 전 루트 묶음은 아직 미만료로 trashed 를 유지해야 한다(각 trashed_at 독립 산정, INV-12)"
    )
    assert trash_scenario.status_of(trash_scenario.child_id) == "trashed", (
        "루트 묶음 구성원 자식도 미만료로 trashed 를 유지해야 한다(INV-12)"
    )
