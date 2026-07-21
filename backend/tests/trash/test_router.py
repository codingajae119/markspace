"""TrashRouter 결선 단위 테스트 (Task 3.1 / Req 1.7, 1.8, 2.5, 2.6, 3.4, 3.6,
5.1, 5.2, 5.3, 5.5, 5.6, 6.3, 6.4, 6.5).

design.md §Components → TrashRouter API Contract 표(카탈로그 행 29~31)와 게이트 결선을
검증한다. DB 없이 라우터 결선만 확인한다:
- 결선/스키마/위임: `get_trash_service` 를 가짜로 override 하고 `get_current_user` 를 인증
  컨텍스트로 주입해 3개 엔드포인트의 경로·메서드·상태코드·응답 스키마·서비스 위임을 단위
  검증한다.
- 실제 게이트 동작(401/403/admin-bypass): `get_current_user` 로 인증 컨텍스트를 주입하고
  `get_db` 를 가짜 세션으로 교체해 두 게이트 경로를 재현한다:
    * `/workspaces/{id}/trash` → s05 `require_ws_role`({id}→workspace_id 브리지) 게이트.
    * `/trash/{bundleId}/*` → s10 `ws_role_for_bundle`(묶음→WS 어댑터) 게이트.
  fake 세션은 어댑터의 `db.scalar`(묶음→ws) 와 resolver 의
  `db.query(WorkspaceMember).filter(...).one_or_none()` 를 모두 지원한다.

핵심 불변식:
- 정확히 3개 엔드포인트가 등록된다(GET /workspaces/{id}/trash,
  POST /trash/{bundleId}/restore, DELETE /trash/{bundleId}).
- 세 경로 모두 MEMBER 게이트를 부착한다(휴지통은 읽기 전역 개방에서 제외, R7.4). 목록은
  {id}=workspace_id 브리지, 복구·완전삭제는 {bundleId}→WS 어댑터를 사용한다.
- 성공 계약: 목록 200 Page[TrashBundleRead], 복구 204(no body), 완전삭제 204(no body).
- 위임: 각 핸들러가 올바른 인자로 대응 서비스 메서드를 호출한다.
- 미인증 → 401, 비멤버 → 403, admin → bypass, 유효하지 않은 묶음 루트 → 404.
- 서비스의 DomainError(NOT_FOUND, 404) 패스스루 → 404 ErrorResponse.
- DELETE /trash/{bundleId} OpenAPI 설명에 비가역성 표기.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers
from app.schemas.base import Page
from app.trash.router import get_trash_service
from app.trash.router import router as trash_router
from app.trash.schemas import TrashBundleRead, TrashMemberRead

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_EXPIRES = datetime(2026, 1, 31, 0, 0, 0)
_BUNDLE_READ = TrashBundleRead(
    bundle_id=100,
    root_document_id=100,
    root_title="휴지통 루트",
    workspace_id=42,
    trashed_at=_NOW,
    expires_at=_EXPIRES,
    member_count=1,
    members=[TrashMemberRead(id=100, parent_id=None, title="휴지통 루트")],
)
_TRASH_PAGE = Page[TrashBundleRead](items=[_BUNDLE_READ], total=1)


class _FakeTrashService:
    """TrashService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s10 계약). 호출을 기록하고 canned 응답을 반환한다.
    `error` 를 설정하면 restore/purge 가 이를 raise 해 서비스 오류 패스스루를 검증한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.error: DomainError | None = None

    def list_trash(self, db, workspace_id, limit, offset) -> Page[TrashBundleRead]:
        self.calls.append(("list_trash", workspace_id, limit, offset))
        if self.error is not None:
            raise self.error
        return _TRASH_PAGE

    def restore(self, db, bundle_id) -> None:
        self.calls.append(("restore", bundle_id))
        if self.error is not None:
            raise self.error
        return None

    def purge(self, db, bundle_id) -> None:
        self.calls.append(("purge", bundle_id))
        if self.error is not None:
            raise self.error
        return None


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
    """`ws_role_for_bundle` 어댑터의 ``db.scalar``(묶음→workspace_id)·resolver 의
    ``db.query`` 를 지원한다. `/workspaces/{id}/trash` 게이트는 scalar 를 쓰지 않고 경로
    {id} 를 그대로 workspace_id 로 사용하므로 query 만 소비한다."""

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
    app.include_router(trash_router)

    service_fake = _FakeTrashService()
    app.dependency_overrides[get_trash_service] = lambda: service_fake
    # 기본: get_db 는 무해한 스텁(admin bypass 시 resolver 는 db.query 를 타지 않지만,
    # 묶음 어댑터는 항상 scalar 로 묶음→ws 매핑을 하므로 42 를 돌려준다).
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
    ("get", "/workspaces/42/trash", None),
    ("post", "/trash/100/restore", None),
    ("delete", "/trash/100", None),
]


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_three_routes_registered():
    app, _ = _build_app()
    paths = app.openapi()["paths"]
    ops = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
    }
    assert ops == {
        ("/workspaces/{id}/trash", "GET"),
        ("/trash/{bundleId}/restore", "POST"),
        ("/trash/{bundleId}", "DELETE"),
    }


def test_purge_openapi_marks_irreversible():
    """DELETE /trash/{bundleId} 설명이 비가역성·프론트엔드 확인 UX 계약을 표기한다(Req 3.4)."""
    app, _ = _build_app()
    op = app.openapi()["paths"]["/trash/{bundleId}"]["delete"]
    description = op.get("description", "")
    assert description  # 비어 있지 않다.
    assert "되돌릴 수 없" in description  # 비가역성 표기.
    assert "프론트엔드" in description  # 확인 절차는 프론트엔드 UX 계약.


# --- 성공 계약(admin 인증으로 게이트 bypass) -------------------------------------


def test_list_returns_200_page_and_delegates():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/42/trash")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["bundle_id"] == 100
    assert body["items"][0]["root_document_id"] == 100
    assert body["items"][0]["member_count"] == 1
    assert service_fake.calls[-1] == ("list_trash", 42, 50, 0)


def test_list_forwards_query_params():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/42/trash", params={"limit": 10, "offset": 20})

    assert resp.status_code == 200
    assert service_fake.calls[-1] == ("list_trash", 42, 10, 20)


def test_list_path_id_used_as_workspace_id():
    """목록은 경로 {id} 를 workspace_id 로 서비스에 전달한다(Req 5.1·5.6)."""
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/777/trash")

    assert resp.status_code == 200
    assert service_fake.calls[-1] == ("list_trash", 777, 50, 0)


def test_restore_returns_204_no_body_and_delegates():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/trash/100/restore")

    assert resp.status_code == 204
    assert resp.content == b""
    assert service_fake.calls[-1] == ("restore", 100)


def test_purge_returns_204_no_body_and_delegates():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.delete("/trash/100")

    assert resp.status_code == 204
    assert resp.content == b""
    assert service_fake.calls[-1] == ("purge", 100)


def test_restore_forwards_path_bundle_id():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/trash/555/restore")

    assert resp.status_code == 204
    assert service_fake.calls[-1] == ("restore", 555)


def test_purge_forwards_path_bundle_id():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.delete("/trash/555")

    assert resp.status_code == 204
    assert service_fake.calls[-1] == ("purge", 555)


# --- 게이트: member 통과(MEMBER) -------------------------------------------------


@pytest.mark.parametrize("method,path", [
    ("get", "/workspaces/42/trash"),
    ("post", "/trash/100/restore"),
    ("delete", "/trash/100"),
])
def test_member_gate_member_passes(method, path):
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)

    resp = getattr(client, method)(path)

    assert resp.status_code in (200, 204), resp.text


@pytest.mark.parametrize("method,path", [
    ("get", "/workspaces/42/trash"),
    ("post", "/trash/100/restore"),
    ("delete", "/trash/100"),
])
def test_member_gate_non_member_forbidden_403(method, path):
    """비멤버 → 403 (휴지통은 개방 제외, member 이상 요구; Req 4.6·7.4·INV-2)."""
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    resp = getattr(client, method)(path)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


@pytest.mark.parametrize("method,path", [
    ("get", "/workspaces/42/trash"),
    ("post", "/trash/100/restore"),
    ("delete", "/trash/100"),
])
def test_admin_bypasses_gate(method, path):
    """admin 은 비멤버여도 게이트를 bypass 한다(Req 5.3·INV-3)."""
    app, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)  # 비멤버여도 admin bypass.
    client = TestClient(app)

    resp = getattr(client, method)(path)

    assert resp.status_code in (200, 204), resp.text


# --- 미인증(세션 없음) → 401 ----------------------------------------------------


@pytest.mark.parametrize("method,path,json_body", _ROUTES)
def test_unauthenticated_401(method, path, json_body):
    """세션 인증 없음 → 401(Req 5.5)."""
    app, _ = _build_app()
    client = TestClient(app)

    resp = getattr(client, method)(path)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 묶음 문서 부재 → 어댑터 404 -------------------------------------------------


@pytest.mark.parametrize("method,path", [
    ("post", "/trash/100/restore"),
    ("delete", "/trash/100"),
])
def test_missing_bundle_document_returns_404(method, path):
    """묶음 id 문서 부재 → 어댑터가 판정 앞서 404(Req 6.3)."""
    app, _ = _build_app()
    _login(app, user_id=99, is_admin=True)  # admin 이어도 어댑터가 묶음 부재로 404.
    _set_db(app, workspace_id=None, role=None)  # scalar → None: 묶음 문서 미존재.
    client = TestClient(app)

    resp = getattr(client, method)(path)

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 서비스(엔진) 오류 패스스루: 유효하지 않은 묶음 루트 → 404 -------------------


@pytest.mark.parametrize("method,path,service_call", [
    ("post", "/trash/100/restore", "restore"),
    ("delete", "/trash/100", "purge"),
])
def test_invalid_bundle_root_service_404_passthrough(method, path, service_call):
    """유효하지 않은 묶음 루트 → 서비스가 엔진 DomainError(NOT_FOUND, 404) 를 전파하고
    라우터가 s01 전역 핸들러로 404 ErrorResponse 를 낸다(Req 2.6·3.6·6.3)."""
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)  # 게이트 통과(admin bypass) 후 서비스가 404.
    service_fake.error = DomainError(
        code=ErrorCode.NOT_FOUND, message="유효한 묶음 루트가 아님", http_status=404
    )
    client = TestClient(app)

    resp = getattr(client, method)(path)

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    assert service_fake.calls[-1][0] == service_call
