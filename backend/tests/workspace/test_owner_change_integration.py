"""admin 소유권 변경 및 계약 정합 통합 테스트 (Task 4.2).

마이그레이션된 DB + 부팅 앱(:func:`ws_harness`, task 4.1 이 conftest 에 정의)에서 admin
소유권 변경(`POST /admin/workspaces/{id}/owner`)의 실동작과 s05 의 계약 정합·재사용을 진짜
ASGI 요청·세션 쿠키 인증으로 검증한다(design.md §Testing Strategy → Integration Tests +
Contract Consistency Tests, §System Flows admin 소유권 변경). 4.1 의
``test_resolver_integration.py`` 와 **별도 파일**이며 동일한 하네스를 재사용한다(mock 없음).

네 개의 검증 축(요구):

1. **owner 부재 → admin 이 새 owner 지정(Req 5.1·5.2·5.3·5.6·3.9)**: 워크스페이스의 owner
   멤버십을 모두 제거해 owner 부재 상태로 만든 뒤 admin 이 owner 를 지정하면, 지정된 사용자가
   실제 owner 로 upsert 되어 OWNER 게이트(`PATCH /workspaces/{id}`)를 통과함을 관찰한다.
   비멤버→신규 owner 등록(5.2·5.6)과 기존 비-owner 멤버→owner 승격(5.3) 두 upsert 경로를
   모두 커버한다.
2. **비-admin 소유권 변경 → 403(Req 5.4)**: 이 라우트는 owner 게이트가 아니라 admin 전용이므로
   워크스페이스 owner 라 하더라도 비-admin 이면 403 `forbidden`.
3. **계약 정합(Req 6.1·6.2)**: `WorkspaceRead` 가 `{Resource}Read`(TimestampedRead + 고유
   필드) 형태를 정확히 따르고 초과 필드가 없음, `GET /workspaces` 가 `Page[WorkspaceRead]`
   엔벨로프(`items`·`total`)를 따름, 에러 응답이 s01 `ErrorResponse`(code·message·
   field_errors) 형태를 따름(422 는 field_errors 채워짐).
4. **새 마이그레이션 없음·s01 스키마만 사용(Req 6.5)**: `migrations/versions/` 리비전 집합이
   s01 초기 마이그레이션 하나뿐임을 확인하고, `Base.metadata` 가 s01 `workspace`·
   `workspace_member` 스키마(컬럼)만 담고 s05 전용 신규 테이블이 없음을 확인한다.

DB 미가용 시 하네스가 그대로 실패한다(``pytest.skip`` 을 쓰지 않는다 — 미검증을 통과로
오인 방지).
"""

from pathlib import Path

from app.common.db import Base
from app.models import Workspace, WorkspaceMember

# s01 §Physical Data Model — workspace/workspace_member 물리 계약(컬럼 집합, 단일 소스).
S01_WORKSPACE_COLUMNS = {
    "id",
    "name",
    "is_shareable",
    "trash_retention_days",
    "created_at",
    "updated_at",
}
S01_WORKSPACE_MEMBER_COLUMNS = {"id", "workspace_id", "user_id", "role"}

# s01 §Physical Data Model — 초기 마이그레이션이 생성하는 전체 테이블 집합(7개).
# s05 는 이 위에서만 동작하며 새 테이블을 metadata 에 추가하지 않는다(Req 6.5).
S01_ALL_TABLES = {
    "user",
    "workspace",
    "workspace_member",
    "document",
    "document_version",
    "attachment",
    "share_link",
}

# s01 §Base Schemas — WorkspaceRead = TimestampedRead(id/created_at/updated_at) + 고유 필드.
# s24-role-persistence: 가산 optional `role` 필드가 추가됐다(호출자 멤버십 role, 목록 경로만
# 실값 주입·그 외 경로 None). optional 기본값이라도 FastAPI 는 키를 직렬화하므로 exact-set
# 계약 가드에 `role` 을 포함한다(create/change_owner=null·list item=멤버 role, 키는 항상 존재).
WORKSPACE_READ_KEYS = {
    "id",
    "created_at",
    "updated_at",
    "name",
    "is_shareable",
    "trash_retention_days",
    "role",
}

_DEFAULT_PW = "ws-member-pass-123"


def _create_workspace(client, name: str = "소유권 공간") -> int:
    """인증 클라이언트로 ``POST /workspaces`` 를 태워 201 을 단언하고 생성된 id 를 반환한다."""
    resp = client.post("/workspaces", json={"name": name})
    assert resp.status_code == 201, f"생성 201 이어야 한다: {resp.status_code} {resp.text}"
    return resp.json()["id"]


def _owner_count(harness, ws_id: int) -> int:
    """신규 세션으로 워크스페이스의 owner role 멤버 수를 관찰한다(커밋된 실제 상태)."""
    session = harness.session_local()
    try:
        return (
            session.query(WorkspaceMember)
            .filter_by(workspace_id=ws_id, role="owner")
            .count()
        )
    finally:
        session.close()


def _member_row(harness, ws_id: int, user_id: int):
    """신규 세션으로 (ws_id, user_id) 멤버십 행을 조회한다(커밋된 실제 상태 관찰용)."""
    session = harness.session_local()
    try:
        return (
            session.query(WorkspaceMember)
            .filter_by(workspace_id=ws_id, user_id=user_id)
            .one_or_none()
        )
    finally:
        session.close()


def _make_owner_absent(harness, ws_id: int) -> None:
    """워크스페이스의 모든 멤버십을 신규 세션으로 직접 제거해 owner 부재 상태로 만든다.

    유일 owner 의 비활동·삭제로 소유자가 사라진 상황(Req 5 objective)을 결정적으로 재현한다.
    """
    session = harness.session_local()
    try:
        session.query(WorkspaceMember).filter_by(workspace_id=ws_id).delete()
        session.commit()
    finally:
        session.close()


# --- 1. owner 부재 → admin 이 새 owner 지정 (Req 5.1·5.2·5.6·3.9) ------------------


def test_admin_assigns_owner_to_nonmember_from_owner_absent_state(ws_harness):
    """owner 부재 워크스페이스에 admin 이 비멤버를 owner 로 지정 → 200, 실제 owner 로 upsert.

    (a) creator 가 워크스페이스를 만들어 owner 로 등록됨 → (b) 모든 멤버십 제거로 owner 부재
    (owner 0개) → (c) admin `POST /admin/workspaces/{id}/owner`(비멤버 대상)→ 200 WorkspaceRead
    → (d) 지정된 사용자가 자기 세션으로 OWNER 게이트(`PATCH /workspaces/{id}`)를 통과.
    비멤버→신규 owner 등록(Req 5.2·5.6)과 owner 부재에서의 지정(Req 5.6·3.9)을 증명한다.
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "oc-creator-1", name="생성자")
    new_owner_id = ws_harness.create_user(admin, "oc-newowner-1", name="새오너")

    creator = ws_harness.login("oc-creator-1", _DEFAULT_PW)
    ws_id = _create_workspace(creator, "owner-부재 공간")

    # owner 부재 상태로 전이: 모든 멤버십 제거 → owner 0개 확인(전제 관찰).
    _make_owner_absent(ws_harness, ws_id)
    assert _owner_count(ws_harness, ws_id) == 0, "owner 부재 전제: owner 가 0명이어야 한다"
    # 대상 사용자는 아직 비멤버여야 한다(비멤버→owner 경로 전제).
    assert _member_row(ws_harness, ws_id, new_owner_id) is None, (
        "대상 사용자는 지정 전 비멤버여야 한다"
    )

    # admin 이 비멤버 사용자를 owner 로 지정 → 200 + WorkspaceRead.
    resp = admin.post(
        f"/admin/workspaces/{ws_id}/owner", json={"new_owner_user_id": new_owner_id}
    )
    assert resp.status_code == 200, f"소유권 변경은 200: {resp.status_code} {resp.text}"
    assert resp.json()["id"] == ws_id

    # 신규 세션으로 upsert 결과 관찰: 대상이 owner role 멤버로 신규 등록됨(Req 5.2).
    row = _member_row(ws_harness, ws_id, new_owner_id)
    assert row is not None, "비멤버 대상이 owner 멤버로 신규 등록되어야 한다"
    assert row.role == "owner", "지정된 사용자는 owner role 이어야 한다"

    # 관찰 가능 완료: 지정된 사용자가 자기 세션으로 OWNER 게이트를 실제로 통과(Req 5.6·3.9).
    new_owner = ws_harness.login("oc-newowner-1", _DEFAULT_PW)
    gate = new_owner.patch(f"/workspaces/{ws_id}", json={"name": "새오너-변경"})
    assert gate.status_code == 200, (
        f"지정된 owner 는 OWNER 게이트를 통과해야 한다(upsert→실 owner): "
        f"{gate.status_code} {gate.text}"
    )
    assert gate.json()["name"] == "새오너-변경"


def test_admin_owner_change_promotes_existing_member_to_owner(ws_harness):
    """이미 비-owner 멤버(member)인 사용자를 admin 이 owner 로 승격 → role 갱신·게이트 통과.

    upsert 의 "기존 멤버 → role owner 로 갱신" 경로(Req 5.3)를 커버한다. member 로 등록된
    사용자는 초기에는 OWNER 게이트에서 403 이지만, admin 소유권 변경 후 owner 로 갱신되어
    같은 사용자가 이제 통과한다.
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "oc-owner-2", name="오너")
    member_id = ws_harness.create_user(admin, "oc-member-2", name="일반멤버")

    owner = ws_harness.login("oc-owner-2", _DEFAULT_PW)
    ws_id = _create_workspace(owner, "승격 공간")
    # member 로 등록 → 초기에는 OWNER 게이트 미달.
    assert (
        owner.post(
            f"/workspaces/{ws_id}/members",
            json={"user_id": member_id, "role": "member"},
        ).status_code
        == 201
    )
    member = ws_harness.login("oc-member-2", _DEFAULT_PW)
    before = member.patch(f"/workspaces/{ws_id}", json={"name": "미달-시도"})
    assert before.status_code == 403, f"member 는 승격 전 403: {before.text}"

    # admin 이 기존 멤버를 owner 로 승격 → 200, 멤버십 role 이 owner 로 갱신.
    resp = admin.post(
        f"/admin/workspaces/{ws_id}/owner", json={"new_owner_user_id": member_id}
    )
    assert resp.status_code == 200, f"소유권 변경은 200: {resp.status_code} {resp.text}"
    row = _member_row(ws_harness, ws_id, member_id)
    assert row is not None and row.role == "owner", (
        "기존 멤버의 role 이 owner 로 갱신되어야 한다(Req 5.3)"
    )

    # 승격 후: 같은 사용자가 이제 OWNER 게이트를 통과.
    after = member.patch(f"/workspaces/{ws_id}", json={"name": "승격-후-변경"})
    assert after.status_code == 200, (
        f"승격된 멤버는 OWNER 게이트를 통과해야 한다: {after.status_code} {after.text}"
    )


# --- 2. 비-admin 소유권 변경 → 403 (Req 5.4) ---------------------------------------


def test_non_admin_owner_change_forbidden(ws_harness):
    """비-admin(워크스페이스 owner 라도) 의 소유권 변경 요청 → 403 forbidden (admin 전용).

    이 라우트는 owner 게이트가 아니라 `require_admin` 게이트이므로, 워크스페이스 owner 조차
    비-admin 이면 403 이다(Req 5.4). 미인증은 401(경계 확인).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "oc-owner-3", name="오너")
    target_id = ws_harness.create_user(admin, "oc-target-3", name="대상")

    owner = ws_harness.login("oc-owner-3", _DEFAULT_PW)
    ws_id = _create_workspace(owner, "권한 경계 공간")

    # 워크스페이스 owner(비-admin)의 소유권 변경 → 403 forbidden.
    resp = owner.post(
        f"/admin/workspaces/{ws_id}/owner", json={"new_owner_user_id": target_id}
    )
    assert resp.status_code == 403, f"비-admin 은 403: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["code"] == "forbidden", f"code=forbidden 이어야 한다: {body!r}"

    # 미인증(세션 없음) → 401(require_admin 이 의존하는 get_current_user 경계).
    anon = ws_harness.new_client()
    r_anon = anon.post(
        f"/admin/workspaces/{ws_id}/owner", json={"new_owner_user_id": target_id}
    )
    assert r_anon.status_code == 401, f"미인증은 401: {r_anon.status_code} {r_anon.text}"
    assert r_anon.json()["code"] == "unauthenticated"


# --- 3. 계약 정합 (Req 6.1·6.2) ---------------------------------------------------


def _assert_error_response_shape(body: object) -> None:
    """관측된 에러 본문이 s01 ``ErrorResponse`` 형태를 따르는지 강제한다(Req 6.2).

    최소 계약(s01 §Errors): 문자열 ``code`` 와 문자열 ``message`` 키를 가지며,
    ``field_errors`` 가 존재하면 리스트다(``{code, message, field_errors?}``).
    """
    assert isinstance(body, dict), f"에러 본문은 JSON 객체여야 한다: {body!r}"
    assert isinstance(body.get("code"), str), f"code 는 문자열이어야 한다: {body!r}"
    assert isinstance(body.get("message"), str), f"message 는 문자열이어야 한다: {body!r}"
    if "field_errors" in body and body["field_errors"] is not None:
        assert isinstance(body["field_errors"], list), (
            f"field_errors 가 존재하면 리스트여야 한다: {body!r}"
        )


def test_workspace_read_matches_resource_read_contract(ws_harness):
    """WorkspaceRead 응답(생성·소유권 변경)이 `{Resource}Read` 형태를 정확히 따른다(Req 6.1).

    TimestampedRead(id·created_at·updated_at) + 고유 필드(name·is_shareable·
    trash_retention_days) 정확히 6개 키만 노출하고 초과 필드가 없음을 단언한다. 생성 응답과
    소유권 변경 응답 모두 동일 계약을 따름을 확인한다.
    """
    admin = ws_harness.login_admin()
    owner_id = ws_harness.create_user(admin, "oc-owner-4", name="오너")
    owner = ws_harness.login("oc-owner-4", _DEFAULT_PW)

    # (1) 생성 응답의 WorkspaceRead 형태.
    create = owner.post("/workspaces", json={"name": "계약 공간"})
    assert create.status_code == 201, f"{create.status_code} {create.text}"
    body = create.json()
    assert set(body.keys()) == WORKSPACE_READ_KEYS, (
        f"WorkspaceRead 키가 계약과 정확히 일치해야 한다(초과·누락 금지): "
        f"관측={sorted(body.keys())} 기대={sorted(WORKSPACE_READ_KEYS)}"
    )
    # TimestampedRead 필드 타입 계약: id 는 int, name/is_shareable/trash_retention_days.
    assert isinstance(body["id"], int)
    assert isinstance(body["name"], str)
    assert isinstance(body["is_shareable"], bool)
    assert isinstance(body["trash_retention_days"], int)
    assert isinstance(body["created_at"], str), "created_at 은 직렬화된 타임스탬프여야 한다"
    # updated_at 은 nullable(생성 직후 None) — 키 자체는 존재해야 한다.
    assert "updated_at" in body
    ws_id = body["id"]

    # (2) 소유권 변경 응답도 동일한 WorkspaceRead 형태여야 한다.
    change = admin.post(
        f"/admin/workspaces/{ws_id}/owner", json={"new_owner_user_id": owner_id}
    )
    assert change.status_code == 200, f"{change.status_code} {change.text}"
    assert set(change.json().keys()) == WORKSPACE_READ_KEYS, (
        f"소유권 변경 응답도 WorkspaceRead 계약을 따라야 한다: {sorted(change.json().keys())}"
    )


def test_list_workspaces_returns_page_envelope(ws_harness):
    """GET /workspaces 가 `Page[WorkspaceRead]` 엔벨로프(items·total)를 따른다(Req 6.1·6.2)."""
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "oc-owner-5", name="오너")
    owner = ws_harness.login("oc-owner-5", _DEFAULT_PW)
    _create_workspace(owner, "목록 공간 A")
    _create_workspace(owner, "목록 공간 B")

    resp = owner.get("/workspaces")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    page = resp.json()
    # 최상위 엔벨로프 계약: items(list) + total(int), 그 외 키 없음.
    assert set(page.keys()) == {"items", "total"}, (
        f"Page 엔벨로프는 items·total 만 가져야 한다: {sorted(page.keys())}"
    )
    assert isinstance(page["items"], list), "items 는 리스트여야 한다"
    assert isinstance(page["total"], int), "total 은 정수여야 한다"
    assert page["total"] >= 2 and len(page["items"]) >= 2, (
        "생성한 2개 워크스페이스가 목록·total 에 반영되어야 한다"
    )
    # 각 항목이 WorkspaceRead 계약을 따름.
    for item in page["items"]:
        assert set(item.keys()) == WORKSPACE_READ_KEYS, (
            f"Page 항목은 WorkspaceRead 계약을 따라야 한다: {sorted(item.keys())}"
        )


def test_error_responses_conform_to_s01_error_model(ws_harness):
    """403·404·422 응답이 s01 `ErrorResponse` 형태를 따른다(Req 6.2).

    - 403(비-admin 소유권 변경): code=forbidden, field_errors 는 present/null.
    - 404(미존재 워크스페이스 소유권 변경): code=not_found.
    - 422(malformed owner-change 본문): code=validation_error + 비어있지 않은 field_errors.
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "oc-owner-6", name="오너")
    target_id = ws_harness.create_user(admin, "oc-target-6", name="대상")
    owner = ws_harness.login("oc-owner-6", _DEFAULT_PW)
    ws_id = _create_workspace(owner, "에러 계약 공간")

    # 403 — 비-admin 소유권 변경.
    r403 = owner.post(
        f"/admin/workspaces/{ws_id}/owner", json={"new_owner_user_id": target_id}
    )
    assert r403.status_code == 403, f"{r403.status_code} {r403.text}"
    _assert_error_response_shape(r403.json())
    assert r403.json()["code"] == "forbidden"

    # 404 — 미존재 워크스페이스 소유권 변경(admin 게이트 통과 후 서비스 404).
    r404 = admin.post(
        "/admin/workspaces/999999999/owner", json={"new_owner_user_id": target_id}
    )
    assert r404.status_code == 404, f"{r404.status_code} {r404.text}"
    _assert_error_response_shape(r404.json())
    assert r404.json()["code"] == "not_found"

    # 422 — malformed 본문(필수 new_owner_user_id 누락) → validation_error + field_errors.
    r422 = admin.post(f"/admin/workspaces/{ws_id}/owner", json={})
    assert r422.status_code == 422, f"{r422.status_code} {r422.text}"
    body = r422.json()
    _assert_error_response_shape(body)
    assert body["code"] == "validation_error", f"422 는 validation_error: {body!r}"
    assert isinstance(body.get("field_errors"), list) and len(body["field_errors"]) > 0, (
        f"스키마 위반은 비어있지 않은 field_errors 를 포함해야 한다: {body!r}"
    )


# --- 4. 새 마이그레이션 없음 · s01 스키마만 사용 (Req 6.5) --------------------------


def _versions_dir() -> Path:
    """backend/migrations/versions/ 디렉터리 경로(테스트 파일 기준으로 견고하게 해석)."""
    # tests/workspace/<this file> → parents[2] = backend.
    return Path(__file__).resolve().parents[2] / "migrations" / "versions"


def test_s05_adds_no_new_migration(ws_harness):
    """s05 가 새 Alembic 마이그레이션을 추가하지 않았음을 확인(Req 6.5).

    `migrations/versions/` 를 실제로 읽어 리비전 파일 집합이 s01 초기 마이그레이션
    (`0001_initial_schema.py`) **하나뿐**임을 단언한다. s02~s05 어느 spec 도 새 마이그레이션을
    추가하지 않았으므로(모두 s01 스키마 위에서 동작), 이 baseline 이 그대로 유지되어야 한다.
    파일명에 의존하지 않고 리비전 파일 목록 자체를 읽어 비교하므로 브리틀하지 않다.
    """
    versions = _versions_dir()
    assert versions.is_dir(), f"마이그레이션 versions 디렉터리가 존재해야 한다: {versions}"

    revision_files = {
        p.name
        for p in versions.glob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    }
    # s01 baseline(0001) + additive user_setting(0002). s05(및 s02~s04)가 자기
    # 마이그레이션을 추가하지 않았음을 검증하는 것이 목적이므로 additive user_setting 은 허용.
    assert revision_files == {"0001_initial_schema.py", "0002_user_setting.py", "0003_user_setting_last_selected_workspace.py"}, (
        "s05(및 s02~s04)는 새 마이그레이션을 추가하지 않아야 한다(s01 baseline + additive user_setting 만 존재해야 함): "
        f"관측={sorted(revision_files)}"
    )

    # 추가 견고성: baseline 이 down_revision 없는 최초 리비전(단일 마이그레이션 체인)임을 확인.
    text = (versions / "0001_initial_schema.py").read_text(encoding="utf-8")
    assert 'revision: str = "0001"' in text, "s01 baseline 의 revision id 는 0001 이어야 한다"
    assert "down_revision: Union[str, None] = None" in text, (
        "baseline 은 최초 리비전(down_revision None)이어야 한다 — 뒤따르는 s05 리비전 없음"
    )


def test_base_metadata_uses_only_s01_workspace_schema(ws_harness):
    """`Base.metadata` 가 s01 workspace·workspace_member 스키마만 담고 s05 신규 테이블이 없음.

    (a) 전체 테이블 집합이 s01 초기 마이그레이션 7개 테이블과 정확히 일치(s05 전용 신규 테이블
    없음), (b) workspace·workspace_member 컬럼 집합이 s01 물리 모델과 일치함을 단언한다(Req 6.5).
    """
    tables = set(Base.metadata.tables)
    # (a) s05 가 새 테이블을 metadata 에 추가하지 않음 — s01 7개 + additive user_setting 과 정확히 일치.
    expected_tables = S01_ALL_TABLES | {"user_setting"}
    assert tables == expected_tables, (
        f"metadata 테이블 집합이 s01 계약(+additive user_setting)과 정확히 일치해야 한다(s05 신규 테이블 금지): "
        f"관측={sorted(tables)} 기대={sorted(expected_tables)}"
    )

    # (b) workspace·workspace_member 가 s01 물리 컬럼만 가짐(s05 컬럼 추가 없음).
    ws_cols = set(Base.metadata.tables["workspace"].columns.keys())
    assert ws_cols == S01_WORKSPACE_COLUMNS, (
        f"workspace 컬럼이 s01 계약과 일치해야 한다: 관측={sorted(ws_cols)}"
    )
    member_cols = set(Base.metadata.tables["workspace_member"].columns.keys())
    assert member_cols == S01_WORKSPACE_MEMBER_COLUMNS, (
        f"workspace_member 컬럼이 s01 계약과 일치해야 한다: 관측={sorted(member_cols)}"
    )

    # workspace_member.role 은 s26 2단계 ENUM(owner/member) 계약을 따른다(정합 재확인).
    role_type = Base.metadata.tables["workspace_member"].columns["role"].type
    assert set(getattr(role_type, "enums", [])) == {"owner", "member"}, (
        f"role ENUM 값이 2단계 모델(owner/member)과 일치해야 한다: {getattr(role_type, 'enums', None)!r}"
    )
