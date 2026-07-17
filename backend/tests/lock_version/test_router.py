"""LockVersionRouter 결선 단위 테스트 (Task 3.1 / Req 1.1, 1.5, 1.6, 2.1, 2.5,
3.1, 3.5, 4.1, 4.2, 5.1, 5.5, 7.1, 7.3, 7.4).

design.md §Components → LockVersionRouter API Contract 표(카탈로그 행 24~28)와 게이트
결선을 검증한다. DB 없이 라우터 결선만 확인한다:
- 결선/스키마/위임: `get_lock_version_service` 를 가짜로 override 하고 `get_current_user` 를
  admin 컨텍스트로 주입해(게이트 bypass, INV-3) 5개 엔드포인트의 경로·메서드·상태코드·응답
  스키마·서비스 위임을 단위 검증한다.
- 실제 게이트 동작(401/403/admin-bypass): `get_current_user` 로 인증 컨텍스트를 주입하고
  `get_db` 를 가짜 세션으로 교체해 `/documents/{id}` 어댑터(`ws_role_for_document`) 게이트를
  재현한다. fake 세션은 어댑터의 `db.scalar`(문서→ws) 와 resolver 의
  `db.query(WorkspaceMember).filter(...).one_or_none()` 를 모두 지원한다.

핵심 불변식:
- 정확히 5개 엔드포인트가 등록된다(POST /documents/{id}/lock·/save·/cancel·/force-unlock,
  GET /documents/{id}/versions).
- lock/save/cancel 은 EDITOR, force-unlock 은 OWNER, versions 는 VIEWER 게이트를 부착한다.
- 성공 계약: lock 200 DocumentLockRead, save 200 DocumentVersionRead, cancel 204(no body),
  force-unlock 204(no body), versions 200 Page[DocumentVersionRead].
- 위임: 각 핸들러가 올바른 인자로 대응 서비스 메서드를 호출한다.
- 미인증 → 401, 비멤버 → 403, 문서 미존재 → 어댑터 404.
- save 스키마 검증 실패(content 누락)→422 s01 ErrorResponse(code "validation_error").
- 서비스의 DomainError(CONFLICT, 409) 패스스루 → 409 ErrorResponse.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers
from app.lock_version.router import get_lock_version_service
from app.lock_version.router import router as lock_version_router
from app.lock_version.schemas import DocumentLockRead, DocumentVersionRead
from app.schemas.base import Page

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_LOCK_READ = DocumentLockRead(
    document_id=100, lock_user_id=7, lock_acquired_at=_NOW
)
_VERSION_READ = DocumentVersionRead(
    id=555, document_id=100, created_by=7, created_at=_NOW
)
_VERSION_PAGE = Page[DocumentVersionRead](items=[_VERSION_READ], total=1)


class _FakeLockVersionService:
    """LockVersionService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s09 계약). 호출을 기록하고 canned 응답을 반환한다.
    `error` 를 설정하면 lock/save/cancel 이 이를 raise 해 서비스 오류 패스스루를 검증한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.error: DomainError | None = None

    def start_edit(self, db, ctx, document_id) -> DocumentLockRead:
        self.calls.append(("start_edit", ctx.user_id, document_id))
        if self.error is not None:
            raise self.error
        return _LOCK_READ

    def save(self, db, ctx, document_id, payload) -> DocumentVersionRead:
        self.calls.append(("save", ctx.user_id, document_id, payload.content))
        if self.error is not None:
            raise self.error
        return _VERSION_READ

    def cancel_edit(self, db, ctx, document_id) -> None:
        self.calls.append(("cancel_edit", ctx.user_id, document_id))
        if self.error is not None:
            raise self.error
        return None

    def force_unlock(self, db, ctx, document_id) -> None:
        self.calls.append(("force_unlock", ctx.user_id, document_id))
        if self.error is not None:
            raise self.error
        return None

    def list_versions(self, db, document_id, limit, offset) -> Page[DocumentVersionRead]:
        self.calls.append(("list_versions", document_id, limit, offset))
        if self.error is not None:
            raise self.error
        return _VERSION_PAGE


# --- 가짜 DB 세션: 어댑터(scalar)·resolver(query) 두 접근만 지원 -------------------


class _FakeMember:
    def __init__(self, role: str) -> None:
        self.role = role


class _FakeQuery:
    def __init__(self, member) -> None:
        self._member = member

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def one_or_none(self):
        return self._member


class _FakeSession:
    """어댑터의 ``db.scalar``(문서→workspace_id)·resolver 의 ``db.query`` 를 지원한다."""

    def __init__(self, *, workspace_id, member) -> None:
        self._workspace_id = workspace_id
        self._member = member

    def scalar(self, *args, **kwargs):
        return self._workspace_id

    def query(self, model) -> _FakeQuery:
        return _FakeQuery(self._member)


def _build_app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(lock_version_router)

    service_fake = _FakeLockVersionService()
    app.dependency_overrides[get_lock_version_service] = lambda: service_fake
    # 기본: get_db 는 무해한 스텁(admin bypass 시 resolver 는 db.query 를 타지 않지만,
    # /documents/{id} 어댑터는 항상 scalar 로 문서→ws 매핑을 하므로 42 를 돌려준다).
    _set_db(app, workspace_id=42, role=None)
    return app, service_fake


def _login(app: FastAPI, *, user_id: int = 7, is_admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=user_id, is_admin=is_admin
    )


def _set_db(app: FastAPI, *, workspace_id, role) -> None:
    """get_db 를 override — 어댑터엔 workspace_id, resolver 엔 role 멤버를 노출한다."""
    member = _FakeMember(role) if role is not None else None

    def _fake_db():
        yield _FakeSession(workspace_id=workspace_id, member=member)

    app.dependency_overrides[get_db] = _fake_db


# 각 라우트를 (method, path, json_body) 로 나열(미인증 401 검증에 재사용).
_ROUTES = [
    ("post", "/documents/100/lock", None),
    ("post", "/documents/100/save", {"content": "hello"}),
    ("post", "/documents/100/cancel", None),
    ("post", "/documents/100/force-unlock", None),
    ("get", "/documents/100/versions", None),
]


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_five_routes_registered():
    app, _ = _build_app()
    paths = app.openapi()["paths"]
    ops = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
    }
    assert ops == {
        ("/documents/{id}/lock", "POST"),
        ("/documents/{id}/save", "POST"),
        ("/documents/{id}/cancel", "POST"),
        ("/documents/{id}/force-unlock", "POST"),
        ("/documents/{id}/versions", "GET"),
    }


# --- 성공 계약(admin 인증으로 게이트 bypass) -------------------------------------


def test_lock_returns_200_and_delegates():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/lock")

    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == 100
    assert body["lock_user_id"] == 7
    assert service_fake.calls[-1] == ("start_edit", 7, 100)


def test_save_returns_200_and_delegates():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/save", json={"content": "본문"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 555
    assert body["document_id"] == 100
    assert "content" not in body  # 버전 메타데이터만 노출(본문 없음).
    assert service_fake.calls[-1] == ("save", 7, 100, "본문")


def test_save_empty_content_is_valid():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/save", json={"content": ""})

    assert resp.status_code == 200
    assert service_fake.calls[-1] == ("save", 7, 100, "")


def test_cancel_returns_204_no_body_and_delegates():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/cancel")

    assert resp.status_code == 204
    assert resp.content == b""
    assert service_fake.calls[-1] == ("cancel_edit", 7, 100)


def test_force_unlock_returns_204_no_body_and_delegates():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/force-unlock")

    assert resp.status_code == 204
    assert resp.content == b""
    assert service_fake.calls[-1] == ("force_unlock", 7, 100)


def test_versions_returns_200_default_pagination():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.get("/documents/100/versions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 555
    assert service_fake.calls[-1] == ("list_versions", 100, 50, 0)


def test_versions_forwards_query_params():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.get("/documents/100/versions", params={"limit": 10, "offset": 20})

    assert resp.status_code == 200
    assert service_fake.calls[-1] == ("list_versions", 100, 10, 20)


# --- 게이트: lock/save/cancel (EDITOR) -------------------------------------------


@pytest.mark.parametrize("method,path,json_body", [
    ("post", "/documents/100/lock", None),
    ("post", "/documents/100/save", {"content": "x"}),
    ("post", "/documents/100/cancel", None),
])
def test_editor_gate_editor_passes(method, path, json_body):
    app, service_fake = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="editor")
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code in (200, 204), resp.text


@pytest.mark.parametrize("method,path,json_body", [
    ("post", "/documents/100/lock", None),
    ("post", "/documents/100/save", {"content": "x"}),
    ("post", "/documents/100/cancel", None),
])
@pytest.mark.parametrize("role", ["viewer", None])
def test_editor_gate_below_editor_forbidden_403(method, path, json_body, role):
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=role)
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


# --- 게이트: force-unlock (OWNER) ------------------------------------------------


def test_force_unlock_owner_passes():
    app, service_fake = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="owner")
    client = TestClient(app)

    resp = client.post("/documents/100/force-unlock")

    assert resp.status_code == 204
    assert service_fake.calls[-1][0] == "force_unlock"


@pytest.mark.parametrize("role", ["editor", "viewer", None])
def test_force_unlock_below_owner_forbidden_403(role):
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=role)
    client = TestClient(app)

    resp = client.post("/documents/100/force-unlock")

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_force_unlock_admin_bypasses():
    app, service_fake = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)  # 비멤버여도 admin bypass(INV-3).
    client = TestClient(app)

    resp = client.post("/documents/100/force-unlock")

    assert resp.status_code == 204
    assert service_fake.calls[-1][0] == "force_unlock"


# --- 게이트: versions (VIEWER) ---------------------------------------------------


def test_versions_viewer_passes():
    app, service_fake = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="viewer")
    client = TestClient(app)

    resp = client.get("/documents/100/versions")

    assert resp.status_code == 200
    assert service_fake.calls[-1][0] == "list_versions"


def test_versions_non_member_forbidden_403():
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    resp = client.get("/documents/100/versions")

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


# --- 대조: viewer 는 versions 만 통과, editor 는 mutation 만 통과 -----------------


def test_viewer_versions_pass_but_mutations_forbidden():
    """viewer 멤버십 → versions 200 이지만 lock/save/cancel/force-unlock 403."""
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="viewer")
    client = TestClient(app)

    assert client.get("/documents/100/versions").status_code == 200
    assert client.post("/documents/100/lock").status_code == 403
    assert client.post("/documents/100/save", json={"content": "x"}).status_code == 403
    assert client.post("/documents/100/cancel").status_code == 403
    assert client.post("/documents/100/force-unlock").status_code == 403


def test_editor_mutations_pass_but_force_unlock_forbidden():
    """editor 멤버십 → lock/save/cancel 200/204 이지만 force-unlock 403(OWNER)."""
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="editor")
    client = TestClient(app)

    assert client.post("/documents/100/lock").status_code == 200
    assert client.post("/documents/100/save", json={"content": "x"}).status_code == 200
    assert client.post("/documents/100/cancel").status_code == 204
    assert client.post("/documents/100/force-unlock").status_code == 403


# --- 문서 미존재 → 어댑터 404 ----------------------------------------------------


@pytest.mark.parametrize("method,path,json_body", _ROUTES)
def test_missing_document_returns_404(method, path, json_body):
    app, _ = _build_app()
    _login(app, user_id=99, is_admin=True)  # admin 이어도 어댑터가 문서 부재로 404.
    _set_db(app, workspace_id=None, role=None)  # scalar → None: 문서 미존재.
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 미인증(세션 없음) → 401 ----------------------------------------------------


@pytest.mark.parametrize("method,path,json_body", _ROUTES)
def test_unauthenticated_401(method, path, json_body):
    app, _ = _build_app()
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 스키마 검증 실패 → 422 -----------------------------------------------------


def test_save_missing_content_returns_422():
    app, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/save", json={})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_save_invalid_content_type_returns_422():
    app, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/save", json={"content": 123.5})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


# --- 서비스 오류 패스스루: DomainError(CONFLICT, 409) → 409 ---------------------


@pytest.mark.parametrize("method,path,json_body", [
    ("post", "/documents/100/lock", None),
    ("post", "/documents/100/save", {"content": "x"}),
    ("post", "/documents/100/cancel", None),
])
def test_service_conflict_passthrough_409(method, path, json_body):
    app, service_fake = _build_app()
    _login(app, is_admin=True)
    service_fake.error = DomainError(
        code=ErrorCode.CONFLICT, message="다른 사용자가 편집 중", http_status=409
    )
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"
