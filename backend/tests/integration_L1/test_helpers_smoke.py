"""시나리오 헬퍼 스모크 테스트 (Task 1.2 관찰 가능한 완료 기준).

``helpers.py`` 의 얇은 라우트 래퍼가 실제 결합 환경에서 동작함을 증명한다:

1. 고유 ``login_id`` 생성기가 서로 다른(비충돌) id 를 낸다.
2. admin 인증 클라이언트로 :func:`create_user` 가 실제 ``POST /admin/users`` 를
   태워 201 + 생성된 user id 를 돌려준다.
3. :func:`attempt_login` 이 생성된 자격으로 로그인 시 200 + 세션 쿠키를 발급한다.
4. :func:`attempt_login` 은 상태를 **내부에서 단언하지 않으므로** 잘못된 비밀번호에도
   예외 없이 401 응답 객체를 그대로 surfacing 한다(음성 경로 래퍼 계약 증명).

이 스모크가 통과하면 후속 태스크(2.2/2.3)가 이 헬퍼 위에서 cross-spec 시나리오를
간결하게 표현할 수 있음이 보장된다.
"""

from tests.integration_L1.helpers import (
    attempt_login,
    create_user,
    unique_login_id,
)


def test_unique_login_id_generator_yields_distinct_ids(harness):
    """고유 login_id 생성기는 서로 다른 id 를 낸다(공유 DB 충돌 방지)."""
    first = unique_login_id()
    second = unique_login_id()

    assert first != second
    # VARCHAR(255) 경계 안에 머문다.
    assert len(first) <= 255 and len(second) <= 255


def test_helper_created_user_can_log_in(harness):
    """헬퍼로 만든 신규 사용자가 그 자격으로 로그인해 200 + 세션을 받는다."""
    admin = harness.login_admin()
    login_id = unique_login_id()
    password = "smoke-user-pw-123"

    user_id = create_user(admin, login_id, password, name="스모크 사용자")
    assert isinstance(user_id, int)

    resp = attempt_login(harness, login_id, password)

    assert resp.status_code == 200, f"신규 사용자 로그인 200 이어야 한다: {resp.text}"
    # 세션 쿠키가 실제로 발급되었다.
    assert harness.session_cookie_name in resp.cookies


def test_attempt_login_surfaces_failure_without_asserting(harness):
    """attempt_login 은 실패를 내부 단언 없이 그대로 반환한다(음성 경로 가능)."""
    admin = harness.login_admin()
    login_id = unique_login_id()
    create_user(admin, login_id, "correct-pw-123", name="음성 경로 사용자")

    resp = attempt_login(harness, login_id, "wrong-password-xxxx")

    # 내부에서 200 을 단언하지 않으므로 401 이 예외 없이 표면화된다(anti-enumeration).
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"
    # 실패 로그인은 세션을 발급하지 않는다.
    assert harness.session_cookie_name not in resp.cookies
