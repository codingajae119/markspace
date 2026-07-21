"""배정 가능 사용자 조회 엔드포인트 게이팅·페이지네이션 통합 테스트 (Task 2.2).

마이그레이션된 DB + 부팅 앱(:func:`ws_harness`)에서 owner-gated 조회 엔드포인트
``GET /workspaces/{id}/assignable-users`` 를 mock 없이 진짜 ASGI 요청·세션 쿠키 인증으로
검증한다(design.md §Testing Strategy → Integration Tests, §Security Considerations).

이 엔드포인트는 task 1.4 에서 이미 커밋되어 통과하므로 본 파일은 **이미 배포된 동작을
검증하는 커버리지 task** 다(RED→GREEN 아님). 대신 게이팅이 실질적으로 판정되는지(예: member 가
trivially 통과가 아니라 진짜 403), 페이지네이션 items/total 일관성, narrow 봉투 누출 부재를
HTTP 경계에서 단언한다.

검증 대상(tasks.md 2.2 + design.md):
- 게이팅 매트릭스: owner→200, member→403, 비멤버→403, admin(비-owner)→200,
  미인증(세션 없음·무효)→401 (Req 2.1·2.2·2.3·2.4).
- 존재하지 않는 워크스페이스→403(404 로 존재 노출 안 함, anti-enumeration) (Req 2.4).
- 페이지네이션: 페이지 크기보다 배정 가능 총수가 클 때 limit/offset 경계에서 items·total 일관,
  잘못된 limit/offset→422 (Req 1.5).
- 배정 가능 0명→200 `{items:[], total:0}` (오류 아님) (Req 1.4).
- narrow 봉투: 응답 사용자 객체는 id/name/email 만 — login_id·상태 flag·타임스탬프·
  password_hash 부재를 HTTP 경계에서 단언 (Req 1.2).
"""

from datetime import datetime

from app.common.security import hash_password
from app.models import User

# 배정 가능 사용자 시드용 기본 비밀번호(로그인에 쓰지 않지만 password_hash 를 실 해시로 채운다).
_SEED_PASSWORD = "assignable-seed-pass-123"


def _create_workspace(client, name: str = "배정 공간") -> int:
    """인증 클라이언트로 ``POST /workspaces`` 를 태워 201 을 단언하고 생성된 id 를 반환한다.

    생성자는 s05 계약상 owner 멤버로 자동 등록된다(게이팅 매트릭스의 owner 근거).
    """
    resp = client.post("/workspaces", json={"name": name})
    assert resp.status_code == 201, f"생성 201 이어야 한다: {resp.status_code} {resp.text}"
    return resp.json()["id"]


def _add_member(owner_client, ws_id: int, user_id: int, role: str):
    """owner(또는 admin) 클라이언트로 멤버를 추가하고 응답을 그대로 반환한다."""
    return owner_client.post(
        f"/workspaces/{ws_id}/members", json={"user_id": user_id, "role": role}
    )


def _seed_assignable_user(
    harness,
    login_id: str,
    *,
    name: str,
    email: str | None,
    is_admin: bool = False,
    is_active: bool = True,
    is_deleted: bool = False,
) -> int:
    """배정 가능(또는 경계) 사용자를 ORM 으로 직접 커밋 시드하고 그 id 를 반환한다.

    기본값(admin 아님·활성·비삭제)은 "배정 가능" 조건을 충족한다. 이 사용자들은
    로그인하지 않고 목록 대상으로만 쓰이므로 admin ``POST /admin/users`` 경로 대신 ORM
    시드로 email·상태 flag 를 정밀 제어한다(SETUP 헬퍼, feature 로직 아님). 앱은 override 된
    별도 세션(별도 커넥션)으로 조회하므로 commit 이 필수다.
    """
    session = harness.session_local()
    try:
        user = User(
            login_id=login_id,
            password_hash=hash_password(_SEED_PASSWORD),
            name=name,
            email=email,
            is_admin=is_admin,
            is_active=is_active,
            is_deleted=is_deleted,
            created_at=datetime.utcnow(),
        )
        session.add(user)
        session.commit()
        return user.id
    finally:
        session.close()


def _get_assignable(client, ws_id: int, *, limit=None, offset=None):
    """``GET /workspaces/{id}/assignable-users`` 를 (선택적 쿼리와 함께) 호출한다."""
    params = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return client.get(f"/workspaces/{ws_id}/assignable-users", params=params)


# --- 1. 게이팅 매트릭스 (Req 2.1·2.2·2.3·2.4) ---------------------------------


def test_gating_matrix_owner_admin_pass_others_rejected(ws_harness):
    """owner·admin→200, member·비멤버→403, 미인증→401 (Req 2.1·2.2·2.3·2.4).

    게이팅이 trivially 통과가 아니라 실질 판정임을 증명한다: member 는 실제 role 로
    등록되었음에도 OWNER 미달로 진짜 403 을 받고, owner·admin(비-멤버)만 200 을 받는다.
    """
    admin = ws_harness.login_admin()
    owner_id = ws_harness.create_user(admin, "au-owner", name="오너")
    member_id = ws_harness.create_user(admin, "au-member", name="멤버")
    ws_harness.create_user(admin, "au-nonmember", name="비멤버")

    owner = ws_harness.login("au-owner", "ws-member-pass-123")
    member = ws_harness.login("au-member", "ws-member-pass-123")
    nonmember = ws_harness.login("au-nonmember", "ws-member-pass-123")

    ws_id = _create_workspace(owner, "게이팅 공간")
    # member 를 실제 role 로 등록 → 게이트가 실제 role 로 판정하게 만든다.
    assert _add_member(owner, ws_id, member_id, "member").status_code == 201

    # owner ≥ OWNER → 200.
    r_owner = _get_assignable(owner, ws_id)
    assert r_owner.status_code == 200, f"owner 는 200: {r_owner.text}"
    assert set(r_owner.json().keys()) == {"items", "total"}

    # member 는 OWNER 미달 → 진짜 403 (trivial 통과 아님, Req 5.4).
    r_member = _get_assignable(member, ws_id)
    assert r_member.status_code == 403, f"member 는 403: {r_member.text}"
    assert r_member.json()["code"] == "forbidden"

    # 비멤버(로그인했으나 멤버 아님) → 403 (Req 2.1).
    r_non = _get_assignable(nonmember, ws_id)
    assert r_non.status_code == 403, f"비멤버는 403: {r_non.text}"
    assert r_non.json()["code"] == "forbidden"

    # admin(비-owner 멤버) → override 로 200 (Req 2.2).
    r_admin = _get_assignable(admin, ws_id)
    assert r_admin.status_code == 200, f"admin override 는 200: {r_admin.text}"
    assert set(r_admin.json().keys()) == {"items", "total"}

    # 미인증(세션 없음) → 401 (Req 2.3).
    anon = ws_harness.new_client()
    r_anon = _get_assignable(anon, ws_id)
    assert r_anon.status_code == 401, f"미인증은 401: {r_anon.text}"
    assert r_anon.json()["code"] == "unauthenticated"


def test_invalid_session_cookie_returns_401(ws_harness):
    """무효 세션 쿠키(변조)로도 401 이다 (Req 2.3, 미인증 경계 세분)."""
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "au-owner2", name="오너")
    owner = ws_harness.login("au-owner2", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "무효세션 공간")

    bad = ws_harness.new_client()
    bad.cookies.set(ws_harness.session_cookie_name, "not-a-valid-session-token")
    r = _get_assignable(bad, ws_id)
    assert r.status_code == 401, f"무효 세션은 401: {r.status_code} {r.text}"
    assert r.json()["code"] == "unauthenticated"


# --- 2. 존재하지 않는 워크스페이스 → 403 (anti-enumeration, Req 2.4) ----------


def test_nonexistent_workspace_returns_403_not_404(ws_harness):
    """존재하지 않는 워크스페이스 조회는 403(비-멤버 게이트) — 404 로 존재 노출 안 함 (Req 2.4).

    로그인한 non-admin 사용자가 존재하지 않는 id 를 조회하면 게이트 단계에서 비-멤버 →
    403 이어야 한다. 404 였다면 워크스페이스 존재 여부가 열거 가능해진다(anti-enumeration 위반).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "au-probe", name="탐침")
    prober = ws_harness.login("au-probe", "ws-member-pass-123")

    missing_ws_id = 9_999_999
    r = _get_assignable(prober, missing_ws_id)
    assert r.status_code == 403, (
        f"존재하지 않는 워크스페이스는 403 이어야 한다(404 아님): {r.status_code} {r.text}"
    )
    assert r.json()["code"] == "forbidden"
    assert r.status_code != 404, "404 는 존재를 노출하므로 금지(anti-enumeration)"


# --- 3. 페이지네이션 (Req 1.5) ------------------------------------------------


def test_pagination_limit_offset_items_and_total_consistent(ws_harness):
    """배정 가능 총수 > 페이지 크기일 때 limit/offset 경계에서 items·total 이 일관한다 (Req 1.5).

    total 은 항상 배정 가능 전체 개수(5)이고, items 는 limit 로 상한되며 offset 이 슬라이스를
    올바르게 이동시킨다. 순서는 결정적(User.id 오름차순)이어야 페이지가 겹치지 않는다.
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "au-pg-owner", name="오너")
    owner = ws_harness.login("au-pg-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "페이지 공간")

    # 배정 가능 사용자 5명 시드(owner 는 멤버, admin 은 admin → 둘 다 제외되어 total=5).
    seeded_ids = [
        _seed_assignable_user(
            ws_harness, f"au-pg-{i}", name=f"배정{i}", email=f"pg{i}@example.com"
        )
        for i in range(5)
    ]
    assert seeded_ids == sorted(seeded_ids), "시드 id 는 증가 순이어야 한다(순서 단언 전제)"

    # 첫 페이지: limit=2 → items 2개, total 5.
    r0 = _get_assignable(owner, ws_id, limit=2, offset=0)
    assert r0.status_code == 200, r0.text
    body0 = r0.json()
    assert body0["total"] == 5, f"total 은 배정 가능 총수(5)여야 한다: {body0['total']}"
    assert len(body0["items"]) == 2, "items 는 limit 로 상한된다"
    page0_ids = [u["id"] for u in body0["items"]]
    assert page0_ids == seeded_ids[0:2], f"첫 페이지 슬라이스: {page0_ids}"

    # 두번째 페이지: offset=2 → 다음 2개.
    r1 = _get_assignable(owner, ws_id, limit=2, offset=2)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["total"] == 5, "total 은 offset 과 무관하게 전체 개수여야 한다"
    page1_ids = [u["id"] for u in body1["items"]]
    assert page1_ids == seeded_ids[2:4], f"두번째 페이지 슬라이스: {page1_ids}"

    # 세번째 페이지: offset=4 → 남은 1개(끝 경계).
    r2 = _get_assignable(owner, ws_id, limit=2, offset=4)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["total"] == 5
    page2_ids = [u["id"] for u in body2["items"]]
    assert page2_ids == seeded_ids[4:5], f"세번째 페이지 슬라이스: {page2_ids}"

    # 페이지들이 서로 겹치지 않고 전체를 정확히 커버한다(결정적 순서 검증).
    assert page0_ids + page1_ids + page2_ids == seeded_ids

    # offset 이 총수를 넘으면 빈 items·불변 total.
    r3 = _get_assignable(owner, ws_id, limit=2, offset=10)
    assert r3.status_code == 200, r3.text
    assert r3.json()["items"] == []
    assert r3.json()["total"] == 5


def test_invalid_limit_and_offset_return_422(ws_harness):
    """limit=0·offset=-1 등 범위 위반은 FastAPI 가 422 로 거부한다 (Req 1.5)."""
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "au-422-owner", name="오너")
    owner = ws_harness.login("au-422-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "422 공간")

    assert _get_assignable(owner, ws_id, limit=0).status_code == 422, "limit=0(<1)→422"
    assert _get_assignable(owner, ws_id, offset=-1).status_code == 422, "offset=-1(<0)→422"


# --- 4. 배정 가능 0명 → 200 빈 봉투 (Req 1.4) ---------------------------------


def test_zero_assignable_users_returns_empty_page_not_error(ws_harness):
    """배정 가능 사용자가 없으면 200 `{items:[], total:0}` — 오류가 아니다 (Req 1.4).

    owner 는 멤버(제외), admin 은 admin(제외)이라 다른 non-admin 사용자를 시드하지 않으면
    배정 가능은 0명이다.
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "au-empty-owner", name="오너")
    owner = ws_harness.login("au-empty-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "빈 공간")

    r = _get_assignable(owner, ws_id)
    assert r.status_code == 200, f"빈 목록도 200: {r.status_code} {r.text}"
    assert r.json() == {"items": [], "total": 0}, f"빈 봉투여야 한다: {r.json()}"


def test_boundary_users_excluded_from_assignable(ws_harness):
    """admin·비활성·삭제·기존 멤버는 배정 가능에서 제외된다 (Req 1.1, 게이팅 매트릭스 보강).

    HTTP 경계에서 필터 정의가 실질적으로 적용되는지 확인한다: 각 경계 사용자 1명씩 시드하되
    배정 가능 사용자 1명만 결과에 남아야 한다.
    """
    admin = ws_harness.login_admin()
    member_id = ws_harness.create_user(admin, "au-bnd-member", name="기존멤버")
    ws_harness.create_user(admin, "au-bnd-owner", name="오너")
    owner = ws_harness.login("au-bnd-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "경계 공간")
    assert _add_member(owner, ws_id, member_id, "member").status_code == 201

    # 경계 사용자들(각각 제외 대상) + 배정 가능 1명.
    _seed_assignable_user(
        ws_harness, "au-bnd-admin", name="어드민", email="a@x.com", is_admin=True
    )
    _seed_assignable_user(
        ws_harness, "au-bnd-inactive", name="비활성", email="i@x.com", is_active=False
    )
    _seed_assignable_user(
        ws_harness, "au-bnd-deleted", name="삭제", email="d@x.com", is_deleted=True
    )
    ok_id = _seed_assignable_user(
        ws_harness, "au-bnd-ok", name="배정가능", email="ok@x.com"
    )

    r = _get_assignable(owner, ws_id)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [u["id"] for u in body["items"]]
    assert ids == [ok_id], f"배정 가능한 1명만 반환되어야 한다: {ids}"
    assert body["total"] == 1, f"total 도 필터를 반영해야 한다: {body['total']}"


# --- 5. narrow 봉투 누출 부재 (Req 1.2) ---------------------------------------


def test_narrow_envelope_exposes_only_id_name_email(ws_harness):
    """응답 사용자 객체는 id/name/email 만 — 계정 필드 누출이 HTTP 경계에서 부재 (Req 1.2).

    직렬화가 스키마 선언 필드로 한정되는지를 실제 응답 JSON 키로 검증한다: login_id·
    password_hash·is_admin/is_active/is_deleted·created_at/updated_at 이 **없어야** 한다.
    email null 사용자도 포함되며 email 키는 존재하되 null 이다(Req 1.3).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "au-nar-owner", name="오너")
    owner = ws_harness.login("au-nar-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "narrow 공간")

    with_email = _seed_assignable_user(
        ws_harness, "au-nar-1", name="이메일있음", email="present@example.com"
    )
    without_email = _seed_assignable_user(
        ws_harness, "au-nar-2", name="이메일없음", email=None
    )

    r = _get_assignable(owner, ws_id)
    assert r.status_code == 200, r.text
    items = {u["id"]: u for u in r.json()["items"]}
    assert set(items.keys()) == {with_email, without_email}

    leak_keys = {
        "login_id",
        "password_hash",
        "is_admin",
        "is_active",
        "is_deleted",
        "created_at",
        "updated_at",
    }
    for uid, user_obj in items.items():
        assert set(user_obj.keys()) == {"id", "name", "email"}, (
            f"narrow 봉투는 id/name/email 만 노출: {sorted(user_obj.keys())}"
        )
        assert leak_keys.isdisjoint(user_obj.keys()), (
            f"계정 필드가 누출되면 안 된다: {sorted(set(user_obj.keys()) & leak_keys)}"
        )

    # email 유무 각각 올바르게 표현(Req 1.3 정합: null 도 제외하지 않음).
    assert items[with_email]["email"] == "present@example.com"
    assert items[without_email]["email"] is None
