"""로그인 통합 테스트: 성공·실패·계정 상태 게이트 (Task 4.1 / Req 1.1, 1.3, 1.4, 1.5, 1.6, 1.7).

MOCK 없이 마이그레이션된 실제 테스트 DB 위에서 ``create_app()`` 으로 실제 앱을 세우고
``TestClient`` 로 진짜 ASGI 요청을 흘려, ``POST /auth/login`` 의 전 결선(요청 파싱 →
:class:`AuthService.authenticate` → s01 ``verify_password`` → ``is_active``/``is_deleted``
게이트 → 세션 write)이 하나의 앱 컨텍스트에서 동작함을 검증한다(design.md
§Testing Strategy Integration Tests "상태 게이트 e2e", §System Flows 로그인 및 세션 발급 흐름).

검증 항목:
- 활성·미삭제 사용자의 올바른 자격 → 200 + AuthUserRead + 세션 쿠키 발급(Req 1.1, 1.2, 1.6).
- 비밀번호 불일치 → 401 ``unauthenticated``(Req 1.3).
- 미존재 login_id → 401 ``unauthenticated``, #2 와 동일 형태(Req 1.3, 계정 열거 방지).
- 비활동(``is_active=false``) 사용자 + 올바른 비밀번호 → 401 ``unauthenticated``, 세션 미발급(Req 1.4).
- 삭제(``is_deleted=true``) 사용자 + 올바른 비밀번호 → 401 ``unauthenticated``(Req 1.5).
- 성공 응답 본문에 ``password_hash`` 부재(Req 1.7).

격리: ``test_integration_wiring.py`` 의 확립된 패턴을 재사용한다. ``DB_NAME`` 을 전용
테스트 DB(``notion_lite_test``)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
**그 시점의** URL 로 새 엔진·세션 팩토리를 만든다(모듈 수준 엔진은 import 시점 개발 DB 에
묶여 있어 재사용하지 않는다). 앱 전체가 테스트 DB 를 쓰도록 ``get_db`` 를 override 하고,
종료 시 테이블을 모두 제거·엔진 dispose·환경변수·캐시를 원복하여 개발 DB 누수를 막는다.
테스트 DB 는 비운 상태로 남긴다. 시나리오마다 신규 ``TestClient`` 를 써서 잔여 쿠키가
없음을 보장한다.
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
WRONG_PASSWORD = "wrong-password"


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
        self.inactive_login_id = "inactive-bob"
        self.deleted_login_id = "deleted-carol"


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

    # 시드: 앱은 override 된 별도 세션(별도 커넥션)으로 조회하므로 반드시 commit 한다.
    # 비밀번호는 s01 hash_password 로 실제 저장 해시를 만든다(MOCK 없음).
    seed = TestSessionLocal()
    try:
        seed.add_all(
            [
                User(
                    login_id="alice",
                    password_hash=hash_password(CORRECT_PASSWORD),
                    name="앨리스",
                    is_admin=False,
                    is_active=True,
                    is_deleted=False,
                    created_at=datetime.utcnow(),
                ),
                User(
                    login_id="inactive-bob",
                    password_hash=hash_password(CORRECT_PASSWORD),
                    name="밥",
                    is_admin=False,
                    is_active=False,
                    is_deleted=False,
                    created_at=datetime.utcnow(),
                ),
                User(
                    login_id="deleted-carol",
                    password_hash=hash_password(CORRECT_PASSWORD),
                    name="캐롤",
                    is_admin=False,
                    is_active=True,
                    is_deleted=True,
                    created_at=datetime.utcnow(),
                ),
            ]
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


def test_login_success_sets_session_and_returns_auth_user(seeded):
    """활성·미삭제 사용자의 올바른 자격 → 200 + AuthUserRead + 세션 쿠키 (Req 1.1, 1.2, 1.6, 1.7)."""
    with TestClient(seeded.app) as client:
        resp = client.post(
            "/auth/login",
            json={"login_id": seeded.active_login_id, "password": CORRECT_PASSWORD},
        )

        assert resp.status_code == 200
        body = resp.json()

        # 응답 본문은 AuthUserRead(비민감 식별 정보)이다 (Req 1.2).
        assert body["login_id"] == seeded.active_login_id
        assert body["name"] == "앨리스"
        assert body["is_admin"] is False
        assert isinstance(body["id"], int)

        # 민감 필드는 절대 노출되지 않는다 (Req 1.7).
        assert "password_hash" not in body
        assert "password" not in body

        # 세션 쿠키가 발급된다 (Req 1.6, 세션 생성).
        set_cookie = resp.headers.get("set-cookie", "")
        assert seeded.session_cookie_name in set_cookie, (
            "성공 로그인은 세션 쿠키를 Set-Cookie 로 발급해야 한다"
        )
        assert seeded.session_cookie_name in client.cookies


def test_login_wrong_password_returns_401_unauthenticated(seeded):
    """비밀번호 불일치 → 401 unauthenticated (Req 1.3)."""
    with TestClient(seeded.app) as client:
        resp = client.post(
            "/auth/login",
            json={"login_id": seeded.active_login_id, "password": WRONG_PASSWORD},
        )

        assert resp.status_code == 401
        assert resp.json()["code"] == "unauthenticated"
        # 실패 시 세션 쿠키를 발급하지 않는다.
        assert seeded.session_cookie_name not in client.cookies


def test_login_nonexistent_login_id_returns_same_401(seeded):
    """미존재 login_id → 401 unauthenticated, 비밀번호 불일치와 동일 형태 (Req 1.3, 계정 열거 방지)."""
    with TestClient(seeded.app) as client:
        missing = client.post(
            "/auth/login",
            json={"login_id": "nobody-here", "password": CORRECT_PASSWORD},
        )

    with TestClient(seeded.app) as client:
        wrong_pw = client.post(
            "/auth/login",
            json={"login_id": seeded.active_login_id, "password": WRONG_PASSWORD},
        )

    assert missing.status_code == 401
    assert missing.json()["code"] == "unauthenticated"
    # 미존재와 비밀번호 불일치는 구분 불가한 동일 응답이어야 한다 (Req 1.3).
    assert missing.status_code == wrong_pw.status_code
    assert missing.json() == wrong_pw.json()


def test_login_inactive_user_with_correct_password_rejected(seeded):
    """비활동 사용자 + 올바른 비밀번호 → 401 unauthenticated, 세션 미발급 (Req 1.4)."""
    with TestClient(seeded.app) as client:
        resp = client.post(
            "/auth/login",
            json={"login_id": seeded.inactive_login_id, "password": CORRECT_PASSWORD},
        )

        assert resp.status_code == 401
        assert resp.json()["code"] == "unauthenticated"
        # 자격 증명이 올발라도 세션을 생성하지 않는다 (Req 1.4).
        assert seeded.session_cookie_name not in client.cookies
        assert "set-cookie" not in {k.lower() for k in resp.headers.keys()}


def test_login_deleted_user_with_correct_password_rejected(seeded):
    """삭제 사용자 + 올바른 비밀번호 → 401 unauthenticated (Req 1.5)."""
    with TestClient(seeded.app) as client:
        resp = client.post(
            "/auth/login",
            json={"login_id": seeded.deleted_login_id, "password": CORRECT_PASSWORD},
        )

        assert resp.status_code == 401
        assert resp.json()["code"] == "unauthenticated"
        assert seeded.session_cookie_name not in client.cookies


def test_all_failure_shapes_are_identical(seeded):
    """비밀번호 불일치·미존재·비활동·삭제의 실패 응답이 모두 동일 형태임을 확인 (Req 1.3, 1.4, 1.5)."""
    payloads = [
        {"login_id": seeded.active_login_id, "password": WRONG_PASSWORD},  # 비밀번호 불일치
        {"login_id": "nobody-here", "password": CORRECT_PASSWORD},  # 미존재
        {"login_id": seeded.inactive_login_id, "password": CORRECT_PASSWORD},  # 비활동
        {"login_id": seeded.deleted_login_id, "password": CORRECT_PASSWORD},  # 삭제
    ]

    bodies = []
    for payload in payloads:
        with TestClient(seeded.app) as client:
            resp = client.post("/auth/login", json=payload)
            assert resp.status_code == 401
            assert resp.json()["code"] == "unauthenticated"
            bodies.append(resp.json())

    # 네 실패 사유가 서로 구분 불가한 동일 본문이어야 한다(계정 열거 방지).
    first = bodies[0]
    for other in bodies[1:]:
        assert other == first
