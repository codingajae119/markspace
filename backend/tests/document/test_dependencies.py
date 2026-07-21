"""DocumentWsAdapter 단위/통합 검증 (s07-document-core task 1.3 / Req 10.3, 10.4).

design.md §Components and Interfaces #DocumentWsAdapter 검증:
- `/documents/{id}` 라우트는 경로 파라미터가 문서 id 이며 s01 `require_ws_role` 의 내부
  의존성은 경로 파라미터 `workspace_id` 를 문자 그대로 읽는다. 따라서 s07 은 문서 id →
  workspace_id 로 잇는 **얇은 어댑터**(`ws_role_for_document`)를 제공하고 판정(위계·admin
  bypass·403)은 전부 s01 resolver 에 위임한다(재구현 없음, 10.4).
- 문서 미존재 시에는 s01 판정에 앞서 404(`DomainError(NOT_FOUND)`)로 거부한다.

이 테스트의 핵심 주장(이 task 고유): 라우트 경로 파라미터가 문서 `{id}` 로 선언될 때
어댑터가 `get_workspace_id` 로 문서 → workspace_id 를 실제로 매핑해 s01 semantics 를 그대로
재현한다(owner·member→200 / 비멤버→403 / admin→200 / 미존재 문서→404 / 미인증→401).
편집 어댑터의 최소 요구 role 은 2단계 모델에서 member 이다(Req 4.1, 4.6).

격리: s05 `tests/workspace/test_dependencies.py` 와 동일한 확립된 패턴을 재사용한다. `DB_NAME`
을 전용 테스트 DB(`notion_lite_test`)로 바꾸고 `get_settings` 캐시를 비운 뒤 그 시점 URL 로
새 엔진·세션 팩토리를 만들고, `get_db` 를 override 한 실제 앱에 테스트 전용 라우트만 부착한다.
종료 시 테이블을 모두 제거하고 엔진을 dispose 한 뒤 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.auth import AuthContext
from app.common.db import Base, get_db
from app.document.dependencies import Role, ws_role_for_document
from app.main import create_app
from app.models import Document, User, Workspace, WorkspaceMember

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

    def __init__(
        self,
        app,
        workspace_id,
        document_id,
        missing_document_id,
        owner_id,
        member_id,
        non_member_id,
        admin_id,
    ):
        self.app = app
        self.workspace_id = workspace_id
        self.document_id = document_id
        self.missing_document_id = missing_document_id
        self.owner_id = owner_id
        self.member_id = member_id
        self.non_member_id = non_member_id
        self.admin_id = admin_id


@pytest.fixture
def wiring():
    """테스트 DB 를 마이그레이션·시드하고, get_db 를 override 한 실제 앱을 제공한다.

    핵심: 보호 라우트를 경로 파라미터 문서 `{id}` 로 선언하고 s07 어댑터
    `ws_role_for_document(Role.MEMBER)` 를 부착한다(문서 id → workspace_id 매핑 검증).
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

        owner = _make_user(seed, login_id="doc-adapter-owner")
        member = _make_user(seed, login_id="doc-adapter-member")
        non_member = _make_user(seed, login_id="doc-adapter-nonmember")
        admin = _make_user(seed, login_id="doc-adapter-admin", is_admin=True)

        seed.add_all(
            [
                WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"),
                WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member"),
            ]
        )

        doc = Document(
            workspace_id=ws.id,
            parent_id=None,
            title="어댑터 대상 문서",
            status="active",
            sort_order=Decimal("1000"),
            created_by=owner.id,
            created_at=datetime.utcnow(),
        )
        seed.add(doc)
        seed.flush()

        document_id = doc.id
        seed.commit()

        ids = _Wiring(
            app=None,
            workspace_id=ws.id,
            document_id=document_id,
            missing_document_id=document_id + 100_000,  # 존재하지 않는 문서 id.
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

    # 핵심: 경로 파라미터를 문서 {id} 로 선언하고 s07 어댑터를 부착한다(문서→WS 매핑 검증).
    def _doc_probe(
        id: int,
        ctx: AuthContext = Depends(ws_role_for_document(Role.MEMBER)),
    ):
        return {"id": id, "user_id": ctx.user_id}

    app.add_api_route("/_test/login/{uid}", _login_as, methods=["POST"])
    app.add_api_route("/_test/logout", _logout, methods=["POST"])
    app.add_api_route("/_doc_probe/{id}", _doc_probe, methods=["GET"])

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
    return f"/_doc_probe/{wiring.document_id}"


# --- 문서 id → workspace_id 브리징 후 s01 위임 (Req 10.3, 10.4) ---


def test_owner_via_document_id_passes_member_gate_200(wiring):
    """owner 멤버는 문서 {id} 경로로 구성한 ws_role_for_document(MEMBER) 통과 → 200.

    경로가 문서 `{id}` 인데도 통과한다는 것은 어댑터가 문서→workspace_id 를 실제로 매핑해
    s01 resolver 가 role 을 판정했음을 의미한다(매핑이 없었다면 workspace_id 를 찾지 못한다).
    """
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.owner_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == wiring.document_id
    assert body["user_id"] == wiring.owner_id


def test_member_via_document_id_passes_member_gate_200(wiring):
    """member 는 MEMBER 요구 편집 라우트를 위계 충족으로 통과 → 200 (Req 4.1, 10.3)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.member_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == wiring.member_id


def test_non_member_denied_403(wiring):
    """비멤버는 어떤 role 도 없어 편집 게이트에서 거부 → 403 (Req 4.6, 10.3)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.non_member_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_admin_bypasses_to_200(wiring):
    """admin 은 멤버십·role 무관하게 어댑터를 통과 → 200 (Req 10.4, INV-3 admin bypass)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.admin_id}").status_code == 200
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == wiring.admin_id


# --- 문서 미존재 → 404 (판정 이전 매핑 실패, Req 10.4) ---


def test_missing_document_returns_404(wiring):
    """존재하지 않는 문서 id 는 workspace_id 매핑 실패로 404 (not_found)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.owner_id}").status_code == 200
        resp = client.get(f"/_doc_probe/{wiring.missing_document_id}")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_missing_document_404_precedes_admin(wiring):
    """admin 이라도 문서 자체가 없으면 판정에 앞서 404 를 낸다(매핑이 판정보다 먼저)."""
    with TestClient(wiring.app) as client:
        assert client.post(f"/_test/login/{wiring.admin_id}").status_code == 200
        resp = client.get(f"/_doc_probe/{wiring.missing_document_id}")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 미인증(세션 없음) → 401 ---


def test_unauthenticated_401(wiring):
    """세션 없이 요청하면 s01 get_current_user 가 401 을 낸다(문서 조회 이전)."""
    with TestClient(wiring.app) as client:
        resp = client.get(_probe_url(wiring))

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 계약 정합: 어댑터가 s01 판정 로직을 재구현하지 않고 위임한다 ---


def test_adapter_reexports_s01_role():
    """어댑터 모듈이 노출하는 Role 은 s01 공통 IntEnum 과 동일 객체다(재정의 없음)."""
    from app.common.permissions import Role as S01Role

    assert Role is S01Role
