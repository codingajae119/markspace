"""버전 이력 읽기 전역 개방 게이트 결선 테스트 (Task 3.5 / Req 3.3, 3.6, 3.7, 3.8, 7.2).

design.md §Components → `active_user_for_document` 재사용: 버전 이력 조회
(`GET /documents/{id}/versions`)가 멤버 게이트(`ws_role_for_document(MEMBER)`)에서 신규 문서
읽기 게이트(`active_user_for_document`)로 전환됐음을 검증한다. 신규 교차 import 없이 기존
`app.document.dependencies` 재사용이며, 활성 사용자면 멤버십과 무관하게 200 을 받는다.

핵심 불변식(문서 상세 게이트와 대칭):
- 비멤버 활성 사용자 + 존재 문서 → 200 (403 아님) (R3.8·R7.2).
- 문서 부재 → 404 (앞 절반 매핑 유지).
- 미인증 → 401 (`get_current_user`).
- 버전 이력 라우트의 실제 의존성이 `active_user_for_document` 이다(라우트 결선 증거).

이 파일은 기존 `test_router.py`(멤버 게이트 전제 테스트, 5.3 에서 갱신 예정)와 분리해
개방 게이트만 독립 검증한다.
"""

from datetime import datetime

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.document.dependencies import active_user_for_document
from app.lock_version.router import get_lock_version_service
from app.lock_version.router import router as lock_version_router
from app.lock_version.schemas import DocumentVersionRead
from app.schemas.base import Page

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_VERSION_READ = DocumentVersionRead(id=555, document_id=100, created_by=7, created_at=_NOW)
_VERSION_PAGE = Page[DocumentVersionRead](items=[_VERSION_READ], total=1)


class _FakeLockVersionService:
    """list_versions 만 사용하는 최소 가짜 서비스(개방 게이트 검증용)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_versions(self, db, document_id, limit, offset) -> Page[DocumentVersionRead]:
        self.calls.append(("list_versions", document_id, limit, offset))
        return _VERSION_PAGE


class _FakeSession:
    """어댑터의 ``db.scalar``(문서→workspace_id) 만 지원한다.

    개방 게이트(`active_user_for_document`)는 멤버십을 조회하지 않으므로 ``db.query`` 는
    호출되지 않는다 — 호출되면 즉시 실패시켜 멤버십 조회 부재를 방어한다.
    """

    def __init__(self, *, workspace_id) -> None:
        self._workspace_id = workspace_id

    def scalar(self, *args, **kwargs):
        return self._workspace_id

    def query(self, *args, **kwargs):  # pragma: no cover - 방어용
        raise AssertionError("개방 게이트는 멤버십을 조회하지 않아야 한다")


def _build_app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(lock_version_router)

    service_fake = _FakeLockVersionService()
    app.dependency_overrides[get_lock_version_service] = lambda: service_fake
    return app, service_fake


def _set_db(app: FastAPI, *, workspace_id) -> None:
    def _fake_db():
        yield _FakeSession(workspace_id=workspace_id)

    app.dependency_overrides[get_db] = _fake_db


def _login(app: FastAPI, *, user_id: int = 3, is_admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=user_id, is_admin=is_admin
    )


def test_versions_non_member_active_user_returns_200():
    """비멤버 활성 사용자(role 없음, admin 아님) + 존재 문서 → 200 (403 아님) — R3.8·R7.2."""
    app, service_fake = _build_app()
    _login(app, user_id=3, is_admin=False)  # 비멤버(멤버십 없음).
    _set_db(app, workspace_id=42)  # 문서 존재 → workspace_id 매핑.
    client = TestClient(app)

    resp = client.get("/documents/100/versions")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 555
    assert service_fake.calls[-1] == ("list_versions", 100, 50, 0)


def test_versions_missing_document_returns_404():
    """문서 부재(scalar→None) → 404 — 앞 절반 매핑 유지 (R3.7)."""
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=None)
    client = TestClient(app)

    resp = client.get("/documents/100/versions")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_versions_unauthenticated_returns_401():
    """미인증(세션 없음) → 401 — get_current_user 가 활성 사용자 강제 (R3.6)."""
    app, _ = _build_app()
    _set_db(app, workspace_id=42)
    client = TestClient(app)

    resp = client.get("/documents/100/versions")

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_versions_route_depends_on_active_user_gate():
    """버전 이력 라우트의 실제 의존성이 `active_user_for_document` 다(라우트 결선 증거).

    멤버 게이트(`ws_role_for_document(...)` 클로저)는 이 심볼과 동일성이 성립하지 않으므로,
    이 어써션은 개방 게이트로의 실제 교체를 증명한다.
    """
    versions_route = next(
        r
        for r in lock_version_router.routes
        if getattr(r, "path", None) == "/documents/{id}/versions"
    )
    gate_calls = [d.call for d in versions_route.dependant.dependencies]
    assert active_user_for_document in gate_calls
