"""L1 하네스 스모크 테스트 (Task 1.1 관찰 가능한 완료 기준).

하네스(:func:`harness`)가 마이그레이션된 DB + 부팅 앱 + 시드 admin + 세션 유지
클라이언트를 실제로 제공함을 end-to-end 로 증명한다. 시드 admin 으로 s02 실제 로그인
흐름(``POST /auth/login``)을 태운 뒤, 세션 쿠키가 실린 동일 클라이언트로
``GET /auth/me`` 가 200 을 돌려주고 본문이 그 admin 을 식별하는지 확인한다.

이 스모크가 통과하면 후속 태스크(계약 대조·경계·INV-4 스위트)가 이 하네스 위에서 실제
결합 e2e 를 구성할 수 있음이 보장된다.
"""


def test_harness_admin_can_reach_auth_me(harness):
    """시드 admin 로그인 → 동일 세션으로 GET /auth/me 200 + admin 식별 (하네스 e2e 증명)."""
    client = harness.login_admin()

    # 로그인 세션 쿠키가 클라이언트에 실제로 실려 있어야 한다(세션 유지 경로 증명).
    assert harness.session_cookie_name in client.cookies

    resp = client.get("/auth/me")

    assert resp.status_code == 200, f"admin 세션으로 /auth/me 200 이어야 한다: {resp.text}"
    body = resp.json()
    # 본문이 시드된 admin 을 식별한다.
    assert body["login_id"] == harness.admin_login_id
    assert body["is_admin"] is True
    # 민감 필드는 절대 노출되지 않는다.
    assert "password_hash" not in body
