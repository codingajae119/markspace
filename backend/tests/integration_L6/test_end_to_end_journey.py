"""대표 전 계층 관통 e2e 여정 스위트 (Task 2.6 / Req 7.1, 7.2, 7.3, 7.4, 7.5,
design §EndToEndJourneySuite · §System Flows(대표 전 계층 관통 e2e 여정)).

실제 결합된 런타임(마이그레이션 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12⊕**s14**) +
실제 서명 쿠키 세션 + 실제 workspace_member 데이터 + 저장/보관 루트만 tmp 로 격리
(`tmp_attachment_roots`) + 부팅 앱과 동일 세션 팩토리로 조립한 실제 s14 `ShareInvalidationSweep`·
실제 s12 `ArchivalSweepService`)에서 **하나의 사용자 여정**이 auth → admin → workspace →
document → lock/version → trash → attachment → sharing 전체를 관통해 성립함을 mock 없이 e2e 로
관찰한다. 개별 경계 검증(2.1~2.5)을 넘어 전체 시스템이 **하나의 실제 사용자 흐름**으로 결합해
동작함을 최종 확인한다. 대조 기준은 개별 spec design 이 아니라 s01 단일 소스(카탈로그 행 34~37·
공개 경로 404 통일·불변식 INV-4·INV-8)다.

## 하나의 여정 = 하나의 테스트 (state chaining)
L6 하네스는 function-scope 로 매 테스트마다 DB 를 drop+migrate 하므로, 여정의 각 단계는
**별도 테스트로 쪼개면 이전 상태가 유실된다**. 따라서 이 스위트는 여정 전체를 **단일 테스트**
(:func:`test_end_to_end_journey`)로 엮어 각 단계가 **직전 단계의 실제 출력**(생성된 uid·ws_id·
문서 id·발급 토큰·첨부 id·묶음 id)을 소비하며 진행한다. 각 단계에 여정 단계 라벨을 붙인 단언
메시지를 달아, 실패 시 **어느 계층 결합이 흐름에서 깨졌는지** 즉시 지목한다.

여정 단계(Req 7.1~7.5):

- **7.1 계정·워크스페이스·문서**: admin 이 사용자 생성(s03) → 사용자 로그인(s02) → owner 로
  워크스페이스 생성(s05, owner 자동 등록) → 문서 트리(root + 하위)를 구성(s07). owner 멤버십은
  실 workspace_member DB 관측으로, 문서는 실 id·parent 연결로 확인한다.
- **7.2 잠금·저장·이미지·공유·외부 열람**: 편집 잠금 획득·해제(s09) → 이미지 붙여넣기(s12) →
  본문 참조 저장으로 새 버전 생성(s09) → 게이트 on(s05) → 공유 링크 발급(s14) → 익명 접근자가
  `GET /public/{token}` 문서 트리·`GET /public/{token}/attachments/{aid}` 첨부 바이너리를 열람
  (8.4), 공개 렌더 HTML 이 링크 스코프 경로로 재작성됨을 확인.
- **7.3 하위 삭제·묶음·트리 제외·링크 무효**: 하위에도 공유 링크를 발급해 둔 뒤 하위를 trash(s10)
  → 묶음 포착 → root 공개 트리에서 하위 제외(active_descendants) → 하위의 공유 링크는 실시간
  게이트로 404 무효화.
- **7.4 복구·재발급(INV-8)**: 하위 묶음 복구(s10, 위치 규칙) → root 트리에 하위 재포함 → 하위
  링크 재발급 시 이전 토큰과 **다른 새 토큰**만 유효(이전 토큰 계속 404).
- **7.5 완전삭제·보관 이동·물리삭제 부재(INV-4)**: root 완전삭제(`DELETE /trash/{bundleId}` →
  deleted) → 무효화 스윕으로 root 링크 retire → 아카이브 스윕으로 root 첨부 보관 이동
  (`is_archived=true`) → user·document·attachment·share_link 행이 물리적으로 존속(플래그/상태
  전환일 뿐 DELETE row 아님)하고 보관 파일이 보관 루트에 존재함을 파일시스템·DB 로 확인.

전 단계는 실제 라우트·엔진·스윕 결합이며(L5/L4/L3/L2/L1 헬퍼 재사용) mock 이 없다. deleted 유발은
항상 실제 완전삭제 경로로만 하고(임의 DB status 조작 금지), 토큰 교체는 DB(`share_token`)로
확인한다. 실 동작이 계약과 다르면(어느 계층이 흐름에서 조립되지 않으면) 단언을 약화시키지 않고
그대로 실패시킨다 — 그것은 원인 spec 에서 고쳐야 할 실제 결합 회귀다.

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
`s12`·`s14` 중 하나라도 수정되면 이 최종 체크포인트를 누적 집합 기준으로 재실행한다(`s01` 수정
시 모든 체크포인트).
"""

from datetime import datetime

from app.models import Attachment, Document, ShareLink, User, WorkspaceMember
from tests.integration_L6 import helpers

# 붙여넣기 이미지 바이너리(작은 PNG 시그니처 + 여정 전용 페이로드; 링크 경유 바이트 대조용).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l6-journey-image-payload"

# 아카이브 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 8.6 완전삭제 반응은 now 에 직접
# 의존하지 않으나 배치 계약 일관성상 API 가 받는다.
_NOW = datetime(2026, 7, 17, 12, 0, 0)

# 여정 오너의 알려진 평문 비밀번호(min_length 8 정책 충족, 테스트 전용 자격).
_OWNER_PASSWORD = "journey-owner-pw-123"


# =============================================================================
# DB 관측 헬퍼 — 부팅 앱과 동일 세션 팩토리(harness.session_local)로 커밋된 행 관찰
# =============================================================================


def _member_role(harness, workspace_id: int, user_id: int) -> str | None:
    """실 workspace_member 행에서 (ws, user) 의 role 을 관측한다(미존재 None, s05 결과)."""
    with harness.session_local() as db:
        row = (
            db.query(WorkspaceMember)
            .filter_by(workspace_id=workspace_id, user_id=user_id)
            .one_or_none()
        )
        return None if row is None else row.role


def _doc_status(harness, document_id: int) -> str | None:
    """문서 status(active/trashed/deleted)를 관측한다(미존재 None, s07/s10 결과)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.status


def _doc_lock_user(harness, document_id: int) -> int | None:
    """문서의 현재 lock_user_id 를 관측한다(미잠금 None, s09 결과, INV-9 잠금 단일성 관찰)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.lock_user_id


def _row_exists(harness, model, primary_key: int) -> bool:
    """모델 행이 물리적으로 존재하는지 관측한다(INV-4 물리 삭제 부재 확인용)."""
    with harness.session_local() as db:
        return db.get(model, primary_key) is not None


def _bundle_id_for_root(client, workspace_id: int, root_document_id: int) -> int:
    """휴지통 목록에서 루트 문서 id 로 묶음을 찾아 `bundle_id` 를 반환한다(묶음 포착).

    `GET /workspaces/{id}/trash`(L4) → `Page[TrashBundleRead]` 를 태워 루트가
    `root_document_id` 인 묶음의 `bundle_id` 를 돌려준다(미발견 시 AssertionError).
    """
    page = helpers.l4_helpers.list_trash(client, workspace_id)
    for item in page["items"]:
        if item["root_document_id"] == root_document_id:
            return item["bundle_id"]
    raise AssertionError(
        f"[7.x] 루트 문서 {root_document_id} 의 휴지통 묶음을 찾지 못했다: "
        f"items={page['items']!r}"
    )


# =============================================================================
# 대표 전 계층 관통 e2e 여정 — 단일 테스트로 전 단계 state chaining
# =============================================================================


def test_end_to_end_journey(
    harness,
    tmp_attachment_roots,
    invalidation_sweep,
    share_link_observation,
    archival_sweep,
):
    """auth → admin → workspace → document → lock/version → trash → attachment → sharing 를
    관통하는 하나의 사용자 여정이 실제 전체 결합에서 성립함을 검증한다(Req 7.1~7.5).

    각 단계는 직전 단계의 실제 출력을 소비하며, 각 단언은 여정 단계 라벨을 달아 실패 시 어느
    계층 결합이 흐름에서 깨졌는지 지목한다. mock·임의 DB 상태 조작 없음.
    """
    # -------------------------------------------------------------------------
    # Step 7.1 — 계정(s03)·로그인(s02)·워크스페이스(s05)·문서 트리(s07)
    # -------------------------------------------------------------------------
    admin = harness.login_admin()

    login_id = helpers.l1_helpers.unique_login_id("journey")
    uid = helpers.l1_helpers.create_user(
        admin, login_id, _OWNER_PASSWORD, name="여정-오너"
    )
    assert isinstance(uid, int), f"[7.1 s03] admin 사용자 생성이 실 id 를 내야 한다: {uid!r}"

    # 사용자 로그인 — 세션 쿠키가 실린 인증 클라이언트(s02 실제 로그인 흐름).
    owner = harness.login(login_id, _OWNER_PASSWORD)

    # owner 로 워크스페이스 생성(요청자 owner 자동 등록, s05).
    ws_id = helpers.l2_helpers.create_workspace(owner, "여정-WS")
    assert isinstance(ws_id, int), f"[7.1 s05] 워크스페이스 생성이 실 id 를 내야 한다: {ws_id!r}"
    assert _member_role(harness, ws_id, uid) == "owner", (
        "[7.1 s05] 워크스페이스 생성자는 실 workspace_member 에서 owner role 이어야 한다"
    )

    # 문서 트리(root + 하위) 구성(s07).
    root = helpers.l3_helpers.create_document(owner, ws_id, "루트", parent_id=None)
    root_id = root["id"]
    child = helpers.l3_helpers.create_document(owner, ws_id, "하위", parent_id=root_id)
    child_id = child["id"]
    assert isinstance(root_id, int) and isinstance(child_id, int), (
        f"[7.1 s07] 문서 생성이 실 id 를 내야 한다: root={root_id!r} child={child_id!r}"
    )
    assert child["parent_id"] == root_id, (
        f"[7.1 s07] 하위 문서는 root 아래에 연결되어야 한다: child.parent_id={child['parent_id']!r}"
    )
    assert _doc_status(harness, root_id) == "active", "[7.1 s07] root 는 active 여야 한다"
    assert _doc_status(harness, child_id) == "active", "[7.1 s07] child 는 active 여야 한다"

    # -------------------------------------------------------------------------
    # Step 7.2 — 잠금(s09)·이미지(s12)·저장 버전(s09)·게이트(s05)·공유(s14)·외부 열람(8.4)
    # -------------------------------------------------------------------------
    # 편집 잠금 획득 → owner 가 잠금 보유(s09, INV-9) → 해제(cancel)로 다음 저장이 재잠금 가능.
    helpers.l4_helpers.lock(owner, root_id)
    assert _doc_lock_user(harness, root_id) == uid, (
        "[7.2 s09] 편집 잠금 후 root 의 lock_user_id 는 owner uid 여야 한다(INV-9)"
    )
    helpers.l4_helpers.cancel(owner, root_id)
    assert _doc_lock_user(harness, root_id) is None, (
        "[7.2 s09] 편집 취소 후 잠금이 해제되어야 한다(lock_user_id None)"
    )

    # 이미지 붙여넣기(s12) — root 문서에 첨부 업로드.
    att = helpers.l5_helpers.upload_image(owner, root_id, content=_IMAGE_BYTES)
    att_id = att["id"]
    assert helpers.l5_helpers.attachment_is_archived(harness.session_local, att_id) is False, (
        "[7.2 s12] 업로드 직후 첨부는 미보관이어야 한다"
    )

    # 본문 참조 저장(s09 새 버전) — save_with_reference 가 잠금→저장을 소유(재잠금 충돌 회피).
    version = helpers.l5_helpers.save_with_reference(owner, root_id, att_id)
    assert isinstance(version.get("id"), int), (
        f"[7.2 s09] 참조 저장은 새 버전(id)을 생성해야 한다: {version!r}"
    )
    versions = helpers.l4_helpers.list_versions(owner, root_id)
    assert versions["total"] >= 1, (
        f"[7.2 s09] 저장 후 버전 목록에 최소 1개 버전이 있어야 한다: {versions['total']}"
    )

    # 게이트 on(s05) → editor 이상(owner) 공유 링크 발급(s14, 계약상 200 ShareLinkRead).
    helpers.set_gate(owner, ws_id, is_shareable=True)
    link = helpers.issue_share(owner, root_id)
    root_token = link["token"]
    assert link["is_enabled"] is True, f"[7.2 s14] 발급 링크는 활성이어야 한다: {link!r}"
    assert helpers.share_token(share_link_observation, root_id) == root_token, (
        "[7.2 s14] DB 관측 토큰이 발급 응답 토큰과 일치해야 한다"
    )

    # 익명 외부 열람(8.4) — 인증 세션과 독립된 비인증 공개 클라이언트.
    public = harness.new_client()
    tree = helpers.public_render(public, root_token)
    ids = helpers.collect_node_ids(tree)
    assert root_id in ids, "[7.2 s14] 공개 렌더 트리는 공유 root 문서를 포함해야 한다"
    assert child_id in ids, (
        "[7.2 s14] 공개 렌더 트리는 현재 active 하위(child)도 동적으로 포함해야 한다"
    )
    root_node = helpers.find_node(tree, root_id)
    assert root_node is not None, "[7.2 s14] 공개 트리에서 root 노드를 찾을 수 있어야 한다"
    assert f"/public/{root_token}/attachments/{att_id}" in root_node["content_html"], (
        "[7.2 8.4] 공개 렌더 HTML 의 첨부 참조가 링크 스코프 경로로 재작성되어야 한다"
    )

    # 링크 경유 첨부 바이너리(8.4) — 익명 접근으로 업로드 바이트와 정확히 일치.
    att_resp = helpers.public_attachment(public, root_token, att_id)
    assert att_resp.content == _IMAGE_BYTES, (
        "[7.2 8.4] 링크 경유 첨부 응답 바이트는 업로드 바이트와 정확히 일치해야 한다"
    )

    # -------------------------------------------------------------------------
    # Step 7.3 — 하위 공유 발급 → 하위 trash(s10) → 묶음 포착·트리 제외·하위 링크 무효
    # -------------------------------------------------------------------------
    # 하위(active·게이트 on)에도 공유 링크를 발급해 둔다(무효화 대상 확보).
    child_link = helpers.issue_share(owner, child_id)
    child_token = child_link["token"]

    # 하위를 trash(s10 실제 라우트).
    helpers.l3_helpers.delete_document(owner, child_id)
    assert _doc_status(harness, child_id) == "trashed", (
        "[7.3 s10] 삭제된 하위 문서 status 는 trashed 여야 한다"
    )

    # 묶음 포착 — 휴지통 목록에 하위를 루트로 하는 묶음이 나타난다(s10).
    child_bundle_id = _bundle_id_for_root(owner, ws_id, child_id)

    # root 공개 트리에서 하위 제외(active_descendants — trashed 하위 배제).
    tree_after_trash = helpers.public_render(public, root_token)
    ids_after_trash = helpers.collect_node_ids(tree_after_trash)
    assert root_id in ids_after_trash, "[7.3 s14] trash 후에도 root 는 공개 트리에 남아야 한다"
    assert child_id not in ids_after_trash, (
        "[7.3 s14] trashed 하위는 root 공개 트리에서 동적으로 제외되어야 한다(active_descendants)"
    )

    # 하위 대상 공유 링크는 실시간 게이트로 즉시 404 무효화(스윕 불필요).
    assert helpers.attempt_public_render(public, child_token).status_code == 404, (
        "[7.3 s14/INV-8] 하위 trashed 후 하위 토큰 공개 렌더는 즉시 404 여야 한다(실시간 게이트)"
    )

    # -------------------------------------------------------------------------
    # Step 7.4 — 하위 복구(s10 위치 규칙)·재발급(INV-8 새 토큰만 유효)
    # -------------------------------------------------------------------------
    helpers.l4_helpers.restore_bundle_via_api(owner, child_bundle_id)
    assert _doc_status(harness, child_id) == "active", (
        "[7.4 s10] 복구 후 하위 문서 status 는 active 여야 한다(위치 규칙)"
    )

    # root 공개 트리에 하위 재포함(복구가 위치 규칙대로 성립).
    tree_after_restore = helpers.public_render(public, root_token)
    assert child_id in helpers.collect_node_ids(tree_after_restore), (
        "[7.4 s14] 복구된 하위는 root 공개 트리에 다시 포함되어야 한다"
    )

    # 재발급 — 이전 토큰과 다른 새 토큰(응답·DB 양쪽 확인).
    new_child_link = helpers.issue_share(owner, child_id)
    new_child_token = new_child_link["token"]
    assert new_child_token != child_token, (
        f"[7.4 INV-8] 재발급 토큰은 이전 토큰과 달라야 한다: "
        f"old={child_token!r} new={new_child_token!r}"
    )
    assert helpers.share_token(share_link_observation, child_id) == new_child_token, (
        "[7.4 INV-8] 재발급 후 DB 토큰은 새 토큰이어야 한다(실제 재발급 관찰, 임의 조작 아님)"
    )
    # 이전 토큰은 계속 404, 새 토큰만 200(재발급이 이전 토큰을 되살리지 않음).
    assert helpers.attempt_public_render(public, child_token).status_code == 404, (
        "[7.4 INV-8] 재발급 이후에도 이전 하위 토큰 공개 렌더는 계속 404 여야 한다"
    )
    assert helpers.attempt_public_render(public, new_child_token).status_code == 200, (
        "[7.4 INV-8] 재발급 새 하위 토큰 공개 렌더는 200 이어야 한다"
    )

    # -------------------------------------------------------------------------
    # Step 7.5 — 완전삭제(deleted)·무효화 스윕 retire·아카이브 스윕 보관 이동·물리삭제 부재(INV-4)
    # -------------------------------------------------------------------------
    # root 를 trash → 묶음 포착 → 완전삭제(deleted 종착, 실제 s10 purge — 지름길 아님).
    assert helpers.share_is_enabled(share_link_observation, root_id) is True, (
        "[7.5 사전] 완전삭제 이전 root 링크는 아직 활성이어야 한다(대조 기준)"
    )
    helpers.l3_helpers.delete_document(owner, root_id)
    root_bundle_id = _bundle_id_for_root(owner, ws_id, root_id)
    helpers.l4_helpers.purge_bundle_via_api(owner, root_bundle_id)
    assert _doc_status(harness, root_id) == "deleted", (
        "[7.5 s10] 완전삭제 후 root 문서 status 는 deleted 여야 한다"
    )

    # 무효화 스윕(s14) — deleted 관측으로 root 링크 retire(비활성 + 토큰 교체).
    retired = helpers.run_invalidation_sweep(invalidation_sweep)
    assert retired >= 1, (
        f"[7.5 s14/INV-8] 무효화 스윕은 deleted root 의 활성 링크를 retire 해야 한다(≥1): {retired}"
    )
    assert helpers.share_is_enabled(share_link_observation, root_id) is False, (
        "[7.5 INV-8] retire 후 root 링크 is_enabled 는 False 여야 한다"
    )
    assert helpers.token_resolves(share_link_observation, root_token) is False, (
        "[7.5 INV-8] retire 후 이전 root 토큰은 어떤 share_link 행으로도 해석되면 안 된다"
    )

    # 아카이브 스윕(s12) — deleted root 의 첨부가 보관 폴더로 이동(8.6 완전삭제 반응).
    processed = helpers.l5_helpers.run_archival_sweep(archival_sweep, _NOW)
    assert processed >= 1, (
        f"[7.5 s12] 아카이브 스윕은 deleted root 의 미보관 첨부를 보관 이동해야 한다(≥1): {processed}"
    )
    assert helpers.l5_helpers.attachment_is_archived(harness.session_local, att_id) is True, (
        "[7.5 s12] 완전삭제 반응으로 root 첨부는 보관됨(is_archived=true)"
    )

    # (INV-4) 물리 삭제 부재 — 전 계층 행이 플래그/상태 전환으로만 표현되고 DELETE row 가 없음.
    assert _doc_status(harness, root_id) == "deleted", (
        "[7.5 INV-4] root document 행은 물리 삭제 아니라 status=deleted 로 존속해야 한다"
    )
    assert helpers.l5_helpers.attachment_is_archived(harness.session_local, att_id) is True, (
        "[7.5 INV-4] attachment 행은 물리 삭제 아니라 is_archived=true 로 존속해야 한다"
    )
    assert helpers.share_row_exists(share_link_observation, root_id) is True, (
        "[7.5 INV-4] share_link 행은 retire(비활성+토큰 교체) 후에도 물리적으로 존속해야 한다"
    )
    assert helpers.share_is_enabled(share_link_observation, root_id) is False, (
        "[7.5 INV-4] share_link 행은 DELETE 아니라 is_enabled=false 플래그로만 무효화되어야 한다"
    )
    assert _row_exists(harness, User, uid) is True, (
        "[7.5 INV-4] user 행은 여정 종료 후에도 물리적으로 존속해야 한다"
    )

    # (INV-4 파일시스템) 보관 파일이 보관 루트의 WS 격리 위치에 원본 바이트로 존재(삭제 아님, 이동).
    archived_rel_path = helpers.l5_helpers.attachment_file_path(harness.session_local, att_id)
    assert archived_rel_path is not None, "[7.5 INV-4] 보관 첨부의 file_path 가 커밋되어 있어야 한다"
    helpers.l5_helpers.assert_ws_isolated(archived_rel_path, ws_id)
    archived_file = helpers.l5_helpers.assert_archived(tmp_attachment_roots, archived_rel_path)
    assert archived_file.read_bytes() == _IMAGE_BYTES, (
        "[7.5 INV-4] 보관된 파일 내용은 원본 업로드 바이트와 동일해야 한다(이동일 뿐 삭제·훼손 아님)"
    )
