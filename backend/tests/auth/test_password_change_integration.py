"""본인 비밀번호 변경 e2e + 계약·경계 검증 통합 테스트 (Task 4.3 / Req 4.1~4.6, 5.1~5.4).

MOCK 없이 마이그레이션된 실제 테스트 DB 위에서 ``create_app()`` 으로 실제 앱을 세우고
``TestClient`` 로 진짜 ASGI 요청을 흘려, 본인 비밀번호 변경의 전 결선(인증 게이트 →
현재 비밀번호 확인 → s01 ``hash_password`` 로 새 해시 갱신 → 저장)이 하나의 앱 컨텍스트에서
동작함을 검증한다(design.md §Testing Strategy Integration Tests "비밀번호 변경 e2e",
§Contract Consistency, §auth/API API Contract 1~4).

검증 항목:
- e2e: 로그인(이전 비번, 200) → 비밀번호 변경(204) → 이전 비번 로그인 실패(401) →
  새 비번 로그인 성공(200). 이는 저장 해시가 실제로 교체되었음을 증명한다(Req 4.1, 4.4).
- 현재 비밀번호 불일치(새 비번은 스키마 통과) → 422 ``unprocessable``(도메인 규칙 위반,
  validation_error 아님)(Req 4.2).
- 새 비밀번호 정책 위반(< 8자, 현재 비번 정확) → 422 ``validation_error`` + 비어있지 않은
  ``field_errors``(스키마 검증, s01 전역 핸들러)(Req 4.3).
- 미인증 비밀번호 변경(스키마 통과 본문) → 401 ``unauthenticated``(Req 4.6).
- 계약: 앱 OpenAPI 의 auth 경로가 s01 카탈로그 1~4(`/auth/login`·`/auth/logout`·`/auth/me`·
  `/auth/password`)와 정확히 일치(메서드 포함)(Req 5.2). 계정 생명주기·admin 재설정·자가
  가입/재설정 엔드포인트 부재(Req 5.3, 5.4). 모든 오류가 s01 ``ErrorResponse`` 형태(Req 5.1, 5.5).

격리: ``test_login_integration.py`` 의 확립된 패턴을 그대로 재사용한다. ``DB_NAME`` 을 전용
테스트 DB(``markspace_test``)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤 그 시점의
URL 로 새 엔진·세션 팩토리를 만든다. 앱 전체가 테스트 DB 를 쓰도록 ``get_db`` 를 override 하고,
종료 시 테이블 제거·엔진 dispose·환경변수·캐시를 원복해 개발 DB 누수를 막는다.
"""

import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base, get_db
from app.common.security import hash_password
from app.main import create_app
from app.models import User
from tests.support import logical_openapi_paths

TEST_DB_NAME = "markspace_test"

# 시드 사용자의 알려진 평문 비밀번호(해시는 s01 hash_password 로 생성).
OLD_PASSWORD = "correct-horse"
NEW_PASSWORD = "brand-new-pass-123"  # >= 8자, 정책 통과.
SHORT_PASSWORD = "short"  # < 8자, 정책 위반(422 validation_error).
WRONG_CURRENT = "definitely-not-the-current-password"


def _drop_everything(engine) -> None:
    """대상 DB 의 모든 테이블을 FK 무시하고 제거해 빈 상태로 만든다(견고한 teardown)."""
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        names = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ]
        for name in names:
            conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def _assert_error_response_shape(body: object) -> None:
    """관측된 에러 본문이 s01 ``ErrorResponse`` 형태를 따르는지 강제한다(Req 5.1, 5.5).

    최소 계약: 문자열 ``code`` 와 문자열 ``message`` 키를 가지며, ``field_errors`` 가
    존재하면 리스트다(s01 ``ErrorResponse`` = {code, message, field_errors?}).
    """
    assert isinstance(body, dict), f"에러 본문은 JSON 객체여야 한다: {body!r}"
    assert isinstance(body.get("code"), str), f"code 는 문자열이어야 한다: {body!r}"
    assert isinstance(body.get("message"), str), f"message 는 문자열이어야 한다: {body!r}"
    if "field_errors" in body and body["field_errors"] is not None:
        assert isinstance(body["field_errors"], list), (
            f"field_errors 가 존재하면 리스트여야 한다: {body!r}"
        )


class _Seed:
    """시나리오에서 참조할 앱 인스턴스·세션 쿠키 이름·시드 login_id 묶음."""

    def __init__(self, app, session_cookie_name):
        self.app = app
        self.session_cookie_name = session_cookie_name
        self.active_login_id = "alice"
        self.active_name = "앨리스"


@pytest.fixture
def seeded():
    """테스트 DB 를 마이그레이션·시드하고, get_db 를 override 한 실제 앱을 제공한다."""
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    TestSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    _drop_everything(engine)  # 시작 전 빈 상태 보증(격리 전제).
    Base.metadata.create_all(engine)  # 마이그레이션된 DB 계약을 물리적으로 생성.

    # 시드: 앱은 override 된 별도 세션으로 조회하므로 반드시 commit 한다.
    # 활성·미삭제 사용자 하나(비밀번호는 s01 hash_password 로 실제 저장 해시 생성, MOCK 없음).
    seed = TestSessionLocal()
    try:
        seed.add(
            User(
                login_id="alice",
                password_hash=hash_password(OLD_PASSWORD),
                name="앨리스",
                is_admin=False,
                is_active=True,
                is_deleted=False,
                created_at=datetime.utcnow(),
            )
        )
        seed.commit()
    finally:
        seed.close()

    # 실제 앱을 세우고, 앱 전체가 테스트 DB 를 쓰도록 get_db 를 override 한다.
    app = create_app()

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield _Seed(app=app, session_cookie_name=settings.session_cookie_name)
    finally:
        app.dependency_overrides.clear()
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


# --- e2e: 비밀번호 변경으로 저장 해시가 실제 교체됨 -------------------------------


def test_password_change_e2e_old_password_stops_working_new_works(seeded):
    """로그인 → 변경(204) → 이전 비번 실패(401) → 새 비번 성공(200) (Req 4.1, 4.4).

    이전 비밀번호로는 더 이상 로그인되지 않고 새 비밀번호로만 로그인되므로, 저장 해시가
    평문 없이 s01 해싱 스킴으로 실제 교체되었음을 e2e 로 증명한다.
    """
    # 1) 이전 비밀번호로 로그인 → 200(세션 쿠키가 이 클라이언트에 유지된다).
    with TestClient(seeded.app) as client:
        login = client.post(
            "/auth/login",
            json={"login_id": seeded.active_login_id, "password": OLD_PASSWORD},
        )
        assert login.status_code == 200
        assert seeded.session_cookie_name in client.cookies

        # 2) 인증된 세션으로 올바른 현재 비번 + 유효한 새 비번(>=8) → 204(본문 없음).
        change = client.post(
            "/auth/password",
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert change.status_code == 204, "올바른 변경 요청은 본문 없이 204 여야 한다"
        assert change.content == b"", "204 응답은 본문이 없어야 한다"

        # 이 세션으로 로그아웃하여 신선한 재로그인 시도를 준비한다.
        assert client.post("/auth/logout").status_code == 204

    # 3) 신선한 클라이언트로 이전 비밀번호 로그인 → 401(이전 자격은 더 이상 통하지 않는다).
    with TestClient(seeded.app) as client:
        old_login = client.post(
            "/auth/login",
            json={"login_id": seeded.active_login_id, "password": OLD_PASSWORD},
        )
        assert old_login.status_code == 401, (
            "비밀번호 변경 후 이전 비밀번호로는 로그인되지 않아야 한다(해시 교체 증명)"
        )
        assert old_login.json()["code"] == "unauthenticated"
        assert seeded.session_cookie_name not in client.cookies

    # 4) 신선한 클라이언트로 새 비밀번호 로그인 → 200(새 자격이 동작한다).
    with TestClient(seeded.app) as client:
        new_login = client.post(
            "/auth/login",
            json={"login_id": seeded.active_login_id, "password": NEW_PASSWORD},
        )
        assert new_login.status_code == 200, (
            "비밀번호 변경 후 새 비밀번호로 로그인되어야 한다(해시 교체 증명)"
        )
        assert new_login.json()["login_id"] == seeded.active_login_id
        assert seeded.session_cookie_name in client.cookies


# --- 오류/예외: 422 unprocessable(도메인) vs 422 validation_error(스키마) vs 401 --------


def test_password_change_wrong_current_returns_422_unprocessable(seeded):
    """인증됨, 현재 비밀번호 불일치(새 비번 스키마 통과) → 422 unprocessable (Req 4.2).

    도메인 규칙 위반이므로 code 는 ``unprocessable`` 이어야 하며 스키마 검증
    ``validation_error`` 와 구분된다.
    """
    with TestClient(seeded.app) as client:
        assert (
            client.post(
                "/auth/login",
                json={"login_id": seeded.active_login_id, "password": OLD_PASSWORD},
            ).status_code
            == 200
        )

        resp = client.post(
            "/auth/password",
            json={"current_password": WRONG_CURRENT, "new_password": NEW_PASSWORD},
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "unprocessable", (
            "현재 비밀번호 불일치는 도메인 규칙 위반(unprocessable)이어야 한다"
        )
        assert body["code"] != "validation_error"
        _assert_error_response_shape(body)


def test_password_change_short_new_returns_422_validation_error_with_field_errors(
    seeded,
):
    """인증됨, 새 비번 < 8자(현재 비번 정확) → 422 validation_error + field_errors (Req 4.3).

    스키마 정책 위반이므로 s01 전역 핸들러가 code ``validation_error`` 와 비어있지 않은
    field_errors 로 응답해야 하며, 도메인 규칙 위반(unprocessable)과 구분된다.
    """
    with TestClient(seeded.app) as client:
        assert (
            client.post(
                "/auth/login",
                json={"login_id": seeded.active_login_id, "password": OLD_PASSWORD},
            ).status_code
            == 200
        )

        resp = client.post(
            "/auth/password",
            json={"current_password": OLD_PASSWORD, "new_password": SHORT_PASSWORD},
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "validation_error", (
            "짧은 새 비밀번호는 스키마 검증 오류(validation_error)여야 한다"
        )
        assert body["code"] != "unprocessable"
        assert body.get("field_errors"), "스키마 검증 오류는 field_errors 를 포함해야 한다"
        assert len(body["field_errors"]) > 0
        _assert_error_response_shape(body)


def test_password_change_unauthenticated_returns_401(seeded):
    """미인증(신선한 클라이언트), 스키마 통과 본문 → 401 unauthenticated (Req 4.6).

    get_current_user 가 먼저 동작하므로 본문과 무관하게 인증 게이트(401)가 스키마
    검증(422)보다 먼저 발생해야 한다.
    """
    with TestClient(seeded.app) as client:
        resp = client.post(
            "/auth/password",
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 401, (
            "미인증 요청은 스키마 검증(422)이 아니라 인증 게이트(401)로 거부되어야 한다"
        )
        body = resp.json()
        assert body["code"] == "unauthenticated"
        _assert_error_response_shape(body)


# --- 계약/경계: OpenAPI 경로 정합 및 계정 생명주기 엔드포인트 부재 ------------------


def test_openapi_exposes_exactly_the_four_auth_endpoints(seeded):
    """앱 OpenAPI 의 auth 경로가 카탈로그 1~4 와 정확히 일치(메서드 포함) (Req 5.2).

    실제 부팅된 앱의 ``openapi()["paths"]`` 를 검사해 auth 표면이 정확히 4개
    (`/auth/login`·`/auth/logout`·`/auth/me`·`/auth/password`)이며 각 메서드가 카탈로그와
    일치함을 강제한다.
    """
    paths = logical_openapi_paths(seeded.app)

    # auth 표면만 추출: /auth/ 로 시작하는 경로 → {메서드 대문자 집합}.
    auth_surface = {
        path: {method.upper() for method in operations}
        for path, operations in paths.items()
        if path.startswith("/auth")
    }

    expected = {
        "/auth/login": {"POST"},
        "/auth/logout": {"POST"},
        "/auth/me": {"GET"},
        "/auth/password": {"POST"},
    }

    assert auth_surface == expected, (
        f"auth OpenAPI 표면은 카탈로그 1~4 와 정확히 일치해야 한다: {auth_surface!r}"
    )


def test_openapi_has_no_account_lifecycle_endpoints(seeded):
    """s02(auth) 표면이 계정 생성/삭제·admin 재설정·자가 가입/재설정을 소유하지 않음 (Req 5.3, 5.4).

    Req 5.3/5.4의 주어는 **Auth Service(s02 자신의 표면)** 이다. s02 Introduction이 명시하듯
    계정 생명주기(`/admin/users` 생성/삭제·admin 비밀번호 재설정)는 `s03-admin-account`가 소유한다.
    따라서 이 테스트는 s02 auth 표면이 정확히 4개 경로뿐이며, s03가 소유하는 `/admin/*`
    네임스페이스를 **제외한** 나머지 표면에 계정 생명주기/재설정 경로가 없음을 강제한다.
    (`/admin/*` 는 s03 spec이 소유·검증하므로 이 s02 경계 테스트의 금지 검사 대상이 아니다.)
    """
    paths = logical_openapi_paths(seeded.app)
    all_paths = set(paths.keys())

    # auth 경로는 정확히 이 4개뿐이어야 한다(생명주기 auth 경로 부재의 상위 보장).
    auth_paths = {p for p in all_paths if p.startswith("/auth")}
    assert auth_paths == {
        "/auth/login",
        "/auth/logout",
        "/auth/me",
        "/auth/password",
    }, f"auth 경로는 정확히 4개여야 한다: {auth_paths!r}"

    # s02 표면에 계정 생명주기/재설정으로 해석될 수 있는 경로가 하나도 없어야 한다.
    # s03가 소유하는 `/admin/*` 계정관리 경로는 이 s02 경계 검사에서 제외한다(소유권 분리).
    forbidden_substrings = ["/users", "/user", "reset", "signup", "sign-up", "register"]
    for path in all_paths:
        if path.startswith("/admin"):
            continue  # s03-admin-account 소유 네임스페이스 — s02 경계 검사 대상 아님.
        lowered = path.lower()
        for needle in forbidden_substrings:
            assert needle not in lowered, (
                f"s02 auth 표면에 계정 생명주기/재설정 엔드포인트가 존재해서는 안 된다: {path!r} "
                f"(금지 토큰 {needle!r})"
            )


def test_all_observed_error_bodies_conform_to_s01_error_response(seeded):
    """관측되는 401·422 unprocessable·422 validation_error 가 모두 s01 ErrorResponse 형태 (Req 5.1, 5.5).

    세 종류의 오류를 실제로 유발해 각 본문이 문자열 code·message(및 리스트 field_errors)를
    갖는 단일 공통 형태임을 강제한다.
    """
    # 401: 미인증 비밀번호 변경.
    with TestClient(seeded.app) as client:
        unauth = client.post(
            "/auth/password",
            json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        )
    assert unauth.status_code == 401
    unauth_body = unauth.json()
    assert unauth_body["code"] == "unauthenticated"
    _assert_error_response_shape(unauth_body)

    # 422 unprocessable(도메인) 및 422 validation_error(스키마): 인증된 세션에서 유발.
    with TestClient(seeded.app) as client:
        assert (
            client.post(
                "/auth/login",
                json={"login_id": seeded.active_login_id, "password": OLD_PASSWORD},
            ).status_code
            == 200
        )

        unprocessable = client.post(
            "/auth/password",
            json={"current_password": WRONG_CURRENT, "new_password": NEW_PASSWORD},
        )
        assert unprocessable.status_code == 422
        unprocessable_body = unprocessable.json()
        assert unprocessable_body["code"] == "unprocessable"
        _assert_error_response_shape(unprocessable_body)

        validation = client.post(
            "/auth/password",
            json={"current_password": OLD_PASSWORD, "new_password": SHORT_PASSWORD},
        )
        assert validation.status_code == 422
        validation_body = validation.json()
        assert validation_body["code"] == "validation_error"
        assert isinstance(validation_body["field_errors"], list)
        assert len(validation_body["field_errors"]) > 0
        _assert_error_response_shape(validation_body)

    # 세 오류의 code 가 서로 구분됨을 최종 확인(401 vs 422-도메인 vs 422-스키마).
    assert unauth_body["code"] == "unauthenticated"
    assert unprocessable_body["code"] == "unprocessable"
    assert validation_body["code"] == "validation_error"
