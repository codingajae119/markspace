"""아래 계층 결합 엣지 스위트 — role별 접근 경계·admin override·작성자 보존·물리삭제 부재
(Task 2.6 / Req 7.1·7.2·7.3, design §CombinationLayerEdgeSuite; INV-1·2·3·4 교차참조).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10) + **실제 세션 쿠키** 위에서, 잠금·
버전·휴지통 도메인이 **아래 계층 결합**(s02 세션 인증 ↔ s03 계정 생명주기 ↔ s05 워크스페이스
멤버십)과 맞물리는 세 경계를 mock 없이 검증한다. 판정은 s05 가 채운 실제 `workspace_member`
데이터 위에서 s01 `require_ws_role` resolver 가 수행하고, 계정 상태(삭제)는 s03 `PATCH
/admin/users/{id}` 로 전이하며, 세션 게이트는 s01 `get_current_user`(요청마다 `is_deleted`
재검사, `app/common/auth.py`)가 강제한다 — 어떤 것도 시뮬레이션하지 않는다.

## 세 시나리오 (Req 매핑)
1. **role별 접근 경계·admin override**(7.1, INV-1·2·3): owner/editor/viewer/비멤버/admin 세션으로
   잠금·버전·휴지통 라우트 접근 경계를 관찰 — viewer 는 잠금·저장·취소·강제해제·휴지통 변경
   거부(403, INV-2), 비멤버는 차단(403, INV-1), 비멤버 admin 은 전면 접근(INV-3). 이 경계가
   아래 계층(s02 세션·s05 멤버십) 결합 **위에서** 성립함을 실 세션 쿠키로 e2e 관찰한다.
2. **작성자 보존·로그인 게이트**(7.2, INV-4): 문서와 `document_version` 을 만든 사용자
   (`created_by`)를 admin 이 삭제(`is_deleted=true`) 처리한 뒤, 그 문서·버전의 `created_by`
   참조와 사용자 `name` 이 물리 삭제 없이 DB 에 보존됨을 직접 조회로 확인하고, 삭제된 사용자의
   잠금·저장 후속 요청이 로그인 게이트(401)로 차단됨을 관찰한다(s02 세션 게이트가 요청마다
   `is_deleted` 재검사).
3. **물리 삭제 부재**(7.3, INV-4): 잠금·저장·취소·강제해제·복구·완전삭제·보관 스윕을 섞은
   대표 시나리오 전반에서 `document`·`document_version`·`user` 레코드가 물리적으로 삭제되지
   않았음(완전삭제·자동삭제는 status 전환만)을 조작 전후 raw `SELECT` 로 확인한다.

## 재검증 트리거 (design §Revalidation Triggers)
`s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10` 중 하나라도 수정되면 이 스위트(및 로드맵상 그 이후
모든 체크포인트)를 누적 집합 기준으로 재실행한다. 특히 여기서 관측하는 role 게이팅(`require_ws_role`
·admin bypass)·삭제 사용자 `created_by`/`name` 보존·세션 `is_deleted` 재검사(401)·물리 삭제
부재(INV-4)는 s01 계약과 s02·s03·s05·s07·s09·s10 구현 결합에 직접 의존한다.

계정 상태 전이 헬퍼는 s08 L3(→L2→L1) 헬퍼를 재사용한다(중복 정의 금지): 사용자 생성·삭제
전이는 `l1_helpers.create_user`/`l1_helpers.set_deleted`, 멤버 추가는 `l2_helpers.add_member`,
문서·삭제·복구·완전삭제는 L3(및 L4 라우트 래퍼). 작성자·물리 삭제 관찰은 부팅 앱과 동일 세션
팩토리(`harness.session_local`)의 raw `SELECT` 다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드·conftest·helpers·하위 하네스는 건드리지
않고 재사용만 한다.
"""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import bindparam, func, select, text

from app.models import User
from tests.integration_L4 import helpers as h

l3_helpers = h.l3_helpers
l2_helpers = h.l2_helpers
l1_helpers = h.l1_helpers

# 인증되었으나 대상 문서가 존재하지 않을 때 어댑터 매핑-실패(→404)를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999


def _title(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


# --- raw SELECT 관찰 헬퍼 (물리 존재·작성자 보존 단언용, 특정 id 만 조회) --------------------


def _fetch_document(harness, document_id: int):
    """document 테이블에서 한 문서 행을 직접 조회한다(없으면 None — 물리 삭제 관측용).

    반환 Row 는 (id, status, created_by, lock_user_id, trashed_at). 물리 보존(INV-4)·작성자
    참조(`created_by`) 보존을 실제 DB 로 확인하는 데 쓴다.
    """
    stmt = text(
        "SELECT id, status, created_by, lock_user_id, trashed_at "
        "FROM document WHERE id = :id"
    )
    with harness.session_local() as db:
        return db.execute(stmt, {"id": document_id}).first()


def _fetch_version(harness, version_id: int):
    """document_version 테이블에서 한 버전 행을 직접 조회한다(없으면 None — 물리 삭제 관측용).

    반환 Row 는 (id, document_id, created_by). 저장으로 생성된 버전의 작성자(`created_by`)
    참조가 작성자 삭제 후에도 보존됨(7.2)·물리 삭제 부재(7.3)를 확인하는 데 쓴다.
    """
    stmt = text(
        "SELECT id, document_id, created_by FROM document_version WHERE id = :id"
    )
    with harness.session_local() as db:
        return db.execute(stmt, {"id": version_id}).first()


def _fetch_user(harness, user_id: int):
    """user 테이블에서 한 사용자 행을 직접 조회한다(없으면 None — 물리 삭제 관측용).

    반환 Row 는 (id, name, is_deleted). 삭제(`is_deleted=true`) 처리된 작성자의 이름이 물리
    보존됨(7.2, INV-4)을 확인하는 데 쓴다.
    """
    stmt = text("SELECT id, name, is_deleted FROM user WHERE id = :id")
    with harness.session_local() as db:
        return db.execute(stmt, {"id": user_id}).first()


def _version_ids_for(harness, document_ids):
    """주어진 문서 id 들에 대한 document_version 행 id 집합을 직접 조회한다(물리 삭제 부재 비교 기준)."""
    stmt = text(
        "SELECT id FROM document_version WHERE document_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with harness.session_local() as db:
        rows = db.execute(stmt, {"ids": list(document_ids)}).all()
    return {int(row[0]) for row in rows}


def _user_count(harness) -> int:
    """DB 수준 `SELECT COUNT(*) FROM user` 로 커밋된 user 행 수를 직접 센다(물리 삭제 부재 판정)."""
    with harness.session_local() as db:
        return int(db.scalar(select(func.count()).select_from(User)))


def _provision_member(scenario, harness, *, role: str, prefix: str, name: str | None = None):
    """admin 이 사용자를 만들고 owner 가 지정 role 로 멤버 추가한 뒤 그 자격으로 로그인한다(setup).

    아래 계층 결합(s03 계정 생성 → s05 멤버십 추가 → s02 로그인 세션)을 실제 라우트로 밟아
    (user_id, name, 인증 client)를 반환한다. client 는 자신의 세션 쿠키를 유지한다. mock 없음.
    """
    author_name = name if name is not None else prefix
    login_id = l1_helpers.unique_login_id(prefix)
    user_id = l1_helpers.create_user(
        scenario.admin_client, login_id, l1_helpers.DEFAULT_PASSWORD, name=author_name
    )
    l2_helpers.add_member(scenario.owner_client, scenario.workspace_id, user_id, role)
    client = harness.login(login_id, l1_helpers.DEFAULT_PASSWORD)
    return user_id, author_name, client


# =============================================================================
# 1) role별 접근 경계·admin override — 잠금·버전 라우트 (Req 7.1, INV-1·2·3)
# =============================================================================


def test_role_access_boundaries_on_lock_version_routes(lock_scenario):
    """viewer/비멤버는 잠금·저장·취소·강제해제 거부(403), admin 은 전면 bypass(INV-1·2·3).

    아래 계층 결합(s02 세션·s05 멤버십) 위에서 s09 잠금·버전 라우트의 접근 경계를 관찰한다.
    문서는 editor A 세션(실제 라우트)으로 만들고, 문서가 미잠금인 동안 게이트를 관찰해 잠금
    충돌(409)과 권한 거부(403)를 혼동하지 않는다(거부는 충돌 이전에 판정):

    - **viewer**(멤버·읽기전용): 잠금·저장·취소·강제해제 모두 403(INV-2). versions 는 VIEWER+
      이므로 200(읽기 경계 구분).
    - **비멤버**: 동일 라우트 모두 403(INV-1). versions 도 403.
    - **admin**(비멤버): 모든 라우트 bypass(INV-3) — versions 200·lock 200·save 200·재잠금 후
      force-unlock 204.
    """
    doc_id = l3_helpers.create_document(
        lock_scenario.editor_a_client, lock_scenario.workspace_id, _title("경계잠금")
    )["id"]

    viewer = lock_scenario.viewer_client
    nonmember = lock_scenario.nonmember_client
    admin = lock_scenario.admin_client

    # viewer·비멤버: 변경 계열(lock/save/cancel/force-unlock) 모두 403(INV-2/1).
    for label, actor in (("viewer", viewer), ("nonmember", nonmember)):
        assert h.attempt_lock(actor, doc_id).status_code == 403, f"{label} lock 403(7.1)"
        assert h.attempt_save(actor, doc_id, "x").status_code == 403, f"{label} save 403(7.1)"
        assert h.attempt_cancel(actor, doc_id).status_code == 403, f"{label} cancel 403(7.1)"
        assert h.attempt_force_unlock(actor, doc_id).status_code == 403, (
            f"{label} force-unlock 403(7.1)"
        )

    # versions 는 읽기 전역 개방 — viewer·비멤버 모두 200(s26 Req 3.3·3.8, 더 이상 403 아님).
    assert h.attempt_list_versions(viewer, doc_id).status_code == 200, "viewer versions 200(3.8)"
    assert h.attempt_list_versions(nonmember, doc_id).status_code == 200, (
        "비멤버 versions 읽기 개방으로 200(3.8, 403 아님)"
    )

    # admin(비멤버) 은 모든 라우트를 bypass 한다(INV-3).
    assert h.attempt_list_versions(admin, doc_id).status_code == 200, "admin versions bypass(INV-3)"
    assert h.attempt_lock(admin, doc_id).status_code == 200, "admin lock bypass(INV-3)"
    assert h.attempt_save(admin, doc_id, "adminbody").status_code == 200, "admin save bypass(INV-3)"
    assert h.attempt_lock(admin, doc_id).status_code == 200, "admin re-lock bypass(INV-3)"
    assert h.attempt_force_unlock(admin, doc_id).status_code == 204, (
        "admin force-unlock bypass(INV-3)"
    )


def test_role_access_boundaries_and_admin_override_on_trash_routes(trash_scenario):
    """viewer/비멤버는 휴지통 목록·복구·완전삭제 거부(403), 비멤버 admin 은 전면 접근(INV-1·2·3).

    editor 가 삭제한 독립 묶음 2개(손자·루트+자식)가 있는 상태에서, 아래 계층 결합(s02 세션·s05
    멤버십) 위에서 s10 휴지통 라우트의 접근 경계를 관찰한다:

    - **viewer·비멤버**: 목록·복구·완전삭제 모두 403(INV-2/1), 거부 후 묶음 상태 불변.
    - **admin**(이 워크스페이스의 **비멤버**): 목록 200·복구 204·완전삭제 204 로 전면 bypass
      (INV-3), 실제 전이(active/deleted)가 DB 로 확인된다.
    """
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    grandchild_id = trash_scenario.grandchild_id

    # viewer·비멤버: 목록·복구·완전삭제 모두 403(INV-2/1).
    for label, client in (
        ("viewer", trash_scenario.scenario.viewer_client),
        ("nonmember", trash_scenario.scenario.nonmember_client),
    ):
        assert h.attempt_list_trash(client, ws_id).status_code == 403, f"{label} 휴지통 목록 403(7.1)"
        assert h.attempt_restore_bundle(client, root_id).status_code == 403, (
            f"{label} 묶음 복구 403(7.1)"
        )
        assert h.attempt_purge_bundle(client, grandchild_id).status_code == 403, (
            f"{label} 묶음 완전삭제 403(7.1)"
        )

    # 거부는 상태를 바꾸지 않는다 — 두 묶음 모두 여전히 trashed.
    assert trash_scenario.status_of(root_id) == "trashed", "거부된 복구는 상태를 바꾸지 않아야 한다(7.1)"
    assert trash_scenario.status_of(grandchild_id) == "trashed", (
        "거부된 완전삭제는 상태를 바꾸지 않아야 한다(7.1)"
    )

    # admin(비멤버) 은 전면 bypass — 목록 200·복구 204·완전삭제 204 (INV-3).
    admin = trash_scenario.scenario.admin_client
    assert h.attempt_list_trash(admin, ws_id).status_code == 200, "admin 휴지통 목록 bypass(INV-3)"
    assert h.attempt_restore_bundle(admin, grandchild_id).status_code == 204, (
        "admin 묶음 복구 bypass(INV-3)"
    )
    assert h.attempt_purge_bundle(admin, root_id).status_code == 204, (
        "admin 묶음 완전삭제 bypass(INV-3)"
    )
    # bypass 로 실제 전이가 일어났음을 DB 로 확인(복구=active, 완전삭제=deleted).
    assert trash_scenario.status_of(grandchild_id) == "active", "admin 복구가 실제 전이돼야 한다(INV-3)"
    assert trash_scenario.status_of(root_id) == "deleted", "admin 완전삭제가 실제 전이돼야 한다(INV-3)"


# =============================================================================
# 2) 작성자 보존·로그인 게이트 — 삭제 사용자 문서·버전 작성자 보존 (Req 7.2, INV-4)
# =============================================================================


def test_deleted_author_document_and_version_preserved_and_login_gated(
    ws_scenario, harness
):
    """문서·버전을 만든 사용자를 admin 이 삭제(`is_deleted=true`)해도 `created_by`·`name` 보존·후속 401(7.2, INV-4).

    아래 계층 결합을 실제 라우트로 밟는다: admin 이 이름을 아는 신규 사용자를 만들고 owner 가
    EDITOR 로 추가한 뒤 그 사용자 세션으로 문서를 만들고 잠금→저장해 **작성자=그 사용자**인
    `document`·`document_version` 을 생성한다(raw SELECT 로 `created_by` 확인). 이후 admin 이
    그 사용자를 삭제 처리하면:

    - 문서 행의 `created_by` 가 **여전히** 그 사용자 id 를 참조한다(작성자 참조 보존).
    - `document_version` 행의 `created_by` 가 **여전히** 그 사용자 id 를 참조한다(버전 작성자 보존).
    - `user` 행이 **여전히 물리 존재**하고 `name` 이 보존되며 `is_deleted=1` 로만 전이(물리 삭제 아님).
    - 삭제된 사용자의 잠금·저장 **후속 요청**이 세션 게이트(s01 `get_current_user` 의 `is_deleted`
      재검사)로 401 차단된다(권한 403 이전의 로그인 게이트).

    ws_scenario 의 기존 세션을 훼손하지 않도록 **신규** 사용자를 만들어 삭제한다.
    """
    author_uid, author_name, author_client = _provision_member(
        ws_scenario, harness, role="member", prefix="author", name=f"작성자-{uuid4().hex[:8]}"
    )
    ws_id = ws_scenario.workspace_id

    # 그 사용자 세션으로 문서 생성 → 잠금 → 저장(버전 생성). 작성자=그 사용자.
    doc_id = l3_helpers.create_document(author_client, ws_id, _title("작성자문서"))["id"]
    h.lock(author_client, doc_id)
    version = h.save(author_client, doc_id, "작성자 본문")
    version_id = version["id"]
    assert version["created_by"] == author_uid, "저장 버전 작성자는 그 사용자여야 한다(7.2 셋업)"

    # 삭제 전 문서·버전 작성자가 그 사용자임을 raw SELECT 로 확정.
    doc_before = _fetch_document(harness, doc_id)
    assert doc_before is not None and int(doc_before.created_by) == author_uid, (
        f"문서 created_by 는 생성 작성자여야 한다(7.2): 기대={author_uid} 관측={doc_before}"
    )
    ver_before = _fetch_version(harness, version_id)
    assert ver_before is not None and int(ver_before.created_by) == author_uid, (
        f"버전 created_by 는 저장 작성자여야 한다(7.2): 기대={author_uid} 관측={ver_before}"
    )

    # admin 이 작성자를 삭제 처리(is_deleted=true) — s03 계정 생명주기(물리 삭제 아님).
    l1_helpers.set_deleted(ws_scenario.admin_client, author_uid, True)

    # 문서 작성자 참조 보존.
    doc_after = _fetch_document(harness, doc_id)
    assert doc_after is not None and int(doc_after.created_by) == author_uid, (
        f"작성자 삭제 후에도 문서 created_by 참조는 보존되어야 한다(7.2, INV-4): "
        f"기대={author_uid} 관측={doc_after}"
    )
    # 버전 작성자 참조 보존.
    ver_after = _fetch_version(harness, version_id)
    assert ver_after is not None and int(ver_after.created_by) == author_uid, (
        f"작성자 삭제 후에도 document_version created_by 참조는 보존되어야 한다(7.2, INV-4): "
        f"기대={author_uid} 관측={ver_after}"
    )
    # 사용자 물리 보존 — 행 존재·name 보존·is_deleted 만 전이(물리 삭제 아님).
    user_row = _fetch_user(harness, author_uid)
    assert user_row is not None, (
        f"삭제 처리된 작성자 user 행은 물리 보존되어야 한다(7.2, INV-4): id={author_uid}"
    )
    assert user_row.name == author_name, (
        f"작성자 이름은 삭제 후에도 보존되어야 한다(작성자 표시 보존, INV-4): "
        f"기대={author_name!r} 관측={user_row.name!r}"
    )
    assert bool(user_row.is_deleted) is True, (
        f"삭제 처리는 is_deleted=true 상태 전이여야 한다(물리 삭제 아님): {user_row.is_deleted}"
    )

    # 삭제된 사용자의 후속 요청은 세션 게이트(is_deleted 재검사)로 401 차단(403 권한 이전).
    assert h.attempt_lock(author_client, doc_id).status_code == 401, (
        "삭제된 사용자의 잠금 후속 요청은 401 로그인 게이트로 차단되어야 한다(7.2, s02 세션 게이트)"
    )
    assert h.attempt_save(author_client, doc_id, "x").status_code == 401, (
        "삭제된 사용자의 저장 후속 요청도 401 로 차단되어야 한다(7.2)"
    )


# =============================================================================
# 3) 물리 삭제 부재 — 잠금·저장·취소·강제해제·복구·완전삭제·스윕 전반 (Req 7.3, INV-4)
# =============================================================================


def test_no_physical_delete_across_lock_trash_and_sweep_mix(
    trash_scenario, sweep_access, harness
):
    """잠금·저장·취소·강제해제·복구·완전삭제·보관 스윕을 섞은 전반에서 document·document_version·user 물리 삭제 부재(7.3, INV-4).

    `trash_scenario` 는 손자 단독 묶음(trashed_at=기준-40일, 만료 후보)과 루트+자식 묶음
    (trashed_at=기준-5일, 미만료)을 제공한다. 여기에 fresh 활성 문서의 잠금 생명주기를 얹어
    대표 시나리오를 구성하고, 모든 조작 **전후**로 물리 존재를 raw `SELECT`·`COUNT` 로 확인한다:

    - **잠금 생명주기**(잠금·저장·취소·강제해제): editor 가 fresh 문서를 만들고 잠금→저장(버전
      생성)→재잠금→취소→재잠금→owner 강제해제. 완전삭제·삭제 없이 문서·버전 물리 보존.
    - **복구·완전삭제·스윕**: 손자 묶음 복구(active) 후 다시 삭제하지 않고, 루트+자식 묶음을 실제
      라우터로 완전삭제(deleted 종착), 이어서 만료된 손자를 다시 삭제·스윕... 대신 순서를 단순화해
      루트 묶음은 완전삭제(API), 손자 묶음은 보관 스윕(`now` 주입)으로 각각 deleted 종착시킨다.
    - **관찰**: 조작 후에도 fresh 문서·버전·루트·자식·손자 행이 **모두 물리 존재**(완전삭제·자동
      삭제는 status=deleted 전환일 뿐)·user 행 수 불감소.
    """
    editor = trash_scenario.editor_client
    owner = trash_scenario.scenario.owner_client
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id
    editor_uid = trash_scenario.scenario.editor_user_id
    owner_uid = trash_scenario.scenario.owner_user_id

    users_before = _user_count(harness)

    # --- 잠금 생명주기(잠금·저장·취소·강제해제) on fresh 활성 문서 ---
    fresh_id = l3_helpers.create_document(editor, ws_id, _title("생명주기"))["id"]
    h.lock(editor, fresh_id)
    v1 = h.save(editor, fresh_id, "본문v1")  # 버전 1개 생성(저장=버전+잠금 해제).
    v1_id = v1["id"]
    h.lock(editor, fresh_id)
    h.cancel(editor, fresh_id)  # 취소 — 버전 미생성·잠금 해제.
    h.lock(editor, fresh_id)
    h.force_unlock(owner, fresh_id)  # owner 강제 해제 — 버전 미생성.

    # 잠금 생명주기 전반에서 fresh 문서·버전은 물리 삭제되지 않는다(상태 전이만 있었음).
    fresh_row = _fetch_document(harness, fresh_id)
    assert fresh_row is not None and fresh_row.status == "active", (
        f"잠금 생명주기 후 fresh 문서는 물리 보존·active 여야 한다(7.3, INV-4): {fresh_row}"
    )
    v1_row = _fetch_version(harness, v1_id)
    assert v1_row is not None and int(v1_row.document_id) == fresh_id, (
        f"저장 버전은 잠금 생명주기 전반에서 물리 보존되어야 한다(7.3, INV-4): {v1_row}"
    )
    fresh_versions_before = _version_ids_for(harness, [fresh_id])
    assert v1_id in fresh_versions_before, "저장 버전 id 가 물리 존재해야 한다(7.3 기준)"

    # --- 복구(엔진 위임) ---
    h.restore_bundle_via_api(editor, grandchild_id)  # 손자 묶음 복구 → active.
    assert trash_scenario.status_of(grandchild_id) == "active", "복구는 active 전이여야 한다"
    # 복구 후 다시 삭제해 만료 스윕 대상으로 되돌린다(trashed_at 은 fixture 핀 값과 무관하게 최신값).
    l3_helpers.delete_document(editor, grandchild_id)

    # --- 완전삭제(API, 엔진 위임) — 루트+자식 묶음 deleted 종착 ---
    h.purge_bundle_via_api(editor, root_id)
    for doc_id in (root_id, child_id):
        row = _fetch_document(harness, doc_id)
        assert row is not None and row.status == "deleted", (
            f"완전삭제는 물리 삭제가 아니라 status=deleted 전환이어야 한다(7.3, INV-4): id={doc_id} {row}"
        )

    # --- 보관 스윕(now 주입) — 만료된 손자 묶음 자동 영구삭제(deleted 종착) ---
    # 손자는 방금 재삭제되어 trashed_at 이 최신이므로, 만료가 되도록 먼 미래 now 를 주입한다
    # (워크스페이스 retention 일수를 크게 넘겨 만료 경계를 결정적으로 확보 — 스윕 실동작 관찰).
    far_future = trash_scenario.reference + timedelta(days=trash_scenario.retention_days + 3650)
    h.run_sweep(sweep_access, far_future)
    assert sweep_access.status_of(grandchild_id) == "deleted", (
        "보관 스윕은 만료 손자 묶음을 deleted 로 자동 영구삭제해야 한다(7.3 스윕 경로)"
    )

    # --- 전반 물리 삭제 부재 관찰 ---
    # (document) 조작한 모든 문서가 물리 존재(완전삭제·자동삭제는 status 전환일 뿐).
    for label, doc_id in (
        ("fresh", fresh_id),
        ("root", root_id),
        ("child", child_id),
        ("grandchild", grandchild_id),
    ):
        assert _fetch_document(harness, doc_id) is not None, (
            f"{label} 문서는 조작 전반에서 물리 삭제되지 않아야 한다(7.3, INV-4): id={doc_id}"
        )
    # (document_version) 저장 버전이 완전삭제·스윕 전반에서 물리 보존.
    assert _fetch_version(harness, v1_id) is not None, (
        f"저장 버전은 조작 전반에서 물리 삭제되지 않아야 한다(7.3, INV-4): id={v1_id}"
    )
    assert _version_ids_for(harness, [fresh_id, root_id, child_id, grandchild_id]) >= {v1_id}, (
        "저장 버전 집합이 조작 전반에서 축소되지 않아야 한다(물리 삭제 부재, 7.3)"
    )
    # (user) 작성자(editor)·owner 행 물리 보존·전체 user 행 수 불감소.
    assert _fetch_user(harness, editor_uid) is not None, (
        f"작성자 editor user 행은 물리 보존되어야 한다(7.3, INV-4): id={editor_uid}"
    )
    assert _fetch_user(harness, owner_uid) is not None, (
        f"owner user 행은 물리 보존되어야 한다(7.3, INV-4): id={owner_uid}"
    )
    assert _user_count(harness) >= users_before, (
        f"조작 전반에서 user 행 수가 물리 삭제로 줄지 않아야 한다(7.3, INV-4): "
        f"전={users_before} 후={_user_count(harness)}"
    )
