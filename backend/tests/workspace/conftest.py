"""s05-workspace 통합 테스트 공용 하네스 (Task 4.1 / 4.2 공유).

mock 없이 s01 ⊕ s02 ⊕ s03 ⊕ s05 의 **실제 구현을 결합**한 검증 환경을 제공한다. 이
하네스는 resolver 실동작·워크스페이스/멤버십 왕복(4.1)과 후속 마이그레이션 왕복(4.2)이
공유하는 fixture(:func:`ws_harness`)로 다음을 실제로 준비한다(design.md §Testing Strategy
→ Integration Tests):

1. **테스트 DB 격리**: ``DB_NAME`` 을 전용 테스트 DB(``notion_lite_test``)로 바꾸고
   :func:`app.config.get_settings` 캐시를 비운 뒤 **그 시점의** URL 로 새 엔진·세션 팩토리를
   만든다(모듈 수준 ``app.common.db.engine`` 은 import 시점 개발 DB 에 묶여 있어 재사용하지
   않는다). 스키마는 ``Base.metadata.create_all`` 로 생성한다(마이그레이션 자체의 검증은
   s05 task 4.2 / L1 의 몫이며 여기서는 결선·resolver 실동작이 대상이다).
2. **admin 시드**: 애플리케이션에 admin 생성 경로가 없으므로 ORM ``User`` 모델로 직접
   ``is_admin=True`` 사용자를 DB 에 커밋한다(테스트 준비이지 feature 로직이 아님).
3. **앱 부팅 + get_db override**: s01 ``create_app()`` 으로 앱을 세우고(s02 auth·s03 admin·
   s05 workspace 라우터는 그 내부에서 이미 조립됨) 앱 전체가 테스트 DB 를 쓰도록 ``get_db``
   의존성을 generator 로 override 한다.
4. **세션 유지 클라이언트**: 로그인 세션 쿠키가 후속 요청에 실제로 전달되는 ``TestClient``
   경로(:meth:`login`)를 제공한다.
5. **DB 미가용 → 실패(스킵 아님)**: 미검증 상태가 통과로 오인되지 않도록 연결 오류를
   전파한다(``pytest.skip`` 을 쓰지 않는다).

종료 시 override 해제·테이블 제거·엔진 dispose·환경변수·캐시를 원복한다.
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

# 시드 admin 의 알려진 평문 자격(해시는 s01 hash_password 로 생성). 실제 자격이 아닌 테스트
# 전용 크리덴셜이며 애플리케이션 코드에는 존재하지 않는다.
ADMIN_LOGIN_ID = "ws-admin-root"
ADMIN_PASSWORD = "ws-admin-correct-horse"
# 멤버 후보 사용자 생성 시 쓰는 기본 비밀번호(s02 min_length 8 정책 충족).
DEFAULT_PASSWORD = "ws-member-pass-123"


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


class WsHarness:
    """부팅된 실제 앱 + 테스트 DB 세션 팩토리 핸들 — 4.1/4.2 가 소비한다.

    노출 필드/헬퍼:

    - ``app``: get_db 가 테스트 DB 로 override 된, 부팅된 실제 FastAPI 앱.
    - ``session_local``: 앱 override 와 **동일한** 세션 팩토리. DB 수준 단언(멤버 행 존재·
      삭제 캐스케이드 등)이 커밋된 행을 신규 세션으로 직접 관찰하는 데 쓴다.
    - ``session_cookie_name``: s01 ``Settings.session_cookie_name``.
    - ``admin_login_id`` / ``admin_password``: 시드된 admin 자격(실제 s02 로그인 흐름 발급용).
    - :meth:`new_client`: 시나리오마다 쿠키 오염 없는 신규 ``TestClient``.
    - :meth:`login`: 주어진 자격으로 s02 ``POST /auth/login`` 을 태워 세션 쿠키가 실린
      인증 클라이언트를 반환.
    - :meth:`login_admin`: 시드 admin 으로 로그인한 인증 클라이언트를 반환.
    - :meth:`create_user`: admin 인증 클라이언트로 ``POST /admin/users`` 를 태워 비-admin
      사용자를 만들고 생성된 id 를 반환(SETUP 헬퍼, 201 내부 단언).
    """

    def __init__(self, app, session_local, session_cookie_name):
        self.app = app
        self.session_local = session_local
        self.session_cookie_name = session_cookie_name
        self.admin_login_id = ADMIN_LOGIN_ID
        self.admin_password = ADMIN_PASSWORD

    def new_client(self) -> TestClient:
        """쿠키 오염이 없는 신규 ``TestClient`` (시나리오마다 새로 만든다)."""
        return TestClient(self.app)

    def login(self, login_id: str, password: str) -> TestClient:
        """s02 실제 로그인 흐름으로 세션 쿠키가 실린 인증 ``TestClient`` 를 반환한다.

        로그인이 200 이 아니면 즉시 실패시켜(assert) 하네스 오설정이 조용히 통과로
        번지지 않게 한다.
        """
        client = self.new_client()
        resp = client.post(
            "/auth/login", json={"login_id": login_id, "password": password}
        )
        assert resp.status_code == 200, f"로그인 실패: {resp.status_code} {resp.text}"
        return client

    def login_admin(self) -> TestClient:
        """시드된 admin 자격으로 로그인한 인증 ``TestClient`` 를 반환한다."""
        return self.login(self.admin_login_id, self.admin_password)

    def create_user(
        self,
        admin: TestClient,
        login_id: str,
        *,
        name: str = "테스트 사용자",
        password: str = DEFAULT_PASSWORD,
    ) -> int:
        """admin 인증 클라이언트로 ``POST /admin/users`` 를 태워 비-admin 사용자를 만든다.

        SETUP 헬퍼 — 201 을 내부에서 단언하고 생성된 사용자의 ``id`` (int)를 반환한다.
        """
        resp = admin.post(
            "/admin/users",
            json={"login_id": login_id, "password": password, "name": name},
        )
        assert resp.status_code == 201, (
            f"사용자 생성 201 이어야 한다: {resp.status_code} {resp.text}"
        )
        return resp.json()["id"]


@pytest.fixture
def ws_harness():
    """테스트 DB 를 create_all·시드하고, get_db 를 override 한 실제 앱을 제공한다.

    DB 미가용 시 엔진 생성·시드 중 연결 오류가 그대로 전파되어 이 fixture 는 **실패**한다
    (``pytest.skip`` 을 쓰지 않는다 — 미검증을 통과로 오인 방지).
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

    app = None
    try:
        _drop_everything(engine)  # 시작 전 빈 상태 보증(격리 전제).
        Base.metadata.create_all(engine)  # 마이그레이션된 DB 계약을 물리적으로 생성.

        # admin 시드: 앱은 override 된 별도 세션(별도 커넥션)으로 조회하므로 commit 필수.
        # User 는 Python-side 기본값만 있어 created_at 을 명시해야 한다(서버 기본값 없음).
        seed = TestSessionLocal()
        try:
            seed.add(
                User(
                    login_id=ADMIN_LOGIN_ID,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    name="관리자",
                    is_admin=True,
                    is_active=True,
                    is_deleted=False,
                    created_at=datetime.utcnow(),
                )
            )
            seed.commit()
        finally:
            seed.close()

        app = create_app()

        def _override_get_db():
            db = TestSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_get_db

        yield WsHarness(
            app=app,
            session_local=TestSessionLocal,
            session_cookie_name=settings.session_cookie_name,
        )
    finally:
        if app is not None:
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
