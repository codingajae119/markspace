"""부팅·health·인증·권한 결선 통합 테스트 (Task 5.3 / Req 4.1, 4.2, 5.3, 5.5, 8.1, 8.2, 8.3).

이 spec 의 CAPSTONE 통합 검증이다. 마이그레이션된 실제 DB 위에서 ``create_app()`` 으로
실제 앱을 세우고 ``TestClient`` 로 진짜 ASGI 요청을 흘려, 부팅→``GET /health``(db:ok)→
세션 미들웨어→``get_current_user``→``require_ws_role`` 로 이어지는 전 결선이 하나의 앱
컨텍스트에서 함께 동작함을 검증한다(design.md §Testing Strategy Integration Tests
"보호 라우트 스텁에 Depends(require_ws_role(EDITOR)) 부착 시 미인증 401·비멤버 403·admin 200",
§System Flows 세션 인증 판정).

격리: ``test_auth.py``·``test_permissions.py``·``test_migration_roundtrip.py`` 와 동일한
확립된 패턴을 재사용한다. ``DB_NAME`` 을 전용 테스트 DB(``notion_lite_test``)로 바꾸고
:func:`app.config.get_settings` 캐시를 비운 뒤 **그 시점의** URL 로 새 엔진·세션 팩토리를
만든다(모듈 수준 ``app.common.db.engine`` 은 import 시점의 개발 DB 에 묶여 있어 재사용하지
않는다). 앱 전체(health·보호 라우트·auth·permissions)가 테스트 DB 를 쓰도록 ``get_db``
의존성을 override 한다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한 뒤 환경변수·캐시를
원복하여 이후 테스트가 다시 개발 DB 를 바라보게 한다(캐시·DB 누수 방지). 테스트 DB 는
비운 상태로 남긴다.

테스트 전용 라우트(``/_test/login/{uid}``, ``/_test/logout``, ``/workspaces/{workspace_id}/_probe``)
는 프로덕션 코드가 아니라 이 테스트 안에서 앱 인스턴스에만 부착한다. 이로써 s01 의 feature
라우터 조립 지점은 비어 있는 채로 유지되면서도(Req 8.4) 결선을 통합 테스트할 수 있다.
로그인 라우트가 없으므로(s02 소유) 세션 write 는 테스트 전용 헬퍼로 대신하며, 실제
``SessionMiddleware`` 가 서명 쿠키를 발급한다.
"""

import os
from datetime import datetime

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.auth import AuthContext
from app.common.db import Base, get_db
from app.common.permissions import Role, require_ws_role
from app.main import create_app
from app.models import User, Workspace, WorkspaceMember

TEST_DB_NAME = "notion_lite_test"


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


def _make_user(session, *, login_id, is_admin=False):
    """테스트 DB 에 활성·미삭제 User 를 삽입하고 flush 하여 id 를 확정한다."""
    user = User(
        login_id=login_id,
        password_hash="x",  # auth 는 비밀번호를 검증하지 않는다(s02 소유).
        name="테스트 사용자",
        is_admin=is_admin,
        is_active=True,
        is_deleted=False,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


class _Wiring:
    """시나리오에서 참조할 앱 인스턴스와 시드된 식별자 묶음."""

    def __init__(self, app, workspace_id, editor_id, viewer_id, non_member_id, admin_id):
        self.app = app
        self.workspace_id = workspace_id
        self.editor_id = editor_id
        self.viewer_id = viewer_id
        self.non_member_id = non_member_id
        self.admin_id = admin_id


@pytest.fixture
def wiring():
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
    seed = TestSessionLocal()
    try:
        ws = Workspace(
            name="통합 테스트 워크스페이스",
            is_shareable=False,
            trash_retention_days=30,
            created_at=datetime.utcnow(),
        )
        seed.add(ws)
        seed.flush()

        editor = _make_user(seed, login_id="wiring-editor")
        viewer = _make_user(seed, login_id="wiring-viewer")
        non_member = _make_user(seed, login_id="wiring-nonmember")
        admin = _make_user(seed, login_id="wiring-admin", is_admin=True)

        seed.add_all(
            [
                WorkspaceMember(
                    workspace_id=ws.id, user_id=editor.id, role="editor"
                ),
                WorkspaceMember(
                    workspace_id=ws.id, user_id=viewer.id, role="viewer"
                ),
            ]
        )
        seed.commit()

        ids = _Wiring(
            app=None,
            workspace_id=ws.id,
            editor_id=editor.id,
            viewer_id=viewer.id,
            non_member_id=non_member.id,
            admin_id=admin.id,
        )
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

    # 테스트 전용 라우트를 앱 인스턴스에만 부착한다(프로덕션 조립 지점은 비운 채 유지, Req 8.4).
    def _login_as(request: Request, uid: int):
        request.session["user_id"] = uid
        return {"ok": True}

    def _logout(request: Request):
        request.session.clear()
        return {"ok": True}

    def _probe(
        workspace_id: int,
        ctx: AuthContext = Depends(require_ws_role(Role.EDITOR)),
    ):
        return {"workspace_id": workspace_id, "user_id": ctx.user_id}

    app.add_api_route("/_test/login/{uid}", _login_as, methods=["POST"])
    app.add_api_route("/_test/logout", _logout, methods=["POST"])
    app.add_api_route(
        "/workspaces/{workspace_id}/_probe", _probe, methods=["GET"]
    )

    ids.app = app

    try:
        yield ids
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


def _probe_url(wiring: _Wiring) -> str:
    return f"/workspaces/{wiring.workspace_id}/_probe"


def test_health_ok_against_migrated_db(wiring):
    """부팅 후 GET /health → 200 {status:ok, db:ok} (Req 8.1, 8.2, 8.3)."""
    with TestClient(wiring.app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_unauthenticated_probe_returns_401(wiring):
    """세션 없는 신규 클라이언트의 보호 라우트 요청 → 401 unauthenticated (Req 4.2)."""
    with TestClient(wiring.app) as client:
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_non_member_probe_returns_403(wiring):
    """멤버가 아닌 인증 사용자 → 403 forbidden (Req 5.3 비멤버 거부)."""
    with TestClient(wiring.app) as client:
        login = client.post(f"/_test/login/{wiring.non_member_id}")
        assert login.status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_editor_member_probe_returns_200(wiring):
    """editor 멤버는 EDITOR 요구를 충족하여 통과 → 200, user_id 반영 (Req 4.1, 5.3)."""
    with TestClient(wiring.app) as client:
        login = client.post(f"/_test/login/{wiring.editor_id}")
        assert login.status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_id"] == wiring.workspace_id
    assert body["user_id"] == wiring.editor_id


def test_viewer_member_probe_returns_403(wiring):
    """viewer 멤버는 EDITOR 요구에 미달 → 403 forbidden (Req 5.3, INV-2)."""
    with TestClient(wiring.app) as client:
        login = client.post(f"/_test/login/{wiring.viewer_id}")
        assert login.status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_admin_non_member_probe_bypasses_to_200(wiring):
    """admin(비멤버)은 멤버십·role 무관하게 통과 → 200 (Req 5.5, INV-3 admin bypass)."""
    with TestClient(wiring.app) as client:
        login = client.post(f"/_test/login/{wiring.admin_id}")
        assert login.status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_id"] == wiring.workspace_id
    assert body["user_id"] == wiring.admin_id
