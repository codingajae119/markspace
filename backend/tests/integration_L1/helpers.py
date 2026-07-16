"""cross-spec 시나리오 헬퍼 — 실제 라우트 호출의 얇은 래퍼 (Task 1.2 / Req 1.1, 3.1).

후속 스위트(계정 생명주기↔로그인 경계 2.2 · INV-4 보존 2.3)가 생성→로그인→상태 전이→
재로그인 같은 cross-spec 시나리오를 간결하게 표현하도록, s02 auth + s03 admin 의 **실제**
엔드포인트를 호출하는 얇은 래퍼를 모은다. mock 이 아니라 부팅된 앱의 실 라우트를 태운다.

## 설계 규칙 (음성 경로 가능성 보존)
- **attempt 계열** (:func:`attempt_login`): 후속 테스트가 같은 래퍼로 성공(200)과 실패(401)를
  둘 다 단언해야 하므로 **응답 객체를 그대로 반환하고 상태를 내부에서 단언하지 않는다**.
  로그인 실패(미존재/오비번/비활동/삭제)는 모두 byte-identical 401 (anti-enumeration)이며,
  호출자가 200 또는 401 을 선택적으로 단언한다.
- **setup 계열** (:func:`create_user`·:func:`set_active`·:func:`set_deleted`·
  :func:`admin_reset_password`·:func:`self_change_password`): 시나리오 준비상 항상 성공하는
  단계이므로 성공 상태를 내부에서 단언하고 유용한 값(생성 id, 파싱된 UserRead dict)을
  돌려주어 시나리오 코드를 읽기 쉽게 한다.

## 하네스와의 역할 분담
하네스(:class:`~tests.integration_L1.conftest.L1Harness`)는 이미
``login`` / ``login_admin`` (200 단언 후 인증 클라이언트 반환)을 제공한다. 이 모듈은 그것을
**중복하지 않고 보완**한다: setup/attempt 래퍼는 이미 인증된 admin ``TestClient`` (호출자가
``harness.login_admin()`` 으로 얻음) 또는 하네스 자체를 인자로 받는다.

엔드포인트 계약 (s01 단일 소스):
- ``POST /admin/users`` (admin)      → 201 ``UserRead``
- ``PATCH /admin/users/{id}`` (admin) → 200 ``UserRead`` (is_active/is_deleted/name/email 부분 갱신)
- ``POST /admin/users/{id}/password`` (admin) → 204
- ``POST /auth/login`` (public)      → 200 ``AuthUserRead`` + 세션 / 401 ``unauthenticated``
- ``POST /auth/password`` (auth)     → 204 / 422
"""

from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

# min_length 8 정책을 만족하는 기본 비밀번호(테스트 전용, 실제 자격 아님).
DEFAULT_PASSWORD = "helper-default-pw-123"


def unique_login_id(prefix: str = "u") -> str:
    """공유 ``notion_lite_test`` DB 에서 충돌하지 않는 고유 ``login_id`` 를 생성한다.

    ``harness`` fixture 인스턴스마다 DB 가 drop+migrate 되지만, 한 인스턴스 안에서 여러
    사용자를 만드는 시나리오의 안전과 명료성을 위해 항상 고유 id 를 낸다. 결과는
    ``VARCHAR(255)`` 경계 안에 머문다(prefix + '-' + 12 hex).
    """
    return f"{prefix}-{uuid4().hex[:12]}"


def create_user(
    admin: TestClient,
    login_id: str,
    password: str = DEFAULT_PASSWORD,
    *,
    name: str,
    email: str | None = None,
) -> int:
    """admin 인증 클라이언트로 ``POST /admin/users`` 를 태워 비-admin 사용자를 만든다.

    SETUP 헬퍼 — 201 을 내부에서 단언하고 생성된 사용자의 ``id`` (int)를 반환한다.
    호출자는 ``admin = harness.login_admin()`` 로 얻은 인증 클라이언트를 넘긴다.
    """
    payload: dict[str, object] = {
        "login_id": login_id,
        "password": password,
        "name": name,
    }
    if email is not None:
        payload["email"] = email

    resp = admin.post("/admin/users", json=payload)
    assert resp.status_code == 201, (
        f"사용자 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    assert "password_hash" not in body, "UserRead 는 password_hash 를 노출하지 않는다"
    return body["id"]


def patch_user(admin: TestClient, user_id: int, **fields: object) -> dict:
    """admin 인증 클라이언트로 ``PATCH /admin/users/{id}`` 를 태워 필드를 부분 갱신한다.

    SETUP 헬퍼 — 200 을 내부에서 단언하고 파싱된 ``UserRead`` dict 를 반환한다.
    ``fields`` 는 ``name`` / ``email`` / ``is_active`` / ``is_deleted`` 의 부분집합.
    """
    resp = admin.patch(f"/admin/users/{user_id}", json=fields)
    assert resp.status_code == 200, (
        f"사용자 갱신 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def set_active(admin: TestClient, user_id: int, is_active: bool) -> dict:
    """대상 사용자의 ``is_active`` 를 전이한다(비활동↔활동). 파싱된 UserRead 반환."""
    return patch_user(admin, user_id, is_active=is_active)


def set_deleted(admin: TestClient, user_id: int, is_deleted: bool) -> dict:
    """대상 사용자의 ``is_deleted`` 를 전이한다(삭제↔복구). 파싱된 UserRead 반환."""
    return patch_user(admin, user_id, is_deleted=is_deleted)


def admin_reset_password(admin: TestClient, user_id: int, new_password: str) -> None:
    """admin 인증 클라이언트로 ``POST /admin/users/{id}/password`` 를 태워 비번을 재설정한다.

    SETUP 헬퍼 — 204 를 내부에서 단언한다(반환값 없음).
    """
    resp = admin.post(
        f"/admin/users/{user_id}/password", json={"new_password": new_password}
    )
    assert resp.status_code == 204, (
        f"admin 비밀번호 재설정 204 이어야 한다: {resp.status_code} {resp.text}"
    )


def self_change_password(
    user_client: TestClient, current_password: str, new_password: str
) -> None:
    """사용자 인증 클라이언트로 ``POST /auth/password`` 를 태워 본인 비번을 변경한다.

    SETUP 헬퍼 — 204 를 내부에서 단언한다. ``user_client`` 는 ``harness.login(...)`` 로
    얻은 인증 클라이언트여야 한다(본인 세션에서만 변경 가능).
    """
    resp = user_client.post(
        "/auth/password",
        json={"current_password": current_password, "new_password": new_password},
    )
    assert resp.status_code == 204, (
        f"본인 비밀번호 변경 204 이어야 한다: {resp.status_code} {resp.text}"
    )


def attempt_login(harness, login_id: str, password: str) -> Response:
    """``POST /auth/login`` 을 실제로 태우고 **응답 객체를 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — 후속 테스트가 같은 래퍼로 성공(200)과 실패(401)를 모두 단언할 수
    있도록 내부에서 상태를 단언하지 않는다. 매 호출마다 쿠키 오염이 없는 신규
    클라이언트를 쓴다(``harness.new_client()``). 성공 시 응답에 세션 쿠키가 실려 있고,
    실패(미존재/오비번/비활동/삭제)는 모두 401 ``unauthenticated`` 로 표면화된다.
    """
    client = harness.new_client()
    return client.post(
        "/auth/login", json={"login_id": login_id, "password": password}
    )
