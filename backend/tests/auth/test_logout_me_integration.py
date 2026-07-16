"""로그아웃·me 왕복 및 미인증 보호 접근 통합 테스트 (Task 4.2 / Req 2.1, 2.2, 2.3, 3.1, 3.2, 3.3).

MOCK 없이 마이그레이션된 실제 테스트 DB 위에서 ``create_app()`` 으로 실제 앱을 세우고
``TestClient`` 로 진짜 ASGI 요청을 흘려, 세션의 확립→종료 생명주기와 보호 엔드포인트의
미인증 게이트가 하나의 앱 컨텍스트에서 동작함을 검증한다(design.md §Testing Strategy
Integration Tests "로그인→me 왕복", "로그아웃 종료", "미인증 보호 접근").

검증 항목:
- 왕복: 동일 클라이언트로 로그인(200) → ``GET /auth/me`` 200 이고 me 사용자가 로그인 사용자와 일치
  (세션 키 정합, Req 3.1) → ``POST /auth/logout`` 204 (Req 2.1) → 동일 쿠키 ``GET /auth/me`` 401
  (세션 종료, Req 2.2).
- 미인증 보호: 신선한 세션 없는 클라이언트로 ``/auth/me``·``/auth/logout``·``/auth/password`` → 각각 401
  ``unauthenticated`` (Req 2.3, 3.2, 4.6 → 여기선 3.2/2.3 및 비밀번호 게이트 401).

격리: ``test_login_integration.py`` 의 확립된 패턴을 그대로 재사용한다. ``DB_NAME`` 을 전용
테스트 DB(``notion_lite_test``)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤 그 시점의
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

TEST_DB_NAME = "notion_lite_test"

# 시드 사용자의 알려진 평문 비밀번호(해시는 s01 hash_password 로 생성).
CORRECT_PASSWORD = "correct-horse"


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
                password_hash=hash_password(CORRECT_PASSWORD),
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


def test_login_me_logout_roundtrip_terminates_session(seeded):
    """로그인→me 왕복 후 로그아웃으로 세션 종료: 동일 쿠키 me 가 200→401 로 전환 (Req 2.1, 2.2, 3.1)."""
    # 쿠키가 인스턴스에 유지되도록 하나의 지속 클라이언트를 왕복 전체에 재사용한다.
    with TestClient(seeded.app) as client:
        # 1) 로그인 성공 → 200, 세션 쿠키 발급.
        login = client.post(
            "/auth/login",
            json={"login_id": seeded.active_login_id, "password": CORRECT_PASSWORD},
        )
        assert login.status_code == 200
        login_body = login.json()
        assert seeded.session_cookie_name in client.cookies, (
            "성공 로그인은 세션 쿠키를 발급해 클라이언트에 유지되어야 한다"
        )

        # 2) 동일 세션 쿠키로 GET /auth/me → 200, 로그인 사용자와 일치(세션 키 정합, Req 3.1).
        me = client.get("/auth/me")
        assert me.status_code == 200
        me_body = me.json()
        assert me_body["id"] == login_body["id"], (
            "me 가 가리키는 사용자 식별자는 로그인 사용자와 동일해야 한다(세션 키 정합)"
        )
        assert me_body["login_id"] == seeded.active_login_id
        assert me_body["name"] == seeded.active_name
        assert "password_hash" not in me_body

        # 3) 로그아웃 → 204, 현재 세션 종료(Req 2.1).
        logout = client.post("/auth/logout")
        assert logout.status_code == 204

        # 4) 동일 클라이언트/쿠키로 다시 me → 401(세션 종료됨, Req 2.2).
        me_after = client.get("/auth/me")
        assert me_after.status_code == 401, (
            "로그아웃 후 동일 세션 쿠키의 보호 요청은 인증 실패여야 한다(세션 종료)"
        )
        assert me_after.json()["code"] == "unauthenticated"


def test_me_unauthenticated_returns_401(seeded):
    """세션 없는 신선한 클라이언트의 GET /auth/me → 401 unauthenticated (Req 3.2)."""
    with TestClient(seeded.app) as client:
        resp = client.get("/auth/me")
        assert resp.status_code == 401
        assert resp.json()["code"] == "unauthenticated"


def test_logout_unauthenticated_returns_401(seeded):
    """세션 없는 신선한 클라이언트의 POST /auth/logout → 401 unauthenticated (Req 2.3)."""
    with TestClient(seeded.app) as client:
        resp = client.post("/auth/logout")
        assert resp.status_code == 401
        assert resp.json()["code"] == "unauthenticated"


def test_password_change_unauthenticated_returns_401(seeded):
    """세션 없는 신선한 클라이언트의 POST /auth/password → 401 unauthenticated (Req 4.6).

    스키마를 통과하는 본문(current_password + 8자 이상 new_password)을 보내 인증 게이트(401)를
    테스트한다. get_current_user 가 먼저 동작하므로 본문과 무관하게 401 이 먼저 발생해야 한다.
    """
    with TestClient(seeded.app) as client:
        resp = client.post(
            "/auth/password",
            json={
                "current_password": CORRECT_PASSWORD,
                "new_password": "new-password-123",
            },
        )
        assert resp.status_code == 401, (
            "미인증 요청은 스키마 검증(422)이 아니라 인증 게이트(401)로 거부되어야 한다"
        )
        assert resp.json()["code"] == "unauthenticated"
