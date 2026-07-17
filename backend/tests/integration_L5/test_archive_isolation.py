"""보관 격리·비노출 스위트 — role 무관 404(admin 포함·권한 판정 이전 차단)·복원 경로 부재·
보관 폴더 WS 격리·단조 증가 (Task 2.5 / Req 6.1·6.2·6.3·6.4·6.5, design §ArchiveIsolationSuite,
§System Flows "보관 비노출 — role 무관 404"; s12 8.9·8.10·8.11·INV-7 교차참조).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕**s12** 첨부 라우터·아카이브
스케줄러 조립, `app.main.create_app`) 위에서, **실제** 8.6 완전삭제 반응 스윕으로 첨부를 보관
처리한 뒤 그 보관 첨부가 어떤 role 로도(admin 포함) 노출되지 않고 복원 경로가 없으며 반복
스윕에도 존속함을 mock 없이 결합 검증한다. 저장/보관 루트만 tmp 로 격리
(`tmp_attachment_roots`)해 디스크상 보관 이동·존속을 실제 파일시스템으로 관찰한다.

핵심 seam(INV-7): 보관 이동은 **영구삭제로 간주**된다 — 보관된 첨부는 요청자 role 과 무관하게
`GET /attachments/{id}` 가 404 이고(6.1), admin 마저 404 이며 이 보관 차단이 `require_ws_role`
권한 판정에 **도달하기 전에** 성립한다(6.2). 실제 서비스(`app/attachment/service.py::
serve_attachment`)는 첨부 로드 후 `is_archived` 이면 role 인자를 애초에 받지 않고 **무조건** 404
를 낸다(role-agnostic). 라우터의 `ws_role_for_attachment(VIEWER)` 게이트가 먼저 실행되지만,
member(owner/editor/viewer)는 게이트를 통과한 뒤 서비스가 404 를 내고, admin 은 게이트를
bypass(INV-3)한 뒤에도 서비스가 404 를 낸다 — 두 경우 모두 보관 첨부는 404 다.

보관 유발은 **실제 8.6 스윕**으로만 한다(임의 DB `is_archived` 조작 금지): 파일 첨부 업로드 →
`DELETE /documents/{id}`(trashed 캐스케이드) → `DELETE /trash/{bundleId}`(purge → deleted) →
`run_archival_sweep(now)`. `kind=file` 을 써서 8.7 참조 소멸(image 한정) 간섭 없이 8.6 완전삭제
반응 seam 만으로 결정적으로 보관 처리한다(스윕 처리 건수 결정성).

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드·conftest·helpers·하네스는 건드리지 않고
재사용만 한다. 재검증 트리거: s01/s02/s03/s05/s07/s09/s10/s12 중 하나라도 수정되면 이
체크포인트를 누적 집합 기준으로 재실행한다(s01 수정 시 모든 체크포인트 재실행).
"""

from datetime import datetime

from tests.integration_L5 import helpers as h

# 업로드 바이너리(일반 파일 첨부; kind=file 은 8.7 참조 소멸(image 한정)에서 제외되므로 이
# 첨부를 보관 이동시킬 수 있는 경로는 오직 8.6 완전삭제 반응뿐이다 — 보관 유발 seam 을 격리).
_FILE_BYTES = b"%PDF-1.4 l5-archive-isolation-payload\n%%EOF"

# 아카이브 스윕에 주입할 고정 now(whole-second, DATETIME(0)). 8.6 은 now 에 의존하지 않으나
# 배치 계약 일관성상 API 가 받는다.
_NOW = datetime(2026, 7, 17, 12, 0, 0)

# 보관 첨부를 active 로 되돌리는(복원/un-archive) 경로가 없음을 관찰하기 위한 금지 키워드
# (6.4·INV-7). 첨부 라우트 경로에 이 중 어느 것도 나타나면 안 된다.
_RESTORE_KEYWORDS = (
    "restore",
    "unarchive",
    "un-archive",
    "un_archive",
    "reactivate",
    "activate",
    "recover",
)


def _iter_all_routes(app):
    """부팅 앱의 모든 라우트를 산출한다 — 최상위 라우트 + `_IncludedRouter` 래퍼 하위 라우트.

    `s01` 조립 지점은 `include_router` 로 각 feature 라우터를 `_IncludedRouter` 래퍼로 감싸
    앱에 등록하며, 실제 `APIRoute`(`.path`·`.methods` 보유)는 래퍼의 `.original_router.routes`
    아래에 있다. 첨부 라우트를 놓치지 않으려면 두 층을 모두 훑어야 한다(라우트 열거가 빈
    결과로 검증을 무의미화하지 않도록 6.4 단언 전에 발견 여부도 확인한다).
    """
    for route in app.routes:
        yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from getattr(original, "routes", [])


def _drive_document_to_deleted(scenario, document_id, workspace_id):
    """실제 s07/s10 완전삭제 경로로 문서를 `status='deleted'` 로 만든다(지름길 아님, Req 6.1 전제).

    1. editor 가 `DELETE /documents/{id}`(L3) → 대상 문서(및 하위 트리)가 trashed 캐스케이드.
    2. editor 가 `GET /workspaces/{id}/trash`(L4)로 이 문서를 루트로 하는 묶음을 찾는다.
    3. editor 가 `DELETE /trash/{bundleId}`(L4 purge, **비가역**) → 묶음 구성원 전체가 deleted.

    s12 는 이 전이를 소유하지 않는다 — s10/s07 이 만든 deleted 상태를 뒤에서 관측할 뿐이다.
    (2.3 완전삭제 결합 스위트의 archive-inducing purge→sweep 경로와 동일 형태를 재사용한다.)
    """
    editor = scenario.editor_client
    h.l3_helpers.delete_document(editor, document_id)

    trash = h.l4_helpers.list_trash(editor, workspace_id)
    bundle = next(
        item for item in trash["items"] if item["root_document_id"] == document_id
    )
    h.l4_helpers.purge_bundle_via_api(editor, bundle["bundle_id"])


def _archive_file_attachment(scenario, harness, archival_sweep, document_id, workspace_id):
    """대상 문서에 파일 첨부를 업로드하고 **실제 8.6 스윕**으로 보관 처리한 뒤
    ``(attachment_id, archived_rel_path)`` 를 반환한다(임의 DB 조작 아님).

    파일 첨부 업로드(SETUP) → 완전삭제 경로로 문서 deleted 전이 → `run_archival_sweep(now)`
    (실제 `ArchivalSweepService`) 순서로, 보관을 오직 실제 스윕이 유발하게 한다. 보관이 실제로
    일어났음을 `is_archived=true` DB 부수효과로 확인해(임의 `is_archived` 조작이 아님을 보증)
    후속 단언의 전제를 세운다.
    """
    editor = scenario.editor_client
    att = h.upload_file(editor, document_id, content=_FILE_BYTES)
    att_id = att["id"]

    # 업로드 직후: 미보관(스윕 이전 상태 — 보관은 아래 실제 스윕이 유발함).
    assert h.attachment_is_archived(harness.session_local, att_id) is False, (
        "업로드 직후 첨부는 미보관이어야 한다(보관은 실제 스윕만 유발)"
    )

    # 실제 완전삭제 경로로 deleted 전이(s07/s10 purge — s12 지름길 아님).
    _drive_document_to_deleted(scenario, document_id, workspace_id)

    # 실제 s12 아카이브 스윕 1회 — 부팅 앱과 동일 세션 팩토리로 실제 ArchivalSweepService 구동.
    processed = h.run_archival_sweep(archival_sweep, _NOW)
    assert processed == 1, (
        f"deleted 문서의 미보관 파일 첨부 1건만 보관 이동되어야 한다(결정적 하네스): {processed}"
    )

    # 보관이 실제 스윕으로 일어났음을 DB 부수효과로 확인(임의 is_archived 조작이 아님 — 레코드
    # 는 물리 삭제 없이 존속하며 is_archived=true 로만 표시됨, INV-4).
    assert h.attachment_is_archived(harness.session_local, att_id) is True, (
        "완전삭제 반응(실제 8.6 스윕)으로 첨부는 보관됨(is_archived=true)"
    )
    archived_rel_path = h.attachment_file_path(harness.session_local, att_id)
    assert archived_rel_path is not None, "보관 첨부의 보관 file_path 가 커밋되어 있어야 한다"
    return att_id, archived_rel_path


# =============================================================================
# 1) role 무관 404 — 보관 첨부는 viewer·editor·owner 모두 404 (Req 6.1, 8.10)
# =============================================================================


def test_archived_attachment_returns_404_for_all_member_roles(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """보관된 첨부의 `GET /attachments/{id}` 가 소속 WS 의 모든 member role(viewer·editor·owner)
    에게 404 임을 검증한다(Req 6.1, 8.10 — role 무관 비노출).

    세 role 모두 소속 WS 멤버이므로 라우터의 `ws_role_for_attachment(VIEWER)` 게이트는
    통과하지만, 서비스가 `is_archived` 를 role 과 무관하게 무조건 404 로 차단한다. 첨부 레코드는
    물리 삭제 없이 존속(is_archived=true 로 확인됨)하므로 이 404 는 부재가 아니라 **보관 차단**의
    결과다.
    """
    ws_id = doc_tree_scenario.workspace_id
    scenario = doc_tree_scenario.scenario

    att_id, _ = _archive_file_attachment(
        scenario, harness, archival_sweep, doc_tree_scenario.root_id, ws_id
    )

    # viewer·editor·owner 모두 소속 WS 멤버지만 보관 첨부는 role 무관 404(8.10).
    for role_name, client in (
        ("viewer", scenario.viewer_client),
        ("editor", scenario.editor_client),
        ("owner", scenario.owner_client),
    ):
        resp = h.attempt_get_attachment(client, att_id)
        assert resp.status_code == 404, (
            f"{role_name} 세션은 보관 첨부 조회 시 404 여야 한다(role 무관 비노출): "
            f"{resp.status_code} {resp.text}"
        )


# =============================================================================
# 2) admin 404 · 권한 판정 이전 차단 — admin bypass 경로에서도 보관 첨부는 404 (Req 6.2, 8.9)
# =============================================================================


def test_admin_gets_404_and_archive_block_precedes_permission_resolution(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """admin 도 보관 첨부에 404 이고, 이 보관 차단이 `require_ws_role` 권한 판정보다 **먼저/
    무관하게** 성립함을 검증한다(Req 6.2, 8.9 — admin 포함 비노출, 권한 판정 이전 차단).

    seed admin 은 이 WS 의 **비멤버**이지만 INV-3 로 role 게이트를 bypass 한다. 대조를 위해:

    - **미보관** 첨부(별도 active 문서)를 admin 이 조회하면 200 — admin 의 bypass 가 실제로
      권한 판정을 통과해 서빙에 도달함을 증명한다(권한 게이트가 admin 을 막지 않음).
    - **보관** 첨부를 같은 admin·같은 bypass 경로로 조회하면 404 — 권한이 통과된(bypass 된)
      상태에서도 보관 차단이 404 를 낸다. 즉 보관 차단은 권한 판정 결과에 의존하지 않고 그것을
      override/선행한다(role-agnostic).
    """
    ws_id = doc_tree_scenario.workspace_id
    scenario = doc_tree_scenario.scenario
    editor = scenario.editor_client
    admin = scenario.admin_client

    # 대조용 미보관 첨부(삭제하지 않는 별도 active 문서 — 스윕이 건드리지 않음).
    active_doc = h.l3_helpers.create_document(editor, ws_id, "admin-대조-활성문서")
    active_att = h.upload_file(editor, active_doc["id"], content=_FILE_BYTES)

    # 실제 8.6 스윕으로 root 문서의 파일 첨부를 보관 처리(active 문서 첨부는 미보관 유지).
    archived_att_id, _ = _archive_file_attachment(
        scenario, harness, archival_sweep, doc_tree_scenario.root_id, ws_id
    )
    assert h.attachment_is_archived(harness.session_local, active_att["id"]) is False, (
        "대조용 active 문서 첨부는 보관되지 않아야 한다(권한 통과 경로 대조 기준)"
    )

    # (권한 통과 증명) admin 은 이 WS 비멤버지만 INV-3 bypass 로 미보관 첨부를 서빙받는다(200).
    active_resp = h.attempt_get_attachment(admin, active_att["id"])
    assert active_resp.status_code == 200, (
        "admin 은 비멤버 WS 라도 INV-3 bypass 로 미보관 첨부를 서빙받아야 한다(권한 게이트 통과): "
        f"{active_resp.status_code} {active_resp.text}"
    )

    # (권한 판정 이전/무관 차단) 같은 admin·같은 bypass 경로인데 보관 첨부는 404 — 보관 차단이
    # 권한 판정 결과에 의존하지 않고 override/선행한다(role-agnostic, 8.9·8.10).
    archived_resp = h.attempt_get_attachment(admin, archived_att_id)
    assert archived_resp.status_code == 404, (
        "admin 도 보관 첨부는 404 여야 한다(보관 차단이 권한 판정을 override/선행): "
        f"{archived_resp.status_code} {archived_resp.text}"
    )


# =============================================================================
# 3) 보관 폴더 WS 격리 — 보관 파일이 attachment_archive_root/{workspace_id}/ 하위 (Req 6.3, INV-6)
# =============================================================================


def test_archived_file_isolated_under_workspace_archive_folder(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """보관된 파일이 `attachment_archive_root/{workspace_id}/` 하위에 격리되어 다른 WS 경로에
    섞이지 않음을 파일시스템 관찰로 검증한다(Req 6.3, 8.8, INV-6).

    보관 후 DB `file_path`(보관 rel path)가 `{workspace_id}/` 로 시작하고, 그 상대 경로가 보관
    루트 하위의 WS 격리 위치에 원본 바이트로 물리 존재함을 확인한다. 또한 다른 임의의
    workspace id 접두 경로로는 해석되지 않음을 확인해 WS 경로 혼입 부재를 관찰한다.
    """
    ws_id = doc_tree_scenario.workspace_id
    scenario = doc_tree_scenario.scenario

    att_id, archived_rel_path = _archive_file_attachment(
        scenario, harness, archival_sweep, doc_tree_scenario.root_id, ws_id
    )

    # (WS 격리 — 경로) 보관 rel path 가 소속 WS id 로 시작한다(다른 WS 경로에 섞이지 않음).
    h.assert_ws_isolated(archived_rel_path, ws_id)

    # (WS 격리 — 디스크) 보관 루트 하위 {workspace_id}/... 위치에 원본 바이트로 물리 존재.
    archived_file = h.assert_archived(tmp_attachment_roots, archived_rel_path)
    assert archived_file.read_bytes() == _FILE_BYTES, (
        "보관된 파일 내용은 원본과 동일해야 한다(이동일 뿐 삭제·훼손 아님, INV-4)"
    )
    assert archived_file.parent.name == str(ws_id), (
        f"보관 파일은 WS 격리 폴더(attachment_archive_root/{ws_id}) 하위에 있어야 한다: "
        f"{archived_file}"
    )

    # (혼입 부재) 다른 WS id 접두 경로로는 이 보관 파일이 존재하지 않는다(경로 혼입 관찰).
    other_ws_rel_path = archived_rel_path.replace(f"{ws_id}/", f"{ws_id + 1}/", 1)
    h.assert_not_archived(tmp_attachment_roots, other_ws_rel_path)


# =============================================================================
# 4) 복원 없음 — 보관 첨부를 active 로 되돌리는 경로 부재·조회 어떤 role 로도 미성공 (Req 6.4, INV-7)
# =============================================================================


def test_no_restore_route_and_archived_stays_404_for_all_roles(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """보관 첨부를 active 로 되돌리는(복원/un-archive) 엔드포인트가 없고, 보관 후 조회가 어떤
    role 로도 성공하지 않음을 검증한다(Req 6.4, INV-7 — 보관 이동은 영구삭제로 간주).

    - **복원 경로 부재**: 부팅 앱의 라우트를 열거해 첨부 관련 경로가 카탈로그 행 32~33 두 개
      (`POST /documents/{id}/attachments`·`GET /attachments/{id}`)뿐이고, 복원/un-archive
      키워드 경로가 없으며, `/attachments/{id}` 가 상태를 바꾸는 PUT/PATCH/DELETE(un-archive)
      를 노출하지 않음(GET 서빙만)을 확인한다.
    - **반복 조회 404**: 보관 후 viewer·editor·owner·admin 이 반복 조회해도 계속 404 다(복원
      불가로 어떤 role 로도 되살아나지 않음).
    """
    ws_id = doc_tree_scenario.workspace_id
    scenario = doc_tree_scenario.scenario

    att_id, _ = _archive_file_attachment(
        scenario, harness, archival_sweep, doc_tree_scenario.root_id, ws_id
    )

    # 부팅 앱 라우트 열거 — 첨부 관련 경로와 메서드 수집(복원 경로 부재 관찰). 부팅 앱은
    # `include_router` 로 각 라우터를 `_IncludedRouter` 래퍼(`.original_router.routes` 에 실제
    # `APIRoute` 보유)로 조립하므로, 최상위 라우트와 래퍼 하위 라우트를 모두 훑는다.
    attachment_routes: dict[str, set[str]] = {}
    for route in _iter_all_routes(harness.app):
        path = getattr(route, "path", "") or ""
        if "attachment" not in path.lower():
            continue
        methods = set(getattr(route, "methods", None) or set())
        attachment_routes.setdefault(path, set()).update(methods)

    # 첨부 라우트가 실제로 발견되어야 한다(열거 방식이 라우트를 놓치지 않았음을 보증 — 빈
    # 집합이 우연히 "복원 경로 없음"으로 오판되지 않게 함).
    assert attachment_routes, (
        "부팅 앱에서 첨부 라우트를 열거하지 못했다(열거 방식 점검 필요 — 검증 무의미화 방지)"
    )

    # (복원 키워드 부재) 어떤 첨부 경로에도 복원/un-archive/reactivate 등의 키워드가 없다.
    for path in attachment_routes:
        low = path.lower()
        for keyword in _RESTORE_KEYWORDS:
            assert keyword not in low, (
                f"보관 첨부를 되돌리는 복원 경로가 존재하면 안 된다(INV-7): {path} (keyword={keyword})"
            )

    # (첨부 엔드포인트는 카탈로그 행 32~33 두 개뿐 — 별도 un-archive 라우트 없음)
    assert set(attachment_routes) == {
        "/documents/{id}/attachments",
        "/attachments/{id}",
    }, (
        f"첨부 라우트는 카탈로그 행 32~33 두 개뿐이어야 한다(복원 경로 추가 없음): "
        f"{sorted(attachment_routes)}"
    )

    # (`/attachments/{id}` 는 GET 서빙만 — 상태를 바꾸는 PUT/PATCH/DELETE(un-archive) 부재)
    serve_methods = attachment_routes["/attachments/{id}"]
    assert "GET" in serve_methods, "`/attachments/{id}` 는 GET 서빙을 노출해야 한다"
    assert not (serve_methods & {"PUT", "PATCH", "DELETE"}), (
        f"`/attachments/{{id}}` 는 상태를 바꾸는(un-archive) 메서드를 노출하면 안 된다: {serve_methods}"
    )

    # (`/documents/{id}/attachments` 는 POST 업로드만)
    upload_methods = attachment_routes["/documents/{id}/attachments"]
    assert "POST" in upload_methods, "`/documents/{id}/attachments` 는 POST 업로드를 노출해야 한다"
    assert not (upload_methods & {"PUT", "PATCH", "DELETE"}), (
        f"업로드 경로는 un-archive 성 메서드를 노출하면 안 된다: {upload_methods}"
    )

    # (반복 조회 404) 복원 경로가 없으므로 보관 첨부는 반복 조회에도 어떤 role 로도 되살아나지
    # 않고 계속 404 다(2회 반복해 관측).
    for role_name, client in (
        ("viewer", scenario.viewer_client),
        ("editor", scenario.editor_client),
        ("owner", scenario.owner_client),
        ("admin", scenario.admin_client),
    ):
        for attempt in range(2):
            resp = h.attempt_get_attachment(client, att_id)
            assert resp.status_code == 404, (
                f"{role_name} 세션의 {attempt + 1}번째 조회도 404 여야 한다(복원 불가, INV-7): "
                f"{resp.status_code} {resp.text}"
            )


# =============================================================================
# 5) 단조 증가 — 반복 스윕 후에도 보관 파일이 자동 정리·삭제되지 않고 존속 (Req 6.5, 8.11)
# =============================================================================


def test_repeated_sweeps_do_not_auto_clean_archived_file(
    doc_tree_scenario, harness, archival_sweep, tmp_attachment_roots
):
    """반복 스윕 후에도 보관 파일이 자동 정리·삭제되지 않고 존속함을 검증한다(Req 6.5, 8.11 —
    단조 증가 수용, 자동 정리 부재).

    첫 스윕으로 보관 처리한 뒤, 아카이브 스윕을 여러 번 더 실행해도(이미 보관된 첨부는 스코프
    에서 제외되어 처리 0) 보관 파일이 삭제되지 않고 원본 바이트로 존속하며 DB `file_path`·
    `is_archived` 도 불변임을 확인한다. 애플리케이션은 보관 폴더를 자동 정리하지 않는다.
    """
    ws_id = doc_tree_scenario.workspace_id
    scenario = doc_tree_scenario.scenario

    att_id, archived_rel_path = _archive_file_attachment(
        scenario, harness, archival_sweep, doc_tree_scenario.root_id, ws_id
    )

    # 첫 스윕 이후 보관 파일 스냅샷(단조 증가 대조 기준).
    archived_file = h.assert_archived(tmp_attachment_roots, archived_rel_path)
    assert archived_file.read_bytes() == _FILE_BYTES

    # 아카이브 스윕을 2회 더 반복 — 이미 보관된 첨부는 스코프 제외로 처리 0(재이동·자동 정리
    # 없음). 매 반복 후 보관 파일이 원본 바이트로 존속하고 DB 상태가 불변임을 확인한다.
    for iteration in range(2):
        processed = h.run_archival_sweep(archival_sweep, _NOW)
        assert processed == 0, (
            f"이미 보관된 첨부는 스코프 제외로 반복 스윕이 0 을 반환해야 한다(자동 정리 없음): "
            f"iteration={iteration + 1} processed={processed}"
        )

        # 보관 파일이 삭제되지 않고 원본 바이트로 존속(자동 정리 부재, 단조 증가 수용).
        still = h.assert_archived(tmp_attachment_roots, archived_rel_path)
        assert still.read_bytes() == _FILE_BYTES, (
            f"반복 스윕 후에도 보관 파일은 삭제되지 않고 원본 바이트로 존속해야 한다: "
            f"iteration={iteration + 1}"
        )

        # DB 부수효과 불변: file_path·is_archived 가 반복 스윕에 바뀌지 않는다.
        assert h.attachment_file_path(harness.session_local, att_id) == archived_rel_path, (
            "반복 스윕은 보관 첨부의 file_path 를 바꾸면 안 된다(단조 증가·불변)"
        )
        assert h.attachment_is_archived(harness.session_local, att_id) is True, (
            "반복 스윕 후에도 첨부는 보관 상태(is_archived=true)로 유지되어야 한다"
        )
