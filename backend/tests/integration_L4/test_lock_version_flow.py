"""잠금·버전 흐름 스위트 — s09 편집 잠금 생명주기 + 저장 시 버전 생성 + role 게이팅 e2e
(Task 2.2 / Req 3.1·3.2·3.3·3.4·3.5·3.6·3.7, design §LockVersionFlowSuite; s09 5.2~5.7 교차참조).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕**s09**⊕s10) + **실제 세션 쿠키** 위에서
s09 잠금·버전 5개 라우트(카탈로그 행 24~28)를 mock 없이 결합 검증한다. 판정은 s05 가 채운 실제
`workspace_member` 데이터 위에서 s01 `require_ws_role` resolver 가 수행하고, `/documents/{id}/*`
는 s07 문서→WS 어댑터가 문서 id 로 workspace_id 를 추출해 위임한다. 게이트·엔진·잠금 서비스가
오작동하면 단언을 약화시키지 않고 실제 회귀를 그대로 표면화한다.

INV-9(문서당 잠금 최대 1인)를 관찰하기 위해 `lock_scenario`(L4 conftest) 가 제공하는 **동일
워크스페이스의 두 EDITOR(A·B)** + owner/viewer/비멤버/admin 세션을 그대로 쓴다. 문서는 editor A
세션으로 실제 라우트(`l3_helpers.create_document`)로 생성한다. 저장 원자 결과(새 버전 +
`current_version_id` 갱신 + 잠금 해제)와 타임아웃 없음(3.5)은 부팅 앱과 **동일 세션 팩토리**
(`harness.session_local`)로 DB 행을 직접 관측·시드해 결정적으로 검증한다(테스트 관찰/시드이며
잠금·저장 전이 자체는 실제 s09 서비스가 수행한다 — mock 아님).

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다.
"""

from datetime import datetime, timedelta

from app.models import Document
from tests.integration_L4 import helpers as h

l3_helpers = h.l3_helpers

# 인증되었으나 대상 문서가 존재하지 않을 때 어댑터 매핑-실패(→404)를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999


def _make_document(lock_scenario, title: str) -> int:
    """editor A 세션으로 대상 워크스페이스에 문서를 만들고 문서 id 를 반환한다(setup)."""
    doc = l3_helpers.create_document(
        lock_scenario.editor_a_client, lock_scenario.workspace_id, title
    )
    return doc["id"]


def _current_version_id(harness, document_id: int) -> int | None:
    """부팅 앱과 동일 세션으로 문서 행의 ``current_version_id`` 를 직접 관측한다(신규 세션)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        assert doc is not None, f"관측 대상 문서가 있어야 한다: id={document_id}"
        return doc.current_version_id


# =============================================================================
# 1) 시작·타인 차단 409 — 문서당 잠금 최대 1인 (3.1, INV-9, s09 5.2)
# =============================================================================


def test_lock_conflict_enforces_at_most_one_holder(lock_scenario):
    """A `POST /lock` 200 → B `POST /lock` 409("편집 중"); 문서당 잠금 보유자 최대 1인(INV-9).

    두 editor(A·B)는 동일 워크스페이스의 서로 다른 EDITOR 멤버다(권한은 동등). B 의 409 는
    권한 실패가 아니라 A 가 이미 보유한 잠금과의 **충돌**이며, 잠금 판정은 `lock_user_id` 단일
    컬럼(INV-9)이 강제한다. A 의 잠금 응답은 요청자·획득 시각을 담은 `DocumentLockRead`.
    """
    doc_id = _make_document(lock_scenario, "INV9-충돌")
    assert lock_scenario.editor_a_user_id != lock_scenario.editor_b_user_id, (
        "두 editor 는 서로 다른 사용자여야 한다(INV-9 충돌 관측)"
    )

    lock_a = h.attempt_lock(lock_scenario.editor_a_client, doc_id)
    assert lock_a.status_code == 200, (
        f"editor A 잠금 획득 200 이어야 한다(3.1): {lock_a.status_code} {lock_a.text}"
    )
    body = lock_a.json()
    assert body["document_id"] == doc_id, "잠금 응답 document_id 는 대상 문서여야 한다"
    assert body["lock_user_id"] == lock_scenario.editor_a_user_id, (
        "잠금 보유자는 요청자 A 여야 한다(INV-9 단일 근거)"
    )
    assert body["lock_acquired_at"], "획득 시각(lock_acquired_at)이 기록되어야 한다(3.1)"

    # B 는 동등한 EDITOR 지만, A 가 보유 중인 잠금과 충돌하므로 403(권한)이 아니라 409.
    conflict = h.attempt_lock(lock_scenario.editor_b_client, doc_id)
    assert conflict.status_code == 409, (
        f"타인 잠금 문서는 409(편집 중)여야 한다(3.1, INV-9): "
        f"{conflict.status_code} {conflict.text}"
    )


# =============================================================================
# 2) 저장 = 새 버전 + current 갱신 + 잠금 해제의 원자 결과 (3.2, s09 5.3)
# =============================================================================


def test_save_creates_version_updates_current_and_releases_lock(lock_scenario, harness):
    """A 저장 → 새 `document_version` 생성·`current_version_id` 갱신·잠금 해제 → B `POST /lock` 200.

    저장은 (버전 생성 + current 갱신 + 잠금 해제) 세 효과의 원자 결과다. 새 버전 id 가
    `current_version_id` 로 승격됨을 부팅 앱과 동일 세션으로 DB 관측하고, 저장된 본문이 s07
    `GET /documents/{id}` 로 현재 본문으로 노출됨을 관측하며, 해제되었으므로 B 가 이어서 잠글
    수 있음(INV-9 이전 가능)을 확인한다. 저장 응답은 본문 없는 `DocumentVersionRead`.
    """
    doc_id = _make_document(lock_scenario, "저장원자")
    editor_a = lock_scenario.editor_a_client

    before_current = _current_version_id(harness, doc_id)
    assert before_current is None, "저장 전에는 current_version_id 가 없어야 한다"

    h.lock(editor_a, doc_id)
    version = h.save(editor_a, doc_id, "# hello")
    assert isinstance(version["id"], int) and version["id"] > 0, "새 버전 식별자가 있어야 한다"
    assert version["document_id"] == doc_id, "버전은 대상 문서에 속해야 한다"
    assert version["created_by"] == lock_scenario.editor_a_user_id, (
        "저장자(created_by)는 요청자 A 여야 한다(3.2)"
    )
    assert "content" not in version, (
        "DocumentVersionRead 는 본문(content)을 노출하지 않는다(메타데이터 전용)"
    )

    # current_version_id 가 방금 생성된 버전으로 갱신되어야 한다(원자 결과, DB 관측).
    after_current = _current_version_id(harness, doc_id)
    assert after_current == version["id"], (
        "저장 후 current_version_id 가 새 버전으로 갱신되어야 한다(3.2, 원자 결과)"
    )

    # 저장된 본문이 s07 현재 본문으로 노출된다(current_version 갱신 관측).
    got = l3_helpers.get_document(editor_a, doc_id)
    assert got["content"] == "# hello", "저장 후 현재 본문이 새 버전으로 갱신되어야 한다(3.2)"

    # 저장이 잠금을 해제했으므로 B 가 이어서 잠글 수 있다(INV-9 이전 가능).
    lock_b = h.attempt_lock(lock_scenario.editor_b_client, doc_id)
    assert lock_b.status_code == 200, (
        f"저장으로 해제된 뒤 editor B 잠금 획득은 200 이어야 한다(3.2, INV-9 이전): "
        f"{lock_b.status_code} {lock_b.text}"
    )
    assert lock_b.json()["lock_user_id"] == lock_scenario.editor_b_user_id, (
        "이전된 잠금 보유자는 B 여야 한다(INV-9 최대 1인)"
    )


# =============================================================================
# 3) 취소 = 잠금 해제 + 버전 미생성 + 목록 불변 (3.3, s09 5.4)
# =============================================================================


def test_cancel_releases_lock_without_new_version(lock_scenario):
    """A 저장으로 버전 1개 확보 → A 재잠금 후 `POST /cancel` → 잠금 해제·새 버전 미생성·목록 불변.

    취소는 미저장 변경분을 폐기하고 잠금만 푼다. 재잠금→취소 전후 버전 `total` 이 동일하고,
    취소로 해제되었으므로 A 가 다시 잠글 수 있음(취소가 실제로 잠금을 풀었음)을 확인한다.
    """
    doc_id = _make_document(lock_scenario, "취소폐기")
    editor_a = lock_scenario.editor_a_client

    # 버전 1개 확보(재잠금 대상 baseline).
    h.lock(editor_a, doc_id)
    h.save(editor_a, doc_id, "본문v1")
    before = h.list_versions(editor_a, doc_id)["total"]
    assert before == 1, "저장 1회 후 버전은 1개여야 한다(baseline)"

    # A 재잠금 후 취소 → 잠금 해제·새 버전 미생성.
    h.lock(editor_a, doc_id)
    cancel = h.attempt_cancel(editor_a, doc_id)
    assert cancel.status_code == 204, (
        f"취소는 204 여야 한다(잠금 해제, 3.3): {cancel.status_code} {cancel.text}"
    )

    after = h.list_versions(editor_a, doc_id)["total"]
    assert after == before, "취소는 어떤 버전도 만들지 않는다(버전 목록 불변, 3.3)"

    # 취소로 해제되었으므로 A 가 다시 잠글 수 있다(취소가 실제 잠금을 풀었음).
    relock = h.attempt_lock(editor_a, doc_id)
    assert relock.status_code == 200, (
        f"취소로 해제된 뒤 A 재잠금 200 이어야 한다(잠금이 실제로 풀렸음): "
        f"{relock.status_code} {relock.text}"
    )


# =============================================================================
# 4) 강제해제 = owner/admin 통과·editor(비 owner) 403·버전 미생성 (3.4, s09 5.6)
# =============================================================================


def test_force_unlock_owner_admin_succeed_editor_denied_no_version(lock_scenario):
    """A 잠금 → editor(비 owner) force-unlock 403 → owner 204 → (재잠금) admin 204; 버전 미생성.

    강제 해제는 OWNER 이상만 통과한다. editor B 는 EDITOR 지만 OWNER 미만이라 403. owner 는
    A 의 잠금을 강제 해제하고, 비멤버 admin 은 bypass(INV-3)로 통과한다. 강제 해제는 어떤
    버전도 만들지 않으므로 전 과정에서 버전 `total` 이 0 으로 불변임을 확인한다.
    """
    doc_id = _make_document(lock_scenario, "강제해제")
    editor_a = lock_scenario.editor_a_client
    editor_b = lock_scenario.editor_b_client

    before = h.list_versions(editor_a, doc_id)["total"]
    assert before == 0, "저장 전 버전은 0 개여야 한다(baseline)"

    # A 가 잠근다.
    h.lock(editor_a, doc_id)

    # editor B(비 owner) 의 강제 해제는 OWNER 미만이라 403(게이트 판정, 3.4).
    denied = h.attempt_force_unlock(editor_b, doc_id)
    assert denied.status_code == 403, (
        f"editor(비 owner) force-unlock 은 403 이어야 한다(3.4): "
        f"{denied.status_code} {denied.text}"
    )

    # owner 가 A 의 잠금을 강제 해제한다(204, 보유자 무관).
    owner_fu = h.attempt_force_unlock(lock_scenario.owner_client, doc_id)
    assert owner_fu.status_code == 204, (
        f"owner force-unlock 은 204 여야 한다(3.4): {owner_fu.status_code} {owner_fu.text}"
    )

    # 다시 A 가 잠그고, 비멤버 admin 이 bypass(INV-3)로 강제 해제한다(204).
    h.lock(editor_a, doc_id)
    admin_fu = h.attempt_force_unlock(lock_scenario.admin_client, doc_id)
    assert admin_fu.status_code == 204, (
        f"admin force-unlock 은 bypass 로 204 여야 한다(3.4, INV-3): "
        f"{admin_fu.status_code} {admin_fu.text}"
    )

    # 강제 해제는 어떤 버전도 만들지 않는다(버전 미생성, 3.4).
    after = h.list_versions(editor_a, doc_id)["total"]
    assert after == before, "강제 해제는 어떤 버전도 만들지 않는다(3.4)"

    # 강제 해제로 풀렸으므로 A 가 다시 잠글 수 있다(잠금이 실제로 풀렸음).
    relock = h.attempt_lock(editor_a, doc_id)
    assert relock.status_code == 200, (
        f"강제 해제 뒤 A 재잠금 200 이어야 한다: {relock.status_code} {relock.text}"
    )


# =============================================================================
# 5) 타임아웃 없음 — 시간 경과만으로 해제되지 않음 (3.5, s09 5.5)
# =============================================================================


def test_lock_has_no_auto_timeout(lock_scenario, harness):
    """잠금 획득 후 `lock_acquired_at` 을 과거로 진행시켜도 잠금 유지; 명시적 해제로만 해제.

    자동 타임아웃이 없음을 결정적으로 검증하려면 시간 진행을 시뮬레이션한다: A 가 잠근 뒤 부팅
    앱과 동일 세션으로 `lock_acquired_at` 을 1년 전으로 덮어쓴다(테스트 시드). 그럼에도 (a) 잠금
    보유자는 여전히 A 이고, (b) B 의 잠금은 여전히 409("편집 중")이며, (c) 오직 명시적 취소로만
    잠금이 풀려 A 가 재잠금할 수 있음을 확인한다(시간 경과 무해제, 명시적 해제만).
    """
    doc_id = _make_document(lock_scenario, "타임아웃없음")
    editor_a = lock_scenario.editor_a_client

    lock_body = h.lock(editor_a, doc_id)
    assert lock_body["lock_user_id"] == lock_scenario.editor_a_user_id

    # 시간 진행 시뮬레이션: 획득 시각을 1년 전으로 덮어쓴다(마이크로초 0, DATETIME 정합).
    stale = (datetime.utcnow() - timedelta(days=365)).replace(microsecond=0)
    with harness.session_local() as db:
        doc = db.get(Document, doc_id)
        assert doc is not None, "잠금 대상 문서가 있어야 한다"
        assert doc.lock_user_id == lock_scenario.editor_a_user_id, "잠금 보유자는 A 여야 한다"
        doc.lock_acquired_at = stale
        db.commit()

    # (a) 오랜 시간이 지나도 잠금 보유자는 여전히 A 다(자동 만료 없음).
    with harness.session_local() as db:
        doc = db.get(Document, doc_id)
        assert doc.lock_user_id == lock_scenario.editor_a_user_id, (
            "시간 경과만으로 잠금 보유자가 사라지지 않아야 한다(3.5, 타임아웃 없음)"
        )

    # (b) B 의 잠금은 여전히 409(잠금이 유효하게 유지됨).
    still_conflict = h.attempt_lock(lock_scenario.editor_b_client, doc_id)
    assert still_conflict.status_code == 409, (
        f"오래된 잠금도 여전히 유효해 B 는 409 여야 한다(3.5): "
        f"{still_conflict.status_code} {still_conflict.text}"
    )

    # (c) 명시적 해제(취소)로만 잠금이 풀린다 — 취소 후 B 가 잠글 수 있다.
    h.cancel(editor_a, doc_id)
    released = h.attempt_lock(lock_scenario.editor_b_client, doc_id)
    assert released.status_code == 200, (
        f"명시적 취소 뒤에는 B 가 잠글 수 있어야 한다(명시적 해제만, 3.5): "
        f"{released.status_code} {released.text}"
    )


# =============================================================================
# 6) 버전 무한 누적·최신순 메타데이터·rollback/과거 본문 경로 부재 (3.6, s09 5.7)
# =============================================================================


def test_versions_accumulate_newest_first_no_rollback(lock_scenario):
    """여러 번 저장 → 버전 누적(기존 삭제·수정 없음)·`GET /versions` 최신순 메타데이터·rollback 없음.

    A 가 같은 문서를 세 번 저장하면 버전 3개가 누적된다(무한 보관). 목록은 최신 저장 순
    (created_at 내림차순, id 내림차순)이고 각 항목은 본문(content) 없는 메타데이터뿐이다. 이전
    저장에서 관측한 버전 id 가 이후에도 그대로 존재해(삭제·수정 없음), 과거 본문 조회·rollback
    경로가 없음을 스키마 형태로 확인한다.
    """
    doc_id = _make_document(lock_scenario, "버전누적")
    editor_a = lock_scenario.editor_a_client

    version_ids = []
    for i in range(3):
        h.lock(editor_a, doc_id)
        v = h.save(editor_a, doc_id, f"본문v{i}")
        version_ids.append(v["id"])

    page = h.list_versions(editor_a, doc_id)
    assert page["total"] == 3, "세 번 저장 시 버전 3개가 누적되어야 한다(무한 보관, 3.6)"
    items = page["items"]
    assert len(items) == 3, "목록 항목도 3개여야 한다"

    # 기존 버전이 삭제·수정되지 않고 모두 보존된다(3.6).
    listed_ids = [item["id"] for item in items]
    assert set(listed_ids) == set(version_ids), (
        "저장한 모든 버전 id 가 목록에 그대로 보존되어야 한다(삭제·수정 없음, 3.6)"
    )

    # 최신 저장 순(created_at 내림차순; 동시각 tie 는 id 내림차순)이어야 한다(3.6).
    created_ats = [item["created_at"] for item in items]
    assert created_ats == sorted(created_ats, reverse=True), (
        "버전 목록은 최신 저장 순이어야 한다(created_at 내림차순, 3.6)"
    )
    for a, b in zip(items, items[1:]):
        if a["created_at"] == b["created_at"]:
            assert a["id"] > b["id"], "동일 저장 시각 tie 는 id 내림차순이어야 한다"

    # 각 항목은 본문(content) 없는 메타데이터뿐 — rollback/과거 본문 조회 경로 부재(3.6).
    for item in items:
        assert "content" not in item, (
            "버전 항목은 본문을 노출하지 않는다(rollback·과거 본문 경로 부재, 3.6)"
        )
        assert set(item.keys()) == {"id", "document_id", "created_by", "created_at"}, (
            "DocumentVersionRead 는 식별자·저장자·저장 시각 메타데이터만 노출한다(3.6)"
        )


# =============================================================================
# 7) role 게이팅 — 실제 s05 멤버십 위에서 라우트 경계·admin bypass·어댑터 404 (3.7, INV-1·2·3)
# =============================================================================


def test_role_gating_over_real_membership(lock_scenario):
    """lock/save/cancel=EDITOR(viewer·비멤버 403)·force-unlock=OWNER(editor 403)·versions=VIEWER
    (비멤버 403)·admin bypass·미존재 문서 404 를 실제 s05 멤버십 위에서 e2e 검증(INV-1·2·3).

    판정은 s05 가 채운 `workspace_member` 데이터 위에서 s01 `require_ws_role` resolver 가 수행하고
    `/documents/{id}/*` 는 s07 문서→WS 어댑터로 게이트된다. 문서가 미잠금인 동안 게이트를 관찰해
    잠금 충돌(409)과 권한 거부(403)를 혼동하지 않는다(거부는 충돌 이전에 판정).
    """
    doc_id = _make_document(lock_scenario, "게이팅")
    viewer = lock_scenario.viewer_client
    nonmember = lock_scenario.nonmember_client
    admin = lock_scenario.admin_client
    editor_a = lock_scenario.editor_a_client

    # (lock/save/cancel = EDITOR) viewer·비멤버는 403(INV-1·2). 미잠금 상태라 충돌 아님.
    for actor, label in ((viewer, "viewer"), (nonmember, "비멤버")):
        assert h.attempt_lock(actor, doc_id).status_code == 403, f"{label} lock 403(3.7)"
        assert h.attempt_save(actor, doc_id, "x").status_code == 403, f"{label} save 403(3.7)"
        assert h.attempt_cancel(actor, doc_id).status_code == 403, f"{label} cancel 403(3.7)"

    # (force-unlock = OWNER) editor(비 owner)는 OWNER 미만이라 403(3.7).
    assert h.attempt_force_unlock(editor_a, doc_id).status_code == 403, (
        "editor(비 owner) force-unlock 403(3.7, OWNER 게이트)"
    )
    # viewer·비멤버도 force-unlock 403.
    assert h.attempt_force_unlock(viewer, doc_id).status_code == 403, "viewer force-unlock 403(3.7)"
    assert h.attempt_force_unlock(nonmember, doc_id).status_code == 403, "비멤버 force-unlock 403(3.7)"

    # (versions = 읽기 전역 개방) viewer·비멤버 모두 200(s26 Req 3.3·3.8 — 더 이상 403 아님).
    assert h.attempt_list_versions(viewer, doc_id).status_code == 200, "viewer versions 200(3.8)"
    assert h.attempt_list_versions(nonmember, doc_id).status_code == 200, (
        "비멤버 versions 읽기 개방으로 200(3.8, 403 아님)"
    )

    # (admin bypass, INV-3) 비멤버 admin 이 모든 라우트를 bypass 한다.
    assert h.attempt_list_versions(admin, doc_id).status_code == 200, "admin versions bypass(INV-3)"
    assert h.attempt_lock(admin, doc_id).status_code == 200, "admin lock bypass(INV-3)"
    assert h.attempt_save(admin, doc_id, "adminbody").status_code == 200, "admin save bypass(INV-3)"
    # save 로 해제된 뒤 admin 이 다시 잠그고 force-unlock 까지 bypass(OWNER 게이트도 통과).
    assert h.attempt_lock(admin, doc_id).status_code == 200, "admin re-lock bypass(INV-3)"
    assert h.attempt_force_unlock(admin, doc_id).status_code == 204, "admin force-unlock bypass(INV-3)"
    assert h.attempt_cancel(admin, doc_id).status_code == 204, "admin cancel bypass(멱등 no-op, INV-3)"

    # (어댑터 404) 미존재 문서는 fully-authorized owner 에게도 404(role 판정 이전, 3.7).
    owner = lock_scenario.owner_client
    assert h.attempt_lock(owner, MISSING_DOCUMENT_ID).status_code == 404, (
        "미존재 문서 lock 은 authorized owner 에게도 404 여야 한다(어댑터 매핑 실패, 3.7)"
    )
    assert h.attempt_save(owner, MISSING_DOCUMENT_ID, "x").status_code == 404, (
        "미존재 문서 save 도 404 여야 한다(3.7)"
    )
    assert h.attempt_list_versions(owner, MISSING_DOCUMENT_ID).status_code == 404, (
        "미존재 문서 versions 도 404 여야 한다(3.7)"
    )
