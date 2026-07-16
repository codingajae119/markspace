"""계정 생명주기 ↔ 로그인 경계 스위트 (Task 2.2 / Req 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 5.1, 5.2, 6.1, 6.2).

이 스위트는 이번 계층에서 처음 결합되는 **cross-spec 경계**를 검증한다: s03(admin)가 계정
상태를 바꾸면 s02(login/auth)가 로그인 경로에서 그 결과를 관찰한다. 두 spec 은 오직 `user`
테이블을 통해서만 결합하며, 모든 시나리오는 mock 없이 실제 라우트 + 실제 서명 쿠키 세션
위에서 실행된다(design.md §cross-spec 경계 e2e · §AccountLifecycleLoginSuite).

## anti-enumeration — 실패 로그인은 사유 불문 uniform 401
로그인 실패(미존재·오비번·비활동·삭제)는 모두 byte-identical **401 `unauthenticated`**(세션
쿠키 없음)로 표면화된다. 이 스위트는 실패를 항상 401 로 **동일하게** 단언하고 사유별로 다른
코드/메시지를 단언하지 않으며, 실패 시 세션 쿠키의 **부재**를, 성공 시 200 + 세션 쿠키의
**존재**를 단언한다(design.md §Security Considerations, requirements §계정 열거 방지).

## 대상 사용자는 항상 비-admin
admin 계정의 비활동/삭제는 s03 가 409 로 차단하므로, 상태 전이 시나리오의 대상은 항상
헬퍼로 생성한 **비-admin** 사용자다.

하네스(:func:`~tests.integration_L1.conftest.harness`)가 제공하는 실 결합 환경 위에서만
동작하며, 시나리오마다 :func:`helpers.unique_login_id` 로 고유 login_id 를 써서 공유 DB 에서
충돌하지 않는다.
"""

from tests.integration_L1 import helpers


# --- Req 3.1: 생성 → 로그인 성공 -------------------------------------------------


def test_created_user_can_log_in_and_session_issued(harness):
    """admin 생성 비-admin 사용자가 올바른 자격으로 로그인 → 200 + 세션 발급 (Req 3.1)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("member")
    helpers.create_user(admin, login_id, name="생성 사용자")

    resp = helpers.attempt_login(harness, login_id, helpers.DEFAULT_PASSWORD)

    assert resp.status_code == 200, f"생성 직후 로그인 200 이어야 한다: {resp.text}"
    # 성공 로그인은 세션 쿠키를 발급한다.
    assert harness.session_cookie_name in resp.cookies
    # 응답 본문은 민감 필드를 노출하지 않는다.
    assert "password_hash" not in resp.json()


# --- Req 3.2, 3.3: admin 비밀번호 재설정 → 새 비번 로그인 / 옛 비번 거부 --------------


def test_admin_reset_password_new_login_succeeds_old_rejected(harness):
    """admin 재설정 후 새 비번 로그인 200(3.2) · 옛 비번 로그인 401(3.3)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("reset")
    old_password = helpers.DEFAULT_PASSWORD
    new_password = "admin-reset-new-pw-456"
    user_id = helpers.create_user(admin, login_id, old_password, name="재설정 사용자")

    helpers.admin_reset_password(admin, user_id, new_password)

    # 3.2 — 새 비밀번호로 로그인하면 성공하고 세션이 발급된다.
    new_resp = helpers.attempt_login(harness, login_id, new_password)
    assert new_resp.status_code == 200, f"새 비번 로그인 200 이어야 한다: {new_resp.text}"
    assert harness.session_cookie_name in new_resp.cookies

    # 3.3 — 재설정 이전의 옛 비밀번호로는 401 로 거부되고 세션이 없다(uniform 401).
    old_resp = helpers.attempt_login(harness, login_id, old_password)
    assert old_resp.status_code == 401
    assert old_resp.json()["code"] == "unauthenticated"
    assert harness.session_cookie_name not in old_resp.cookies


# --- Req 4.1: 비활동 → 로그인 거부 -----------------------------------------------


def test_inactive_user_login_rejected_no_session(harness):
    """admin `is_active=false` 처리 후 올바른 자격 로그인 → 401, 세션 미발급 (Req 4.1)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("inactive")
    user_id = helpers.create_user(admin, login_id, name="비활동 사용자")

    helpers.set_active(admin, user_id, False)

    resp = helpers.attempt_login(harness, login_id, helpers.DEFAULT_PASSWORD)

    # 자격 증명이 올발라도 비활동이면 uniform 401 로 거부되고 세션이 발급되지 않는다.
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
    assert harness.session_cookie_name not in resp.cookies


# --- Req 4.2: 삭제 → 로그인 거부 -------------------------------------------------


def test_deleted_user_login_rejected(harness):
    """admin `is_deleted=true` 처리 후 올바른 자격 로그인 → 401, 세션 미발급 (Req 4.2)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("deleted")
    user_id = helpers.create_user(admin, login_id, name="삭제 사용자")

    helpers.set_deleted(admin, user_id, True)

    resp = helpers.attempt_login(harness, login_id, helpers.DEFAULT_PASSWORD)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
    assert harness.session_cookie_name not in resp.cookies


# --- Req 4.3: 보유 세션 무효화 (상태 전이 후 held 세션 401) --------------------------


def test_held_session_revoked_after_state_change(harness):
    """사용자가 로그인해 라이브 세션을 보유한 뒤 admin 이 삭제 처리하면, 동일 held 세션의
    후속 보호 요청(`/auth/me`)이 401 로 거부됨을 확인한다 (Req 4.3).

    이는 s01 `get_current_user` 가 매 요청마다 신규 DB 세션으로 커밋된 is_active/is_deleted
    flag 를 재확인하므로, 상태 변경 후 held 쿠키가 더 이상 존중되지 않음을 증명한다.
    """
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("held")
    user_id = helpers.create_user(admin, login_id, name="보유세션 사용자")

    # 먼저 사용자가 로그인해 라이브 세션(인증 클라이언트)을 보유한다.
    client = harness.login(login_id, helpers.DEFAULT_PASSWORD)
    # sanity: 상태 전이 전에는 보호 요청이 200 이다.
    before = client.get("/auth/me")
    assert before.status_code == 200

    # admin 이 그 사용자를 삭제 처리(상태 전이)한다.
    helpers.set_deleted(admin, user_id, True)

    # 동일 held 세션 쿠키의 후속 보호 요청은 401 로 거부된다.
    me = client.get("/auth/me")
    assert me.status_code == 401
    assert me.json()["code"] == "unauthenticated"


# --- Req 5.1: 재활성화(삭제 flag 되돌림) → 로그인 재성공 -----------------------------


def test_undelete_restores_login(harness):
    """삭제된 사용자의 삭제 flag 를 되돌리면(`is_deleted=false`) 다시 로그인 200 (Req 5.1)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("undelete")
    user_id = helpers.create_user(admin, login_id, name="재활성화 사용자")

    helpers.set_deleted(admin, user_id, True)
    # 삭제 상태에서는 거부된다(전제 확인).
    denied = helpers.attempt_login(harness, login_id, helpers.DEFAULT_PASSWORD)
    assert denied.status_code == 401

    # 삭제 flag 를 되돌리면 다시 로그인에 성공한다.
    helpers.set_deleted(admin, user_id, False)
    resp = helpers.attempt_login(harness, login_id, helpers.DEFAULT_PASSWORD)

    assert resp.status_code == 200, f"재활성화 후 로그인 200 이어야 한다: {resp.text}"
    assert harness.session_cookie_name in resp.cookies


# --- Req 5.2: 상태 독립성 (삭제 flag 되돌림이 is_active 를 자동 복원하지 않음) -----------


def test_undelete_does_not_reactivate_when_inactive(harness):
    """is_active=False 이면서 is_deleted=True 인 사용자의 삭제 flag 만 되돌려도(is_active 유지)
    여전히 로그인 401 임을 확인한다 — 두 flag 는 독립적이다 (Req 5.2)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("independent")
    user_id = helpers.create_user(admin, login_id, name="상태독립 사용자")

    # 두 flag 를 모두 세운다: 비활동 + 삭제.
    helpers.set_active(admin, user_id, False)
    helpers.set_deleted(admin, user_id, True)

    # 오직 삭제 flag 만 되돌린다(is_active 는 False 로 유지).
    restored = helpers.set_deleted(admin, user_id, False)
    assert restored["is_active"] is False, "삭제 flag 되돌림이 is_active 를 자동 복원하면 안 된다"
    assert restored["is_deleted"] is False

    # 삭제는 되돌렸지만 여전히 비활동이므로 로그인은 uniform 401 로 거부된다.
    resp = helpers.attempt_login(harness, login_id, helpers.DEFAULT_PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
    assert harness.session_cookie_name not in resp.cookies


# --- Req 6.1, 6.2: 본인 비밀번호 변경 → 새 비번 로그인 / 옛 비번 거부 -----------------


def test_self_change_password_new_login_succeeds_old_rejected(harness):
    """본인 비밀번호 변경 후 새 비번 로그인 200(6.1) · 옛 비번 로그인 401(6.2)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("selfchg")
    old_password = helpers.DEFAULT_PASSWORD
    new_password = "self-changed-new-pw-789"
    helpers.create_user(admin, login_id, old_password, name="본인변경 사용자")

    # 사용자가 옛 비번으로 로그인해 인증 세션을 얻고, 본인 비밀번호를 변경한다.
    client = harness.login(login_id, old_password)
    helpers.self_change_password(client, old_password, new_password)

    # 6.1 — 새 비밀번호로 로그인하면 성공하고 세션이 발급된다.
    new_resp = helpers.attempt_login(harness, login_id, new_password)
    assert new_resp.status_code == 200, f"새 비번 로그인 200 이어야 한다: {new_resp.text}"
    assert harness.session_cookie_name in new_resp.cookies

    # 6.2 — 변경 이전의 옛 비밀번호로는 401 로 거부되고 세션이 없다(uniform 401).
    old_resp = helpers.attempt_login(harness, login_id, old_password)
    assert old_resp.status_code == 401
    assert old_resp.json()["code"] == "unauthenticated"
    assert harness.session_cookie_name not in old_resp.cookies
