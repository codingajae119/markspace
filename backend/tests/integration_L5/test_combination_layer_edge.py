"""아래 계층 결합 엣지 스위트 — role별 접근 경계·admin override·WS 격리·삭제 사용자·물리삭제 부재
(Task 2.6 / Req 7.1·7.2·7.3·7.4, design §CombinationLayerEdgeSuite; INV-1·2·3·4·6 교차참조).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕**s12** 첨부 라우터·아카이브
스케줄러 조립, `app.main.create_app`) + **실제 세션 쿠키** 위에서, s12 첨부 도메인이 **아래
계층 결합**(s02 세션 인증 ↔ s03 계정 생명주기 ↔ s05 워크스페이스 멤버십)과 맞물리는 네 경계를
mock 없이 검증한다. 판정은 s05 가 채운 실제 `workspace_member` 데이터 위에서 s01
`require_ws_role` resolver(첨부 업로드=문서→WS 어댑터·서빙=첨부→WS 어댑터)가 수행하고, 계정
상태(삭제)는 s03 `PATCH /admin/users/{id}` 로 전이하며, 세션 게이트는 s01
`get_current_user`(요청마다 `is_deleted` 재검사)가 강제한다 — 어떤 것도 시뮬레이션하지 않는다.

## 네 시나리오 (Req 매핑)
1. **role 경계·admin override**(7.1, INV-1·2·3): owner/editor/viewer/비멤버/admin 세션으로 첨부
   업로드·서빙 접근 경계를 관찰 — viewer 업로드 거부(403, INV-2), 비멤버 차단(403, INV-1),
   admin(비멤버) 업로드·서빙 성공(INV-3). 이 경계가 아래 계층(s02 세션·s05 멤버십) 결합
   **위에서** 성립함을 재사용 role 세션 쿠키로 e2e 관찰한다(2.2 게이팅의 결합 강조 재확인).
2. **WS 격리**(7.2, INV-6): 워크스페이스 A 의 첨부를 워크스페이스 B **에만** 소속된(A 비멤버)
   사용자가 `GET /attachments/{id}` 로 요청하면 403 — 다른 WS 의 첨부가 노출되지 않는다. 두
   워크스페이스와 B 전용 사용자를 실제 l2 라우트로 구성한다.
3. **삭제 사용자 결합**(7.3, INV-4): 첨부를 업로드한 사용자를 admin 이 삭제(`is_deleted=true`)
   처리한 뒤, 그 첨부 레코드(스키마에 업로더 FK 부재이므로 레코드 존속으로 관찰)와 그 사용자가
   작성한 문서 `created_by` 가 물리 삭제 없이 DB 에 보존되고, 삭제 사용자의 후속 첨부 업로드·조회
   요청이 로그인 게이트(401)로 차단됨을 관찰한다(s02 세션 게이트가 요청마다 `is_deleted` 재검사).
4. **물리 삭제 부재**(7.4, INV-4): 업로드·서빙·완전삭제 반응 보관(8.6)·참조 소멸 보관(8.7)
   시나리오 전반에서 `attachment` 레코드에 예기치 않은 물리 삭제(DELETE row)가 없고, 보관은 항상
   `is_archived=true` + 파일 이동으로만 표현됨을 스윕 전후 행 수·특정 행 존속으로 확인한다.

## 계정 상태 전이·워크스페이스 구성 헬퍼는 재사용(중복 정의 금지)
사용자 생성·삭제 전이는 `l1_helpers.create_user`/`l1_helpers.set_deleted`, 멤버 추가·두 번째
워크스페이스 생성은 `l2_helpers.add_member`/`l2_helpers.create_workspace`, 문서 생성·삭제는 L3,
휴지통 완전삭제는 L4 라우트 래퍼를 그대로 쓴다. 물리 존재·작성자 보존 관찰은 부팅 앱과 동일
세션 팩토리(`harness.session_local`)의 신규 세션 직접 조회다. 삭제·완전삭제 유발은 실제 admin
라우트·실제 s10 완전삭제·실제 s12 아카이브 스윕으로만 하며 임의 DB status/is_deleted 조작을
하지 않는다(스윕 직접 호출은 실제 s12·s10·s07 코드 실행이므로 허용).

## 재검증 트리거 (design §Revalidation Triggers)
`s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·`s12` 중 하나라도 수정되면 이 스위트(및 로드맵상 그
이후 모든 체크포인트 L6)를 누적 집합 기준으로 재실행한다(s01 수정 시 모든 체크포인트 재실행).
여기서 관측하는 role 게이팅(`require_ws_role`·admin bypass)·WS 격리(첨부→WS 어댑터)·삭제 사용자
레코드 보존·세션 `is_deleted` 재검사(401)·물리 삭제 부재(INV-4)는 s01 계약과
s02·s03·s05·s07·s09·s10·s12 구현 결합에 직접 의존한다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드·conftest·helpers·하위 하네스는 건드리지
않고 재사용만 한다.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select

from app.models import Attachment, Document
from tests.integration_L5 import helpers as h

# 어댑터 매핑-실패(→404)를 관측하기 위한 미존재 리소스 id(시드 범위와 겹치지 않는 큰 값).
MISSING_ID = 999_999_999

# 업로드 바이너리(작은 시그니처 + 페이로드; 25MiB 한도 이하라 저장·서빙·이동 경로만 관찰).
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-l5-combination-edge-image-payload"
_FILE_BYTES = b"%PDF-1.4 l5-combination-edge-file-payload\n%%EOF"

# 아카이브 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 참조 소멸(8.7) 붙여넣기 보호 경계
# 결정성용. 완전삭제 반응(8.6)은 now 에 의존하지 않는다.
_NOW = datetime(2026, 7, 17, 12, 0, 0)
# 참조 소멸 후보의 첨부 created_at 핀 값(현재 버전 이전 → 붙여넣기 보호 통과, 마이크로초 0).
_EARLY = datetime(2026, 1, 1, 0, 0, 0)


def _title(prefix: str) -> str:
    """공유 ``markspace_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


# --- 물리 존재·작성자 보존 관찰 헬퍼 (부팅 앱과 동일 세션 팩토리로 신규 세션 직접 조회) -----------


def _attachment_row(harness, attachment_id: int):
    """attachment 행을 신규 세션으로 직접 조회한다(없으면 None — 물리 삭제 관측용).

    첨부 스키마에는 업로더 FK 가 없으므로 "삭제된 사용자의 첨부 레코드 보존"(7.3)·"물리 삭제
    부재"(7.4)는 이 행의 **존속**(None 아님)으로 관찰한다.
    """
    with harness.session_local() as db:
        return db.get(Attachment, attachment_id)


def _attachment_count(harness) -> int:
    """`SELECT COUNT(*) FROM attachment` 로 커밋된 첨부 행 수를 직접 센다(물리 삭제 부재 판정).

    보관은 `is_archived=true` + 파일 이동일 뿐 DELETE row 가 아니므로, 스윕 전후 이 값이
    변하지 않아야 한다(INV-4).
    """
    with harness.session_local() as db:
        return int(db.scalar(select(func.count()).select_from(Attachment)))


def _document_created_by(harness, document_id: int):
    """document 행의 `created_by` 를 신규 세션으로 직접 조회한다(없으면 None — 물리 삭제 관측용).

    첨부를 업로드한 사용자가 삭제되어도 그 사용자가 작성한 문서의 `created_by` 참조가 물리 삭제
    없이 보존됨(7.3)을 확인하는 데 쓴다.
    """
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.created_by


def _drive_document_to_deleted(editor, workspace_id: int, document_id: int) -> None:
    """실제 s07/s10 완전삭제 경로로 문서를 `status='deleted'` 로 만든다(지름길 아님).

    1. editor 가 `DELETE /documents/{id}`(L3) → 대상 문서(및 하위 트리)가 trashed 캐스케이드.
    2. editor 가 `GET /workspaces/{id}/trash`(L4)로 이 문서를 루트로 하는 묶음을 찾는다.
    3. editor 가 `DELETE /trash/{bundleId}`(L4 purge, **비가역**) → 묶음 구성원 전체 deleted 종착.

    s12 는 이 전이를 소유하지 않는다 — s10/s07 이 만든 deleted 상태에 아카이브 스윕이 반응할 뿐이다.
    """
    h.l3_helpers.delete_document(editor, document_id)
    trash = h.l4_helpers.list_trash(editor, workspace_id)
    bundle = next(
        item for item in trash["items"] if item["root_document_id"] == document_id
    )
    h.l4_helpers.purge_bundle_via_api(editor, bundle["bundle_id"])


# =============================================================================
# 1) role별 접근 경계·admin override — 첨부 업로드·서빙 (Req 7.1, INV-1·2·3)
# =============================================================================


def test_role_boundaries_and_admin_override_on_real_lower_stack(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """owner/editor/viewer/비멤버/admin 재사용 세션으로 첨부 업로드·서빙 경계가 아래 계층 결합
    위에서 성립함을 관찰(7.1, INV-1·2·3).

    판정은 s05 실제 `workspace_member` 데이터 위에서 s01 `require_ws_role` 이 수행한다: 업로드는
    `require_ws_role(EDITOR)`(문서→WS 어댑터), 서빙은 `require_ws_role(VIEWER)`(첨부→WS 어댑터).
    2.2 게이팅과 관측 표면은 겹치나, 여기서는 그 경계가 s02 세션 인증 + s05 멤버십 **결합 위에서**
    재사용 role 세션 쿠키로 성립함을 강조한다:

    - **업로드(편집)**: owner 201·member 201·비멤버 활성 사용자 403(Req 4.6)·미인증 401·admin
      (비멤버) 201(INV-3)·미존재 문서 404(문서→WS 어댑터 매핑 실패, 판정 이전).
    - **서빙(읽기 전역 개방)**: member 가 만든 첨부를 member·비멤버 활성 사용자 모두 200(s26
      Req 3.4·3.8, 더 이상 403 아님)·미인증 401·admin 200(INV-3)·미존재 첨부 404(어댑터 매핑 실패).
    """
    scenario = doc_tree_scenario.scenario
    ws_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id

    def _upload(client, doc=doc_id):
        return h.attempt_upload_attachment(
            client,
            doc,
            filename="edge.png",
            content=_IMAGE_BYTES,
            content_type="image/png",
        )

    # --- 업로드 경계(EDITOR): s02 세션 + s05 멤버십 결합 위에서 판정 ---
    assert _upload(scenario.owner_client).status_code == 201, "owner 업로드 201(7.1)"
    assert _upload(scenario.editor_client).status_code == 201, "editor 업로드 201(7.1)"
    assert _upload(scenario.viewer_client).status_code == 403, (
        "viewer(비멤버) 업로드 403(편집 멤버십 요구, Req 4.6)"
    )
    assert _upload(scenario.nonmember_client).status_code == 403, (
        "비멤버 업로드 403(INV-1, anti-enumeration)"
    )
    assert _upload(harness.new_client()).status_code == 401, (
        "미인증(세션 없음) 업로드 401(s02 세션 게이트)"
    )
    assert _upload(scenario.admin_client).status_code == 201, (
        "admin(비멤버지만 resolver bypass) 업로드 201(INV-3)"
    )
    assert _upload(scenario.editor_client, MISSING_ID).status_code == 404, (
        "미존재 문서 업로드 404(문서→WS 어댑터 매핑 실패, role 판정 이전)"
    )

    # --- 서빙 경계(VIEWER): editor 가 만든 첨부 위에서 판정 ---
    att = h.upload_image(scenario.editor_client, doc_id, content=_IMAGE_BYTES)
    att_id = att["id"]
    # 첨부는 대상 문서의 WS 로 격리 확정(아래 계층 결합의 관측 근거).
    assert att["workspace_id"] == ws_id, "첨부 소속 WS 는 대상 문서의 WS 로 확정된다(7.1 결합)"

    assert h.attempt_get_attachment(scenario.viewer_client, att_id).status_code == 200, (
        "viewer(비멤버) 서빙 200(읽기 전역 개방, 3.8)"
    )
    assert (
        h.attempt_get_attachment(scenario.nonmember_client, att_id).status_code == 200
    ), "비멤버 서빙 200(읽기 전역 개방, 3.8 — 403 아님)"
    assert h.attempt_get_attachment(harness.new_client(), att_id).status_code == 401, (
        "미인증 서빙 401(s02 세션 게이트)"
    )
    assert h.attempt_get_attachment(scenario.admin_client, att_id).status_code == 200, (
        "admin(비멤버지만 bypass) 서빙 200(INV-3)"
    )
    assert h.attempt_get_attachment(scenario.viewer_client, MISSING_ID).status_code == 404, (
        "미존재 첨부 서빙 404(첨부→WS 어댑터 매핑 실패)"
    )


# =============================================================================
# 2) WS 격리 — 다른 워크스페이스의 첨부 비노출 (Req 7.2, INV-6)
# =============================================================================


def test_cross_workspace_attachment_read_open_but_edit_isolated(
    doc_tree_scenario, harness, tmp_attachment_roots
):
    """워크스페이스 A 의 첨부를 B **에만** 소속된(A 비멤버) 사용자가 **조회하면 200**(읽기 전역
    개방, s26 Req 3.4·7.2)이되, A 문서로의 **업로드(편집)**는 403 으로 격리된다(편집 멤버십 요구).

    두 워크스페이스와 B 전용 사용자를 실제 라우트로 구성한다:

    1. 워크스페이스 A(`doc_tree_scenario`)의 member 가 문서에 첨부를 업로드한다.
    2. admin 이 신규 사용자 U 를 만들고, U 가 자신의 워크스페이스 B 를 생성한다(`create_workspace`
       계약상 U 는 B 의 owner 멤버로 자동 등록 — 즉 U 는 B 의 멤버이지만 A 의 멤버는 아니다).
    3. U 가 `GET /attachments/{A 첨부 id}` 를 요청하면 s26 읽기 전역 개방으로 **200**(다른 WS
       첨부도 활성 사용자면 읽을 수 있다 — 읽기에 한해 WS 격리 완화, Req 3.4·7.2).
    4. 반면 U 가 A 의 문서에 첨부를 **업로드**(편집)하려 하면 403 — 편집은 여전히 멤버십 단위로
       격리된다(A 비멤버, Req 4.6). 읽기 개방과 편집 격리를 한 테스트에서 대조한다.
    """
    scenario = doc_tree_scenario.scenario
    ws_a_id = doc_tree_scenario.workspace_id
    doc_id = doc_tree_scenario.root_id

    # (1) 워크스페이스 A 에 첨부 업로드.
    att = h.upload_image(scenario.editor_client, doc_id, content=_IMAGE_BYTES)
    att_id = att["id"]
    assert att["workspace_id"] == ws_a_id, "첨부는 워크스페이스 A 에 격리된다(업로드 전제)"

    # (2) B 전용 사용자 U + 워크스페이스 B(U 는 B 의 owner 멤버, A 의 멤버 아님).
    login_id = h.l1_helpers.unique_login_id("ws-b-only")
    b_user_id = h.l1_helpers.create_user(
        scenario.admin_client, login_id, h.l1_helpers.DEFAULT_PASSWORD, name="B전용사용자"
    )
    b_client = harness.login(login_id, h.l1_helpers.DEFAULT_PASSWORD)
    ws_b_id = h.l2_helpers.create_workspace(b_client, _title("WS-B"))
    assert ws_b_id != ws_a_id, "워크스페이스 B 는 A 와 다른 워크스페이스여야 한다(WS 경계 전제)"

    # (3) B 전용 사용자가 A 의 첨부를 조회 → 200(읽기 전역 개방, 403 아님, Req 3.4·7.2).
    assert h.attempt_get_attachment(b_client, att_id).status_code == 200, (
        "B 에만 소속된(A 비멤버) 사용자도 A 첨부를 읽기 개방으로 200 조회해야 한다"
        "(읽기 격리 완화, Req 3.4·7.2)"
    )

    # (4) 대조: B 전용 사용자의 A 문서로의 업로드(편집)는 403 — 편집은 멤버십 단위 격리(Req 4.6).
    upload_denied = h.attempt_upload_attachment(
        b_client, doc_id, filename="pic.png", content=_IMAGE_BYTES, content_type="image/png"
    )
    assert upload_denied.status_code == 403, (
        "A 비멤버의 A 문서 첨부 업로드(편집)는 403 이어야 한다(편집 격리, Req 4.6): "
        f"{upload_denied.status_code} {upload_denied.text}"
    )

    # (대조) A 의 member 는 같은 첨부를 200 으로 조회 — 소속 WS 접근도 정상.
    assert h.attempt_get_attachment(scenario.editor_client, att_id).status_code == 200, (
        "A 의 member 는 A 첨부를 조회할 수 있어야 한다(소속 WS 접근 정상)"
    )
    _ = b_user_id  # 사용자 생성이 실제 계정 라우트를 태웠음을 명시(재사용 계약).


# =============================================================================
# 3) 삭제 사용자 결합 — 첨부 레코드·문서 작성자 보존·로그인 게이트 (Req 7.3, INV-4)
# =============================================================================


def test_deleted_uploader_records_preserved_and_login_gated(
    ws_scenario, harness, tmp_attachment_roots
):
    """첨부를 업로드한 사용자를 admin 이 삭제(`is_deleted=true`)해도 첨부 레코드·문서 `created_by`
    보존·후속 401(7.3, INV-4).

    아래 계층 결합을 실제 라우트로 밟는다: admin 이 신규 사용자 U 를 만들고 owner 가 EDITOR 로
    추가한 뒤, U 세션으로 문서를 만들고 그 문서에 첨부를 업로드한다(작성자=U). 이후 admin 이 U 를
    삭제 처리하면:

    - U 가 업로드한 `attachment` 행이 **여전히 물리 존재**한다(첨부 스키마에 업로더 FK 가 없으므로
      레코드 존속으로 보존을 관찰).
    - U 가 작성한 `document` 행의 `created_by` 가 **여전히** U 의 id 를 참조한다(작성자 참조 보존).
    - 삭제된 U 의 후속 첨부 업로드·조회 요청이 세션 게이트(s01 `get_current_user` 의 `is_deleted`
      재검사)로 401 차단된다(권한 403 이전의 로그인 게이트).

    ws_scenario 의 기존 세션을 훼손하지 않도록 **신규** 사용자를 만들어 삭제한다.
    """
    admin = ws_scenario.admin_client
    owner = ws_scenario.owner_client
    ws_id = ws_scenario.workspace_id

    # 신규 EDITOR 멤버 U 생성 → 로그인(아래 계층: s03 생성 → s05 멤버십 → s02 세션).
    login_id = h.l1_helpers.unique_login_id("uploader")
    uploader_uid = h.l1_helpers.create_user(
        admin, login_id, h.l1_helpers.DEFAULT_PASSWORD, name="업로더"
    )
    h.l2_helpers.add_member(owner, ws_id, uploader_uid, "member")
    uploader_client = harness.login(login_id, h.l1_helpers.DEFAULT_PASSWORD)

    # U 세션으로 문서 생성 + 첨부 업로드(작성자=U).
    doc_id = h.l3_helpers.create_document(uploader_client, ws_id, _title("업로더문서"))["id"]
    att = h.upload_file(uploader_client, doc_id, content=_FILE_BYTES)
    att_id = att["id"]

    # 삭제 전: 첨부 행 존재·문서 created_by=U 확정(보존 대조 기준).
    assert _attachment_row(harness, att_id) is not None, "삭제 전 첨부 행이 존재해야 한다(7.3 전제)"
    assert _document_created_by(harness, doc_id) == uploader_uid, (
        "문서 created_by 는 업로더여야 한다(7.3 전제)"
    )

    # admin 이 업로더를 삭제 처리(is_deleted=true) — s03 계정 생명주기(물리 삭제 아님).
    h.l1_helpers.set_deleted(admin, uploader_uid, True)

    # (첨부 레코드 보존) 업로더 삭제 후에도 첨부 행이 물리 존재(업로더 FK 부재 → 존속으로 관찰).
    att_row = _attachment_row(harness, att_id)
    assert att_row is not None, (
        "업로더 삭제 후에도 업로드한 첨부 레코드는 물리 보존되어야 한다(7.3, INV-4)"
    )
    assert att_row.is_archived is False, (
        "업로더 삭제는 첨부 보관 이동을 유발하지 않는다(레코드는 미보관 상태로 존속)"
    )
    # (문서 작성자 참조 보존) created_by 가 여전히 삭제된 업로더 id 를 참조.
    assert _document_created_by(harness, doc_id) == uploader_uid, (
        "업로더 삭제 후에도 문서 created_by 참조는 보존되어야 한다(7.3, INV-4)"
    )

    # (로그인 게이트) 삭제된 업로더의 후속 첨부 업로드·조회는 세션 게이트로 401(403 권한 이전).
    assert (
        h.attempt_upload_attachment(
            uploader_client,
            doc_id,
            filename="after.pdf",
            content=_FILE_BYTES,
            content_type="application/octet-stream",
            kind="file",
        ).status_code
        == 401
    ), "삭제된 업로더의 후속 업로드는 401 로그인 게이트로 차단되어야 한다(7.3, s02 세션 게이트)"
    assert h.attempt_get_attachment(uploader_client, att_id).status_code == 401, (
        "삭제된 업로더의 후속 첨부 조회도 401 로 차단되어야 한다(7.3, 권한 403 이전 로그인 게이트)"
    )

    # (대조) 살아있는 멤버(owner)는 같은 첨부를 여전히 조회 가능 — 레코드가 실제로 존속함을 확인.
    assert h.attempt_get_attachment(owner, att_id).status_code == 200, (
        "보존된 첨부는 살아있는 멤버가 여전히 서빙받을 수 있어야 한다(레코드 존속 확인)"
    )


# =============================================================================
# 4) 물리 삭제 부재 — 업로드·서빙·보관(8.6/8.7) 전반 attachment DELETE row 부재 (Req 7.4, INV-4)
# =============================================================================


def test_no_physical_delete_of_attachment_rows_across_scenarios(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """업로드·서빙·완전삭제 반응 보관(8.6)·참조 소멸 보관(8.7) 전반에서 `attachment` 레코드 물리
    삭제 부재·보관은 항상 `is_archived=true` + 파일 이동으로만 표현(7.4, INV-4).

    같은 워크스페이스에 세 독립 문서·첨부를 두고 각 시나리오를 실제 경로로 밟는다:

    - **SERVED**(업로드·서빙): active 문서의 이미지 첨부를 viewer 가 서빙(200) — 접근되어도 보관·
      삭제되지 않는다.
    - **PURGE**(완전삭제 반응, 8.6): 문서를 실제 완전삭제(deleted)한 뒤 아카이브 스윕이 파일 첨부를
      보관 이동(`is_archived=true`).
    - **DEREF**(참조 소멸, 8.7): 이미지 첨부를 참조한 현재 버전을 참조 없는 새 버전으로 저장해
      현재 버전 참조를 소멸시키면 아카이브 스윕이 이미지를 보관 이동(`is_archived=true`).

    아카이브 스윕 **전후** attachment 행 수가 불변(DELETE row 부재)이고, 세 첨부 행이 모두 물리
    존속하며, 보관 대상 둘은 `is_archived=true` 로 **표시**될 뿐(행 삭제 아님)·SERVED 는 미보관
    존속임을 DB·파일시스템·API 로 확인한다.
    """
    scenario = doc_tree_scenario.scenario
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client
    viewer = scenario.viewer_client

    # 세 독립 문서(트리 캐스케이드 간섭 회피를 위해 신규 생성).
    served_doc = h.l3_helpers.create_document(editor, ws_id, _title("존속-서빙"))["id"]
    purge_doc = h.l3_helpers.create_document(editor, ws_id, _title("존속-완전삭제"))["id"]
    deref_doc = h.l3_helpers.create_document(editor, ws_id, _title("존속-참조소멸"))["id"]

    # SERVED: active 이미지 첨부(현재 버전 없음 → 8.6/8.7 어느 스코프에도 안 듦 → 존속·미보관).
    served_att = h.upload_image(editor, served_doc, content=_IMAGE_BYTES)["id"]
    # PURGE: 파일 첨부(kind=file 은 8.7 스코프 밖 → 8.6 완전삭제 반응만이 보관 경로).
    purge_att = h.upload_file(editor, purge_doc, content=_FILE_BYTES)["id"]
    # DEREF: 이미지 첨부(참조 소멸 8.7 대상).
    deref_att = h.upload_image(editor, deref_doc, content=_IMAGE_BYTES)["id"]

    # SERVED 첨부는 서빙 가능(업로드·서빙 시나리오 — 접근으로 삭제·보관되지 않는다).
    assert h.attempt_get_attachment(viewer, served_att).status_code == 200, (
        "active 문서 첨부는 서빙 가능해야 한다(업로드·서빙 시나리오)"
    )

    # 아카이브 스윕 이전 행 수 스냅샷(물리 삭제 부재 비교 기준 — 세 첨부).
    count_before = _attachment_count(harness)
    assert count_before == 3, (
        f"업로드한 세 첨부가 커밋되어 있어야 한다(결정적 하네스): {count_before}"
    )

    # PURGE 경로: 실제 완전삭제로 deleted 전이(8.6 반응 조건 구성 — s12 지름길 아님).
    _drive_document_to_deleted(editor, ws_id, purge_doc)

    # DEREF 경로: 참조 포함 저장(v1) → 참조 제거 저장(v2)으로 현재 버전 참조 소멸(실제 s09 저장).
    h.save_with_reference(editor, deref_doc, deref_att)
    h.save_without_reference(editor, deref_doc)
    # 붙여넣기 보호 통과(att.created_at <= 현재 버전) 결정성용 핀(테스트 시드 조작).
    with harness.session_local() as db:
        att = db.get(Attachment, deref_att)
        att.created_at = _EARLY
        db.commit()

    # 아카이브 스윕 1회 — PURGE(8.6)·DEREF(8.7) 두 첨부만 보관 이동(SERVED 는 스코프 밖).
    processed = h.run_archival_sweep(archival_sweep, _NOW)
    assert processed == 2, (
        f"완전삭제 반응(8.6)·참조 소멸(8.7) 두 첨부만 보관 이동되어야 한다(SERVED 미대상): {processed}"
    )

    # (물리 삭제 부재 — 행 수) 보관은 DELETE row 가 아니므로 첨부 행 수는 스윕 전후 불변(INV-4).
    count_after = _attachment_count(harness)
    assert count_after == count_before, (
        f"보관 이동은 물리 삭제(DELETE row)가 아니므로 첨부 행 수는 불변이어야 한다(7.4, INV-4): "
        f"전={count_before} 후={count_after}"
    )

    # (특정 행 존속) 세 첨부 행이 모두 물리 존재 — 보관 대상 둘은 is_archived=true 표시일 뿐.
    served_row = _attachment_row(harness, served_att)
    purge_row = _attachment_row(harness, purge_att)
    deref_row = _attachment_row(harness, deref_att)
    assert served_row is not None and served_row.is_archived is False, (
        "SERVED 첨부는 물리 존속·미보관이어야 한다(업로드·서빙만으로는 보관·삭제되지 않음)"
    )
    assert purge_row is not None and purge_row.is_archived is True, (
        "PURGE 첨부는 물리 존속하며 완전삭제 반응으로 is_archived=true 표시일 뿐(삭제 아님, INV-4)"
    )
    assert deref_row is not None and deref_row.is_archived is True, (
        "DEREF 첨부는 물리 존속하며 참조 소멸로 is_archived=true 표시일 뿐(삭제 아님, INV-4)"
    )

    # (보관=파일 이동) 보관 대상은 보관 루트에 원본 바이트로 이동·저장 루트에서 소멸(삭제 아님).
    for att_id, payload in ((purge_att, _FILE_BYTES), (deref_att, _IMAGE_BYTES)):
        archived_rel = purge_row.file_path if att_id == purge_att else deref_row.file_path
        h.assert_ws_isolated(archived_rel, ws_id)
        archived_file = h.assert_archived(tmp_attachment_roots, archived_rel)
        assert archived_file.read_bytes() == payload, (
            "보관은 파일 이동일 뿐 — 보관 위치에 원본 바이트로 존재해야 한다(INV-4)"
        )

    # (API 표면) 보관 첨부는 role 무관 404(행은 존속하되 비노출), SERVED 는 여전히 200.
    assert h.attempt_get_attachment(viewer, purge_att).status_code == 404, (
        "보관된 첨부는 조회 불가(404) — 그러나 행은 물리 존속(비노출이지 삭제 아님)"
    )
    assert h.attempt_get_attachment(viewer, deref_att).status_code == 404, (
        "보관된 이미지 첨부는 조회 불가(404) — 그러나 행은 물리 존속(비노출이지 삭제 아님)"
    )
    assert h.attempt_get_attachment(viewer, served_att).status_code == 200, (
        "미보관 SERVED 첨부는 스윕 전반에서 여전히 서빙 가능해야 한다(물리 삭제·보관 부재)"
    )
