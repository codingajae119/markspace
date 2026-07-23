"""WsIdAdapter 단위/통합 검증 (s05-workspace task 1.2 / Req 4.1~4.6, 5.4).

design.md §Components and Interfaces #WsIdAdapter·#require_admin(s01 공통 소비) 검증:
- s05 워크스페이스 라우트는 경로 파라미터가 ``{id}`` 이며(s01 카탈로그 `/workspaces/{id}`),
  s01 ``require_ws_role`` 의 내부 의존성은 경로 파라미터 ``workspace_id`` 를 문자 그대로
  읽는다. 따라서 s05 는 경로 ``{id}`` → ``workspace_id`` 로 잇는 **얇은 어댑터**를 제공하고
  판정(위계·admin bypass·403)은 전부 s01 resolver 에 위임한다(재구현 없음).
- admin 게이트는 s05 가 정의하지 않는다: ``require_admin`` 은 s01 ``common/permissions`` 의
  공통 게이트를 **import 해 소비**만 한다(feature-local 정의 폐기, design.md §require_admin).

이 테스트의 핵심 주장(이 task 고유): 라우트 경로 파라미터가 ``{id}`` 로 선언될 때(NOT
``{workspace_id}``) 어댑터의 이름 브리징이 실제로 일어나 owner→200 / member·비멤버→403
(OWNER 관리 게이트 미달) / admin→200 으로 s01 semantics 를 그대로 재현하고, s01 공통
``require_admin`` 을 부착한 라우트가 admin→200 / 비-admin→403 으로 게이팅됨을 확인한다.

격리: ``test_integration_wiring.py`` 와 동일한 확립된 패턴을 재사용한다. ``DB_NAME`` 을
전용 테스트 DB(``markspace_test``)로 바꾸고 ``get_settings`` 캐시를 비운 뒤 그 시점 URL 로
새 엔진·세션 팩토리를 만들고, ``get_db`` 를 override 한 실제 앱에 테스트 전용 라우트만
부착한다. 종료 시 테이블을 모두 제거하고 엔진을 dispose 한 뒤 환경변수·캐시를 원복한다.
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
from app.common.permissions import require_admin
from app.main import create_app
from app.models import User, Workspace, WorkspaceMember
from app.workspace.dependencies import Role, require_ws_role

TEST_DB_NAME = "markspace_test"


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

    def __init__(
        self, app, workspace_id, owner_id, member_id, non_member_id, admin_id
    ):
        self.app = app
        self.workspace_id = workspace_id
        self.owner_id = owner_id
        self.member_id = member_id
        self.non_member_id = non_member_id
        self.admin_id = admin_id


@pytest.fixture
def wiring():
    """테스트 DB 를 마이그레이션·시드하고, get_db 를 override 한 실제 앱을 제공한다.

    핵심: 보호 라우트를 경로 파라미터 ``{id}`` 로 선언하고 s05 어댑터
    ``require_ws_role(Role.OWNER)`` 를 부착한다(이름 브리징 검증). 또한 s01 공통
    ``require_admin`` 을 부착한 admin 전용 라우트를 함께 부착한다.
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

    # 시드: 앱은 override 된 별도 세션(별도 커넥션)으로 조회하므로 반드시 commit 한다.
    seed = TestSessionLocal()
    try:
        ws = Workspace(
            name="어댑터 테스트 워크스페이스",
            is_shareable=False,
            trash_retention_days=30,
            created_at=datetime.utcnow(),
        )
        seed.add(ws)
        seed.flush()

        owner = _make_user(seed, login_id="adapter-owner")
        member = _make_user(seed, login_id="adapter-member")
        non_member = _make_user(seed, login_id="adapter-nonmember")
        admin = _make_user(seed, login_id="adapter-admin", is_admin=True)

        seed.add_all(
            [
                WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"),
                WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member"),
            ]
        )
        seed.commit()

        ids = _Wiring(
            app=None,
            workspace_id=ws.id,
            owner_id=owner.id,
            member_id=member.id,
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

    # 테스트 전용 라우트를 앱 인스턴스에만 부착한다(프로덕션 조립 지점은 비운 채 유지).
    def _login_as(request: Request, uid: int):
        request.session["user_id"] = uid
        return {"ok": True}

    def _logout(request: Request):
        request.session.clear()
        return {"ok": True}

    # 핵심: 경로 파라미터를 {id} 로 선언하고 s05 어댑터를 부착한다(이름 브리징 검증).
    def _owner_probe(
        id: int,
        ctx: AuthContext = Depends(require_ws_role(Role.OWNER)),
    ):
        return {"id": id, "user_id": ctx.user_id}

    # s01 공통 require_admin 을 부착한 admin 전용 라우트(소비 검증).
    def _admin_probe(ctx: AuthContext = Depends(require_admin)):
        return {"user_id": ctx.user_id}

    app.add_api_route("/_test/login/{uid}", _login_as, methods=["POST"])
    app.add_api_route("/_test/logout", _logout, methods=["POST"])
    app.add_api_route("/_probe/{id}", _owner_probe, methods=["GET"])
    app.add_api_route("/_admin_probe", _admin_probe, methods=["GET"])

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
    return f"/_probe/{wiring.workspace_id}"


# --- require_ws_role 어댑터: 경로 {id} → workspace_id 브리징 (Req 4.1~4.6) ---


def test_adapter_owner_via_id_path_param_returns_200(wiring):
    """owner 멤버는 {id} 경로로 구성한 require_ws_role(OWNER) 를 통과 → 200 (Req 4.2, 4.6).

    경로가 ``{id}`` 로 선언됐는데도 통과한다는 것은 어댑터가 id→workspace_id 를 실제로
    브리징해 s01 resolver 가 role 을 판정했음을 의미한다(이름이 안 이어졌다면 FastAPI 가
    workspace_id 파라미터를 찾지 못해 422 로 실패한다).
    """
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.owner_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == wiring.workspace_id
    assert body["user_id"] == wiring.owner_id


def test_adapter_member_denied_for_owner_route_403(wiring):
    """member 는 OWNER 요구 관리 라우트에서 위계 미달 → 403 (Req 5.4, INV-2)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.member_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_adapter_non_member_denied_403(wiring):
    """비멤버는 어떤 role 도 없어 거부 → 403 (Req 4.4)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.non_member_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_adapter_admin_bypasses_to_200(wiring):
    """admin 은 멤버십·role 무관하게 어댑터를 통과 → 200 (Req 4.5, INV-3 admin bypass)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.admin_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == wiring.workspace_id
    assert body["user_id"] == wiring.admin_id


# --- require_admin(s01 공통 소비): admin_router 부착 게이팅 (Req 5.4) ---


def test_s01_require_admin_passes_for_admin(wiring):
    """s01 공통 require_admin 을 부착한 라우트는 admin → 200 (Req 5.4)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.admin_id}").status_code == 200
        resp = client.get("/_admin_probe")

    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == wiring.admin_id


def test_s01_require_admin_denies_non_admin_403(wiring):
    """s01 공통 require_admin 을 부착한 라우트는 비-admin → 403 (Req 5.4)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.owner_id}").status_code == 200
        resp = client.get("/_admin_probe")

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


# --- 계약 정합: 어댑터가 s01 판정 로직을 재구현하지 않고 위임한다 ---


def test_adapter_reexports_s01_role(wiring):
    """어댑터 모듈이 노출하는 Role 은 s01 공통 IntEnum 과 동일 객체다(재정의 없음)."""
    from app.common.permissions import Role as S01Role

    assert Role is S01Role
