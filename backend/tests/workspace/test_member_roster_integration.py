"""멤버 로스터 조회 엔드포인트 게이팅·anti-enumeration 통합 테스트 (Task 3.1).

마이그레이션된 DB + 부팅 앱(:func:`ws_harness`)에서 owner-gated 조회 엔드포인트
``GET /workspaces/{id}/members`` 를 mock 없이 진짜 ASGI 요청·세션 쿠키 인증으로
검증한다(design.md §Testing Strategy → Integration Tests, §System Flows → 로스터 조회
게이팅, §Security Considerations).

이 엔드포인트는 task 2.2 에서 이미 커밋되어 통과하므로 본 파일은 **이미 배포된 동작을
검증하는 커버리지 task** 다(RED→GREEN 아님, assignable 통합 테스트와 동일 성격). 대신
게이팅이 trivially 통과가 아니라 실질 판정됨(예: member 가 실제 role 로 등록되었음에도
진짜 403)을 HTTP 경계에서 단언한다. no-op 게이트라면 member/비-멤버/미인증/미존재 WS
케이스가 모두 200 을 받아 이 파일의 단언들이 실패하므로 vacuous 통과가 아니다.

게이팅은 s23 assignable 과 **동일**하다(둘 다 ``require_ws_role(Role.OWNER)`` 부착):
owner→200, member→403, 비-멤버→403, admin(비-owner)→200(INV-3 override, 요청자
owner 여부와 무관), 미인증(세션 없음·무효)→401, 미존재 WS→403(404 아님, anti-enumeration).

검증 대상(tasks.md 3.1 + design.md):
- 게이팅 매트릭스: owner→200, member→403, 비-멤버→403, admin(비-owner)→200,
  미인증→401 (Req 2.1·2.2·2.3·2.5).
- 무효 세션 쿠키(변조)→401 (Req 2.1, 미인증 경계 세분).
- 존재하지 않는 워크스페이스→403(≠404, 존재 노출 안 함, anti-enumeration) (Req 2.4).

로스터 divergence(비활성·삭제·owner 포함)·narrow 봉투(4-필드)·pagination 케이스는
task 3.2 가 이 파일에 **추가**한다(본 아래 §3~§6, 게이팅+anti-enumeration 은 §1~§2 가 소유).
"""

from datetime import datetime

from app.common.security import hash_password
from app.models import User

# 로스터 시드용 기본 비밀번호(로그인에 쓰지 않지만 password_hash 를 실 해시로 채운다).
_SEED_PASSWORD = "roster-seed-pass-123"


def _create_workspace(client, name: str = "로스터 공간") -> int:
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


def _get_members(client, ws_id: int, *, limit=None, offset=None):
    """``GET /workspaces/{id}/members`` 를 (선택적 쿼리와 함께) 호출한다."""
    params = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return client.get(f"/workspaces/{ws_id}/members", params=params)


def _seed_user(
    harness,
    login_id: str,
    *,
    name: str,
    email: str | None,
    is_active: bool = True,
    is_deleted: bool = False,
) -> int:
    """멤버 후보 사용자를 ORM 으로 직접 커밋 시드하고 그 id 를 반환한다(SETUP 헬퍼).

    :func:`_add_member` 로 워크스페이스에 편입할 사용자를 email·상태 flag 정밀 제어와 함께
    만든다(assignable 통합 테스트의 ``_seed_assignable_user`` 미러). 이 사용자들은 로그인하지
    않고 로스터 대상으로만 쓰이므로 admin ``POST /admin/users`` 경로 대신 ORM 시드로 email·
    is_active·is_deleted 를 직접 제어한다. 앱은 override 된 별도 세션(별도 커넥션)으로 조회하므로
    commit 이 필수다. 로스터는 소프트삭제 미필터이므로 비활성·삭제 사용자도 멤버로 남는다(Req 1.5).
    """
    session = harness.session_local()
    try:
        user = User(
            login_id=login_id,
            password_hash=hash_password(_SEED_PASSWORD),
            name=name,
            email=email,
            is_admin=False,
            is_active=is_active,
            is_deleted=is_deleted,
            created_at=datetime.utcnow(),
        )
        session.add(user)
        session.commit()
        return user.id
    finally:
        session.close()


# --- 1. 게이팅 매트릭스 (Req 2.1·2.2·2.3·2.5) --------------------------------


def test_gating_matrix_owner_admin_pass_others_rejected(ws_harness):
    """owner·admin→200, member·비멤버→403, 미인증→401 (Req 2.1·2.2·2.3·2.5).

    게이팅이 trivially 통과가 아니라 실질 판정임을 증명한다: member 는 실제 role 로
    등록되었음에도 OWNER 미달로 진짜 403 을 받고, owner·admin(비-owner 멤버)만 200 을 받는다.
    admin override 는 요청자가 해당 WS 의 owner 인지와 무관하다(INV-3).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "mr-owner", name="오너")
    member_id = ws_harness.create_user(admin, "mr-member", name="멤버")
    ws_harness.create_user(admin, "mr-nonmember", name="비멤버")

    owner = ws_harness.login("mr-owner", "ws-member-pass-123")
    member = ws_harness.login("mr-member", "ws-member-pass-123")
    nonmember = ws_harness.login("mr-nonmember", "ws-member-pass-123")

    ws_id = _create_workspace(owner, "게이팅 공간")
    # member 를 실제 role 로 등록 → 게이트가 실제 role 로 판정하게 만든다.
    assert _add_member(owner, ws_id, member_id, "member").status_code == 201

    # owner ≥ OWNER → 200 (Req 2.5 의 대비군: 정상 owner 는 통과).
    r_owner = _get_members(owner, ws_id)
    assert r_owner.status_code == 200, f"owner 는 200: {r_owner.text}"
    assert set(r_owner.json().keys()) == {"items", "total"}

    # member 는 OWNER 미달 → 진짜 403 (trivial 통과 아님, Req 5.4).
    r_member = _get_members(member, ws_id)
    assert r_member.status_code == 403, f"member 는 403: {r_member.text}"
    assert r_member.json()["code"] == "forbidden"

    # 비멤버(로그인했으나 멤버 아님) → 403 (Req 2.3).
    r_non = _get_members(nonmember, ws_id)
    assert r_non.status_code == 403, f"비멤버는 403: {r_non.text}"
    assert r_non.json()["code"] == "forbidden"

    # admin(비-owner 멤버) → override 로 200 — 요청자 owner 여부와 무관 (Req 2.5, INV-3).
    r_admin = _get_members(admin, ws_id)
    assert r_admin.status_code == 200, f"admin override 는 200: {r_admin.text}"
    assert set(r_admin.json().keys()) == {"items", "total"}

    # 미인증(세션 없음) → 401 (Req 2.1).
    anon = ws_harness.new_client()
    r_anon = _get_members(anon, ws_id)
    assert r_anon.status_code == 401, f"미인증은 401: {r_anon.text}"
    assert r_anon.json()["code"] == "unauthenticated"


def test_invalid_session_cookie_returns_401(ws_harness):
    """무효 세션 쿠키(변조)로도 401 이다 (Req 2.1, 미인증 경계 세분)."""
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "mr-owner2", name="오너")
    owner = ws_harness.login("mr-owner2", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "무효세션 공간")

    bad = ws_harness.new_client()
    bad.cookies.set(ws_harness.session_cookie_name, "not-a-valid-session-token")
    r = _get_members(bad, ws_id)
    assert r.status_code == 401, f"무효 세션은 401: {r.status_code} {r.text}"
    assert r.json()["code"] == "unauthenticated"


# --- 2. 존재하지 않는 워크스페이스 → 403 (anti-enumeration, Req 2.4) ----------


def test_nonexistent_workspace_returns_403_not_404(ws_harness):
    """존재하지 않는 워크스페이스 조회는 403(비-멤버 게이트) — 404 로 존재 노출 안 함 (Req 2.4).

    로그인한 non-admin 사용자가 존재하지 않는 id 를 조회하면 게이트 단계에서 비-멤버 →
    403 이어야 한다. 404 였다면 워크스페이스 존재 여부가 열거 가능해진다(anti-enumeration 위반).
    """
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "mr-probe", name="탐침")
    prober = ws_harness.login("mr-probe", "ws-member-pass-123")

    missing_ws_id = 9_999_999
    r = _get_members(prober, missing_ws_id)
    assert r.status_code == 403, (
        f"존재하지 않는 워크스페이스는 403 이어야 한다(404 아님): {r.status_code} {r.text}"
    )
    assert r.json()["code"] == "forbidden"
    assert r.status_code != 404, "404 는 존재를 노출하므로 금지(anti-enumeration)"


# --- 3. 로스터 divergence — 비활성·삭제 멤버 포함 + owner 자신 포함 (Req 1.1·1.3·1.5) ---


def test_roster_includes_inactive_deleted_members_and_owner_self(ws_harness):
    """비활성·삭제 상태 멤버가 role 과 함께 로스터에 존재하고 owner 자신도 포함된다(Req 1.3·1.5).

    이것이 이 기능의 존재 이유(assignable 의 **정반대** 필터)를 잠그는 회귀 락이다: assignable
    이라면 비활성·삭제 사용자는 배제되지만, 로스터는 소프트삭제 필터를 적용하지 않으므로 이들이
    각자의 role 과 함께 반드시 나타나야 한다(Req 1.5, design.md §결정적 divergence). 또한 조회를
    요청한 owner 자신의 멤버십 항목도 로스터에 포함된다(Req 1.3).
    """
    admin = ws_harness.login_admin()
    owner_id = ws_harness.create_user(admin, "mr-div-owner", name="오너")
    owner = ws_harness.login("mr-div-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "divergence 공간")

    # 비활성 사용자·삭제 사용자를 ORM 시드 → 각각 role 로 멤버 편입(soft-delete 미필터 검증).
    inactive_id = _seed_user(
        ws_harness, "mr-div-inactive", name="비활성", email="inact@x.com", is_active=False
    )
    deleted_id = _seed_user(
        ws_harness, "mr-div-deleted", name="삭제", email="del@x.com", is_deleted=True
    )
    assert _add_member(owner, ws_id, inactive_id, "member").status_code == 201
    assert _add_member(owner, ws_id, deleted_id, "member").status_code == 201

    r = _get_members(owner, ws_id)
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {item["user_id"]: item for item in body["items"]}

    # owner 자신 포함(Req 1.3) — 생성자는 owner role 로 자동 등록됨.
    assert owner_id in by_id, f"owner 자신이 로스터에 포함되어야 한다: {sorted(by_id)}"
    assert by_id[owner_id]["role"] == "owner"

    # 비활성·삭제 멤버가 role 과 함께 존재(Req 1.5) — assignable 이면 배제될 대상.
    assert inactive_id in by_id, "비활성 멤버는 로스터에 role 과 함께 존재해야 한다(soft-delete 미필터)"
    assert by_id[inactive_id]["role"] == "member"
    assert deleted_id in by_id, "삭제 멤버는 로스터에 role 과 함께 존재해야 한다(soft-delete 미필터)"
    assert by_id[deleted_id]["role"] == "member"

    # total 은 소속 멤버 전체 개수(owner + 2) — 소프트삭제로 감소하지 않는다.
    assert body["total"] == 3, f"소속 멤버 전량(3)이어야 한다: {body['total']}"
    assert set(by_id) == {owner_id, inactive_id, deleted_id}


# --- 4. narrow 봉투 — 정확히 {user_id, name, email, role}, email null 포함 (Req 1.2·2.6) ---


def test_narrow_envelope_exposes_only_user_id_name_email_role(ws_harness):
    """각 item 키가 정확히 `{user_id, name, email, role}` 이고 계정 필드 누출이 부재(Req 1.2·2.6).

    직렬화가 스키마 선언 4필드로 한정되는지를 실제 응답 JSON 키로 검증한다: login_id·
    password_hash·상태 flag(is_admin/is_active/is_deleted)·타임스탬프(created_at/updated_at)가
    **없어야** 한다. email null 멤버도 로스터에 포함되며 email 키는 존재하되 null 이다(Req 1.2).
    로스터 item 의 식별 키는 `user_id`(assignable 의 `id` 와 다름)이며 `role` 필드가 추가된다.
    """
    admin = ws_harness.login_admin()
    owner_id = ws_harness.create_user(admin, "mr-nar-owner", name="오너")
    owner = ws_harness.login("mr-nar-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "narrow 공간")

    with_email = _seed_user(
        ws_harness, "mr-nar-1", name="이메일있음", email="present@example.com"
    )
    without_email = _seed_user(ws_harness, "mr-nar-2", name="이메일없음", email=None)
    assert _add_member(owner, ws_id, with_email, "member").status_code == 201
    assert _add_member(owner, ws_id, without_email, "member").status_code == 201

    r = _get_members(owner, ws_id)
    assert r.status_code == 200, r.text
    by_id = {item["user_id"]: item for item in r.json()["items"]}
    assert set(by_id) == {owner_id, with_email, without_email}

    leak_keys = {
        "id",
        "login_id",
        "password_hash",
        "is_admin",
        "is_active",
        "is_deleted",
        "created_at",
        "updated_at",
        "workspace_id",
    }
    for uid, item in by_id.items():
        assert set(item.keys()) == {"user_id", "name", "email", "role"}, (
            f"narrow 봉투는 정확히 4필드만 노출: {sorted(item.keys())}"
        )
        assert leak_keys.isdisjoint(item.keys()), (
            f"계정/내부 필드가 누출되면 안 된다: {sorted(set(item.keys()) & leak_keys)}"
        )

    # email 유무 각각 올바르게 표현(null 멤버도 제외하지 않고 email: null 로 포함).
    assert by_id[with_email]["email"] == "present@example.com"
    assert by_id[without_email]["email"] is None


# --- 5. pagination — total > 페이지 크기, 결정적 순서, 경계 일관 (Req 1.4·1.6) ---


def test_pagination_limit_offset_items_and_total_consistent(ws_harness):
    """total > 페이지 크기일 때 limit/offset 경계에서 items·total 이 일관·결정적이다(Req 1.4·1.6).

    total 은 항상 소속 멤버 전체 개수(owner + 시드 5 = 6)이고, items 는 limit 로 상한되며 offset
    이 슬라이스를 올바르게 이동시킨다. 순서는 결정적(User.id 오름차순)이어야 페이지가 겹치지 않고
    전체를 정확히 커버한다(Req 1.6). offset 이 총수를 넘으면 빈 items·불변 total.
    """
    admin = ws_harness.login_admin()
    owner_id = ws_harness.create_user(admin, "mr-pg-owner", name="오너")
    owner = ws_harness.login("mr-pg-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "페이지 공간")

    seeded_ids = [
        _seed_user(ws_harness, f"mr-pg-{i}", name=f"멤버{i}", email=f"pg{i}@example.com")
        for i in range(5)
    ]
    for uid in seeded_ids:
        assert _add_member(owner, ws_id, uid, "member").status_code == 201

    # 결정적 순서는 User.id 오름차순 → 기대 전체 순서(owner 포함 6명).
    expected_order = sorted([owner_id] + seeded_ids)
    assert len(expected_order) == 6

    # 첫 페이지: limit=2 → items 2개, total 6.
    r0 = _get_members(owner, ws_id, limit=2, offset=0)
    assert r0.status_code == 200, r0.text
    body0 = r0.json()
    assert body0["total"] == 6, f"total 은 소속 멤버 전량(6): {body0['total']}"
    assert len(body0["items"]) == 2, "items 는 limit 로 상한된다"
    page0 = [item["user_id"] for item in body0["items"]]
    assert page0 == expected_order[0:2], f"첫 페이지 슬라이스: {page0}"

    # 두번째 페이지: offset=2.
    r1 = _get_members(owner, ws_id, limit=2, offset=2)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["total"] == 6, "total 은 offset 과 무관하게 전체 개수"
    page1 = [item["user_id"] for item in body1["items"]]
    assert page1 == expected_order[2:4], f"두번째 페이지 슬라이스: {page1}"

    # 세번째 페이지: offset=4 → 남은 2개(끝 경계).
    r2 = _get_members(owner, ws_id, limit=2, offset=4)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["total"] == 6
    page2 = [item["user_id"] for item in body2["items"]]
    assert page2 == expected_order[4:6], f"세번째 페이지 슬라이스: {page2}"

    # 페이지들이 겹치지 않고 전체를 정확히 커버(결정적 순서 검증).
    assert page0 + page1 + page2 == expected_order

    # 동일 파라미터 반복 조회 시 안정 순서(Req 1.6).
    again = [item["user_id"] for item in _get_members(owner, ws_id, limit=2, offset=0).json()["items"]]
    assert again == page0, "동일 파라미터 반복 조회는 안정 순서여야 한다"

    # offset 이 총수를 넘으면 빈 items·불변 total.
    r3 = _get_members(owner, ws_id, limit=2, offset=10)
    assert r3.status_code == 200, r3.text
    assert r3.json()["items"] == []
    assert r3.json()["total"] == 6, "offset 초과여도 total 은 불변"


def test_invalid_limit_and_offset_return_422(ws_harness):
    """limit=0·offset=-1 등 범위 위반은 FastAPI 가 422 로 거부한다(Req 1.4·1.6 경계)."""
    admin = ws_harness.login_admin()
    ws_harness.create_user(admin, "mr-422-owner", name="오너")
    owner = ws_harness.login("mr-422-owner", "ws-member-pass-123")
    ws_id = _create_workspace(owner, "422 공간")

    assert _get_members(owner, ws_id, limit=0).status_code == 422, "limit=0(<1)→422"
    assert _get_members(owner, ws_id, offset=-1).status_code == 422, "offset=-1(<0)→422"
