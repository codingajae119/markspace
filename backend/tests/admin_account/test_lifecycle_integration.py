"""계정 생명주기·계약·soft-delete 통합 테스트 (Task 4.1 / Req 1.2, 1.3, 2.2, 3.1, 3.3, 4.1, 6.1, 7.1, 7.2, 8.3, 8.5).

MOCK 없이 마이그레이션된 실제 테스트 DB 위에서 ``create_app()`` 으로 실제 앱을 세우고
``TestClient`` 로 진짜 ASGI 요청을 흘려, s03 계정관리 엔드포인트의 전 결선(s01 세션 인증 +
s02 로그인 + s03 admin 게이트 + 서비스·리포지토리 영속)이 하나의 앱 컨텍스트에서 동작함을
검증한다(design.md §Testing Strategy Integration Tests, §Contract Consistency Tests).

admin 세션은 s02 실제 로그인 흐름(``POST /auth/login``)으로 발급하여 s01 세션 인증 +
s02 로그인 + s03 admin 게이트가 함께 동작하는 진짜 end-to-end 임을 보장한다.

검증 항목:
- admin 전용 접근: admin 세션 → 201 ``UserRead``, 인증된 비-admin → 403 ``forbidden``,
  미인증(세션 없음) → 401 ``unauthenticated`` (Req 1.2, 1.3, 2.2, 8.5).
- 생명주기 왕복: 생성 → 목록 노출 → soft-delete(``is_deleted=true``) 후에도 목록에 계속
  노출 → 재활성화(``is_deleted=false``); ``is_active`` 는 삭제/재활성화 왕복 내내 불변
  (두 flag 독립, Req 3.1, 3.3, 4.1, 6.1).
- 비밀번호 재설정: 204 후 저장된 ``password_hash`` 가 **새 해시**로 갱신되어 평문이 아니고
  (verify_password True, stored != plaintext) 재설정 전 해시와도 다름(Req 7.1, 7.2).
- INV-4(물리 삭제 없음): soft-delete 후에도 DB 행이 물리적으로 존재(Req 8.3).

격리: ``tests/auth/test_login_integration.py`` 의 확립된 패턴을 재사용한다. ``DB_NAME`` 을
전용 테스트 DB(``markspace_test``)로 바꾸고 :func:`app.config.get_settings` 캐시를 비운 뒤
**그 시점의** URL 로 새 엔진·세션 팩토리를 만든다. 앱 전체가 테스트 DB 를 쓰도록 ``get_db``
를 override 하고, DB 수준 단언(비밀번호 해시·행 존재)은 앱 override 와 동일한 세션 팩토리에서
연 신규 세션으로 커밋된 행을 관찰한다. 종료 시 테이블을 모두 제거·엔진 dispose·환경변수·캐시를
원복한다. 세션 시나리오마다 신규 ``TestClient`` 를 써서 잔여 쿠키 오염을 막는다.
"""

import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.db import Base, get_db
from app.common.security import hash_password, verify_password
from app.main import create_app
from app.models import User

TEST_DB_NAME = "markspace_test"

# 시드 사용자의 알려진 평문 비밀번호(해시는 s01 hash_password 로 생성).
ADMIN_PASSWORD = "admin-correct-horse"
NONADMIN_PASSWORD = "member-correct-horse"


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
    """시나리오에서 참조할 앱·세션 팩토리·쿠키 이름·시드 자격 묶음.

    ``session_local`` 은 앱 override 와 **동일한** 세션 팩토리로, DB 수준 단언이 커밋된
    행을 신규 세션으로 직접 관찰하게 한다.
    """

    def __init__(self, app, session_cookie_name, session_local):
        self.app = app
        self.session_cookie_name = session_cookie_name
        self.session_local = session_local
        self.admin_login_id = "admin-root"
        self.nonadmin_login_id = "member-mallory"


@pytest.fixture
def seeded():
    """테스트 DB 를 마이그레이션·시드하고, get_db 를 override 한 실제 앱을 제공한다.

    admin(is_admin=True) 과 비-admin(is_admin=False) 사용자를 실제 해시로 시드하여
    s02 실제 로그인 흐름으로 세션을 발급할 수 있게 한다.
    """
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
    # 비밀번호는 s01 hash_password 로 실제 저장 해시를 만든다(MOCK 없음).
    seed = TestSessionLocal()
    try:
        seed.add_all(
            [
                User(
                    login_id="admin-root",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    name="관리자",
                    is_admin=True,
                    is_active=True,
                    is_deleted=False,
                    created_at=datetime.utcnow(),
                ),
                User(
                    login_id="member-mallory",
                    password_hash=hash_password(NONADMIN_PASSWORD),
                    name="말로리",
                    is_admin=False,
                    is_active=True,
                    is_deleted=False,
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
        yield _Seed(
            app=app,
            session_cookie_name=settings.session_cookie_name,
            session_local=TestSessionLocal,
        )
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


def _login(app, login_id: str, password: str) -> TestClient:
    """s02 실제 로그인 흐름으로 세션 쿠키가 실린 인증 TestClient 를 반환한다.

    시나리오마다 신규 TestClient 를 만들어 쿠키 오염을 방지한다(로그인 통합 테스트와 정합).
    """
    client = TestClient(app)
    resp = client.post(
        "/auth/login", json={"login_id": login_id, "password": password}
    )
    assert resp.status_code == 200, f"시드 자격으로 로그인 실패: {resp.status_code} {resp.text}"
    return client


# ---------------------------------------------------------------------------
# 시나리오 1: POST /admin/users 의 admin 전용 접근 (Req 1.2, 1.3, 2.2, 8.5)
# ---------------------------------------------------------------------------


def test_create_user_as_admin_returns_201_userread(seeded):
    """admin 세션 → 201 + UserRead(기본 상태·민감 필드 미노출) (Req 2.2, 8.5)."""
    client = _login(seeded.app, seeded.admin_login_id, ADMIN_PASSWORD)

    resp = client.post(
        "/admin/users",
        json={"login_id": "created-user", "password": "new-pw-123", "name": "생성됨"},
    )

    assert resp.status_code == 201
    body = resp.json()
    # UserRead 계약: 기본 상태 + 식별 필드.
    assert body["login_id"] == "created-user"
    assert body["name"] == "생성됨"
    assert body["is_admin"] is False
    assert body["is_active"] is True
    assert body["is_deleted"] is False
    assert isinstance(body["id"], int)
    # 민감 필드는 절대 노출되지 않는다(Req 8.1, Contract Consistency).
    assert "password_hash" not in body
    assert "password" not in body


def test_create_user_as_nonadmin_returns_403_forbidden(seeded):
    """인증된 비-admin → 403 forbidden (require_admin 게이트, Req 1.3)."""
    client = _login(seeded.app, seeded.nonadmin_login_id, NONADMIN_PASSWORD)

    resp = client.post(
        "/admin/users",
        json={"login_id": "should-not-exist", "password": "pw-123456", "name": "무단"},
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"

    # 게이트가 요청을 막았으므로 계정이 생성되지 않았어야 한다(INV: 비-admin 부작용 없음).
    with seeded.session_local() as db:
        leaked = db.scalar(
            select(User).where(User.login_id == "should-not-exist")
        )
    assert leaked is None, "비-admin 요청이 계정을 생성해서는 안 된다"


def test_create_user_unauthenticated_returns_401(seeded):
    """미인증(세션 없음) → 401 unauthenticated (s01 get_current_user, Req 1.2)."""
    with TestClient(seeded.app) as client:
        resp = client.post(
            "/admin/users",
            json={"login_id": "anon-created", "password": "pw-123456", "name": "익명"},
        )

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# ---------------------------------------------------------------------------
# 시나리오 2: 생명주기 왕복 — 생성 → 목록 → soft-delete → 재활성화 (Req 3.1, 3.3, 4.1, 6.1)
# ---------------------------------------------------------------------------


def _find_in_list(client: TestClient, user_id: int) -> dict | None:
    """GET /admin/users 목록에서 user_id 항목을 찾아 반환(없으면 None)."""
    resp = client.get("/admin/users", params={"limit": 100, "offset": 0})
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        if item["id"] == user_id:
            return item
    return None


def test_lifecycle_roundtrip_soft_delete_and_reactivate(seeded):
    """생성 → 목록 노출 → soft-delete 후에도 노출 → 재활성화; is_active 는 불변 (Req 3.1, 3.3, 4.1, 6.1)."""
    admin = _login(seeded.app, seeded.admin_login_id, ADMIN_PASSWORD)

    # 생성 → id 확보.
    created = admin.post(
        "/admin/users",
        json={"login_id": "lifecycle-user", "password": "pw-abcdef", "name": "왕복"},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    # 생성 직후 목록에 노출된다(Req 3.1). 기본 is_active=True, is_deleted=False.
    listed = _find_in_list(admin, user_id)
    assert listed is not None, "생성된 계정이 목록에 노출되어야 한다"
    assert listed["is_active"] is True
    assert listed["is_deleted"] is False

    # soft-delete: is_deleted=True 로 PATCH.
    patched = admin.patch(f"/admin/users/{user_id}", json={"is_deleted": True})
    assert patched.status_code == 200
    assert patched.json()["is_deleted"] is True
    # is_active 는 삭제 전이가 건드리지 않는다(두 flag 독립, Req 4.5·6.2).
    assert patched.json()["is_active"] is True

    # 삭제되었어도 목록에서 제외되지 않고 is_deleted=True 상태로 계속 노출된다(Req 3.3).
    listed_after_delete = _find_in_list(admin, user_id)
    assert listed_after_delete is not None, "soft-delete 된 계정은 목록에서 필터되지 않아야 한다"
    assert listed_after_delete["is_deleted"] is True
    assert listed_after_delete["is_active"] is True, "is_active 는 삭제 왕복 내내 불변이어야 한다"

    # 재활성화: is_deleted=False 로 되돌린다(Req 6.1).
    reactivated = admin.patch(f"/admin/users/{user_id}", json={"is_deleted": False})
    assert reactivated.status_code == 200
    assert reactivated.json()["is_deleted"] is False
    assert reactivated.json()["is_active"] is True

    # 재활성화 후에도 목록에 노출되며 is_active 는 여전히 불변이다(독립성 재확인).
    listed_after_reactivate = _find_in_list(admin, user_id)
    assert listed_after_reactivate is not None
    assert listed_after_reactivate["is_deleted"] is False
    assert listed_after_reactivate["is_active"] is True, "is_active 는 재활성화 후에도 불변이어야 한다"


# ---------------------------------------------------------------------------
# 시나리오 3: 비밀번호 재설정 — 저장 해시가 새 해시로 갱신 (Req 7.1, 7.2)
# ---------------------------------------------------------------------------


def test_password_reset_updates_stored_hash(seeded):
    """POST .../password → 204; 저장 해시가 새 해시로 갱신(평문 아님·이전 해시와 다름) (Req 7.1, 7.2)."""
    admin = _login(seeded.app, seeded.admin_login_id, ADMIN_PASSWORD)

    initial_password = "initial-pw-000"
    created = admin.post(
        "/admin/users",
        json={"login_id": "reset-user", "password": initial_password, "name": "재설정"},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    # 재설정 전 저장 해시를 신규 세션으로 관찰(커밋된 값).
    with seeded.session_local() as db:
        before = db.get(User, user_id)
        pre_reset_hash = before.password_hash
    # 초기 해시는 초기 평문을 검증하고 평문 저장이 아니다(sanity).
    assert verify_password(initial_password, pre_reset_hash)
    assert pre_reset_hash != initial_password

    new_password = "brand-new-pw-999"
    reset = admin.post(
        f"/admin/users/{user_id}/password", json={"new_password": new_password}
    )
    assert reset.status_code == 204
    assert reset.content == b"", "204 응답은 본문이 없어야 한다"

    # 재설정 후 저장 해시를 신규 세션으로 다시 관찰(커밋된 값).
    with seeded.session_local() as db:
        after = db.get(User, user_id)
        stored = after.password_hash

    # 새 비밀번호로 검증되고, 평문이 아니며, 이전 해시와도 다르다(실제 갱신·해싱 증명).
    assert verify_password(new_password, stored) is True
    assert stored != new_password, "비밀번호는 평문으로 저장되어서는 안 된다(Req 7.2)"
    assert stored != pre_reset_hash, "재설정은 저장 해시를 실제로 교체해야 한다(Req 7.1)"
    # 옛 비밀번호로는 더 이상 검증되지 않는다.
    assert verify_password(initial_password, stored) is False


# ---------------------------------------------------------------------------
# 시나리오 4: INV-4 — soft-delete 는 물리 삭제하지 않는다 (Req 8.3)
# ---------------------------------------------------------------------------


def test_soft_delete_keeps_row_physically(seeded):
    """soft-delete PATCH 후 DB 행이 물리적으로 존재하며 is_deleted=True (INV-4, Req 8.3)."""
    admin = _login(seeded.app, seeded.admin_login_id, ADMIN_PASSWORD)

    created = admin.post(
        "/admin/users",
        json={"login_id": "inv4-user", "password": "pw-inv4-00", "name": "불변식"},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    patched = admin.patch(f"/admin/users/{user_id}", json={"is_deleted": True})
    assert patched.status_code == 200
    assert patched.json()["is_deleted"] is True

    # 물리 행이 여전히 존재해야 한다(물리 DELETE 발행 금지, INV-4).
    with seeded.session_local() as db:
        row = db.get(User, user_id)
        assert row is not None, "soft-delete 는 물리적으로 행을 제거해서는 안 된다"
        assert row.is_deleted is True
        assert row.login_id == "inv4-user"

    # count 로도 행이 남아 있음을 교차 확인한다.
    with seeded.session_local() as db:
        found = db.scalar(select(User).where(User.login_id == "inv4-user"))
        assert found is not None
