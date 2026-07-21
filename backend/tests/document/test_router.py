"""DocumentRouter 결선 단위 테스트 (Task 4.1 / Req 1.1, 1.6, 1.7, 2.1, 2.4, 2.6,
3.1, 3.2, 4.1, 4.6, 5.1, 5.2, 5.6, 10.2, 10.3, 10.5).

design.md §Components → DocumentRouter API Contract 표(행 18~23)와 게이트 결선을 검증한다.
DB 없이 라우터 결선만 확인한다:
- 결선/스키마/위임: `get_document_service`·`get_state_engine`·`get_document_repository` 를
  가짜로 override 하고 `get_current_user` 를 admin 컨텍스트로 주입해(게이트 bypass, INV-3)
  6개 엔드포인트의 경로·메서드·상태코드·응답 스키마·서비스/엔진 위임을 단위 검증한다.
- 실제 게이트 동작(401/403/admin-bypass): `get_current_user` 로 인증 컨텍스트를 주입하고
  `get_db` 를 가짜 세션으로 교체해 두 게이트 계열을 재현한다:
    * `/workspaces/{workspace_id}/documents` → s01 `require_ws_role`(경로 workspace_id 직접).
    * `/documents/{id}` → `ws_role_for_document` 어댑터(문서 id → workspace_id 매핑 후 s01 위임).
  fake 세션은 어댑터의 `db.scalar`(문서→ws) 와 resolver 의
  `db.query(WorkspaceMember).filter(...).one_or_none()` 를 모두 지원한다.

핵심 불변식:
- 정확히 6개 엔드포인트가 등록된다(POST/GET /workspaces/{id}/documents,
  GET/PATCH/DELETE /documents/{id}, POST /documents/{id}/move).
- 생성·수정·이동·삭제는 MEMBER 게이트, 조회·목록은 s26 읽기 전역 개방(활성 사용자 게이트,
  role 판정 없음 — 비멤버도 200)을 부착한다.
- 성공 계약: POST create 201, GET 200, PATCH 200, POST move 200, DELETE 204(no body).
- DELETE 는 엔진 `trash_document` 를 호출하고 비active 대상→409(엔진 raise)로 직렬화된다.
- `/documents/{id}` 대상 문서 미존재 → 어댑터가 404 를 낸다.
- 스키마 검증 실패(필수 누락·공백 title)→422 s01 ErrorResponse(code "validation_error").
"""

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers
from app.document.router import (
    get_document_repository,
    get_document_service,
    get_state_engine,
)
from app.document.router import router as document_router
from app.document.schemas import DocumentRead
from app.schemas.base import Page

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_DOC_READ = DocumentRead(
    id=100,
    created_at=_NOW,
    updated_at=None,
    workspace_id=42,
    parent_id=None,
    title="문서",
    status="active",
    sort_order=Decimal("1000"),
    current_version_id=None,
    created_by=7,
    content="",
    content_html="",
)
_DOC_PAGE = Page[DocumentRead](items=[_DOC_READ], total=1)


class _FakeDocumentService:
    """DocumentService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s07 계약). 호출을 기록하고 canned 응답을 반환한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_document(self, db, ctx, workspace_id, payload) -> DocumentRead:
        self.calls.append(
            ("create_document", ctx.user_id, workspace_id, payload.title)
        )
        return _DOC_READ

    def get_document(self, db, document_id) -> DocumentRead:
        self.calls.append(("get_document", document_id))
        return _DOC_READ

    def list_documents(self, db, workspace_id, limit, offset) -> Page[DocumentRead]:
        self.calls.append(("list_documents", workspace_id, limit, offset))
        return _DOC_PAGE

    def update_document(self, db, document_id, changes) -> DocumentRead:
        self.calls.append(("update_document", document_id, changes.title))
        return _DOC_READ

    def move_document(self, db, document_id, payload) -> DocumentRead:
        self.calls.append(("move_document", document_id, payload.new_parent_id))
        return _DOC_READ


class _FakeDocument:
    """엔진에 넘길 ORM 문서 자리끼(도메인 속성은 필요 없다)."""

    def __init__(self, doc_id: int) -> None:
        self.id = doc_id


class _FakeRepository:
    """DocumentRepository.get 만 흉내내는 스텁(DELETE 오케스트레이션용)."""

    def __init__(self, doc=None) -> None:
        self.doc = doc if doc is not None else _FakeDocument(100)
        self.calls: list[tuple] = []

    def get(self, db, document_id):
        self.calls.append(("get", document_id))
        return self.doc


class _FakeStateEngine:
    """DocumentStateEngine.trash_document 만 흉내내는 스텁."""

    def __init__(self) -> None:
        self.error: DomainError | None = None
        self.calls: list[tuple] = []

    def trash_document(self, db, document):
        self.calls.append(("trash_document", document.id))
        if self.error is not None:
            raise self.error
        return object()


# --- 가짜 DB 세션: 어댑터(scalar)·resolver(query) 두 접근만 지원 -------------------


class _FakeMember:
    def __init__(self, role: str) -> None:
        self.role = role


class _FakeQuery:
    def __init__(self, member, *, ws_exists) -> None:
        self._member = member
        self._ws_exists = ws_exists

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def one_or_none(self):
        return self._member

    def first(self):
        # s26 require_active_workspace 의 ``db.query(Workspace.id)...first()`` 존재검사.
        # WS 존재 시 truthy row, 부재 시 None(→404) 을 흉내낸다.
        return (1,) if self._ws_exists else None


class _FakeSession:
    """어댑터의 ``db.scalar``(문서→workspace_id)·resolver 의 ``db.query``(role/WS 존재)를 지원한다."""

    def __init__(self, *, workspace_id, member, ws_exists=True) -> None:
        self._workspace_id = workspace_id
        self._member = member
        self._ws_exists = ws_exists

    def scalar(self, *args, **kwargs):
        return self._workspace_id

    def query(self, model) -> _FakeQuery:
        return _FakeQuery(self._member, ws_exists=self._ws_exists)


def _build_app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(document_router)

    service_fake = _FakeDocumentService()
    engine_fake = _FakeStateEngine()
    repo_fake = _FakeRepository()
    app.dependency_overrides[get_document_service] = lambda: service_fake
    app.dependency_overrides[get_state_engine] = lambda: engine_fake
    app.dependency_overrides[get_document_repository] = lambda: repo_fake
    # 기본: get_db 는 무해한 스텁(admin bypass 시 resolver 는 db.query 를 타지 않지만,
    # /documents/{id} 어댑터는 항상 scalar 로 문서→ws 매핑을 하므로 42 를 돌려준다).
    _set_db(app, workspace_id=42, role=None)
    return app, service_fake, engine_fake, repo_fake


def _login(app: FastAPI, *, user_id: int = 7, is_admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=user_id, is_admin=is_admin
    )


def _set_db(app: FastAPI, *, workspace_id, role, ws_exists=True) -> None:
    """get_db 를 override — 어댑터엔 workspace_id, resolver 엔 role 멤버, 읽기 게이트엔 WS 존재를 노출한다."""
    member = _FakeMember(role) if role is not None else None

    def _fake_db():
        yield _FakeSession(workspace_id=workspace_id, member=member, ws_exists=ws_exists)

    app.dependency_overrides[get_db] = _fake_db


# 각 라우트를 (method, path, json_body) 로 나열(미인증 401 검증에 재사용).
_ROUTES = [
    ("post", "/workspaces/42/documents", {"title": "문서"}),
    ("get", "/workspaces/42/documents", None),
    ("get", "/documents/100", None),
    ("patch", "/documents/100", {"title": "새 제목"}),
    ("post", "/documents/100/move", {"new_parent_id": 5}),
    ("delete", "/documents/100", None),
]


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_six_routes_registered():
    app, _, _, _ = _build_app()
    paths = app.openapi()["paths"]
    ops = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
    }
    assert ops == {
        ("/workspaces/{workspace_id}/documents", "POST"),
        ("/workspaces/{workspace_id}/documents", "GET"),
        ("/documents/{id}", "GET"),
        ("/documents/{id}", "PATCH"),
        ("/documents/{id}", "DELETE"),
        ("/documents/{id}/move", "POST"),
    }


# --- 성공 계약(admin 인증으로 게이트 bypass) -------------------------------------


def test_create_document_returns_201_and_delegates():
    app, service_fake, _, _ = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = client.post("/workspaces/42/documents", json={"title": "새 문서"})

    assert resp.status_code == 201
    assert resp.json()["id"] == 100
    assert service_fake.calls[-1] == ("create_document", 7, 42, "새 문서")


def test_create_document_with_parent_delegates():
    app, service_fake, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post(
        "/workspaces/42/documents", json={"title": "자식", "parent_id": 9}
    )

    assert resp.status_code == 201
    assert service_fake.calls[-1] == ("create_document", 7, 42, "자식")


def test_list_documents_returns_200_default_pagination():
    app, service_fake, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/42/documents")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 100
    assert service_fake.calls[-1] == ("list_documents", 42, 50, 0)


def test_list_documents_forwards_query_params():
    app, service_fake, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.get("/workspaces/42/documents", params={"limit": 10, "offset": 20})

    assert resp.status_code == 200
    assert service_fake.calls[-1] == ("list_documents", 42, 10, 20)


def test_get_document_returns_200_and_delegates():
    app, service_fake, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.get("/documents/100")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 100
    assert body["content"] == ""
    assert body["content_html"] == ""
    assert service_fake.calls[-1] == ("get_document", 100)


def test_update_document_returns_200_and_delegates():
    app, service_fake, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.patch("/documents/100", json={"title": "갱신"})

    assert resp.status_code == 200
    assert resp.json()["id"] == 100
    assert service_fake.calls[-1] == ("update_document", 100, "갱신")


def test_move_document_returns_200_and_delegates():
    app, service_fake, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/move", json={"new_parent_id": 5})

    assert resp.status_code == 200
    assert resp.json()["id"] == 100
    assert service_fake.calls[-1] == ("move_document", 100, 5)


def test_move_document_empty_body_moves_to_root():
    app, service_fake, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/documents/100/move", json={})

    assert resp.status_code == 200
    assert service_fake.calls[-1] == ("move_document", 100, None)


def test_delete_document_returns_204_and_calls_engine():
    app, _, engine_fake, repo_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.delete("/documents/100")

    assert resp.status_code == 204
    assert resp.content == b""
    assert repo_fake.calls[-1] == ("get", 100)
    assert engine_fake.calls[-1] == ("trash_document", 100)


# --- DELETE 오케스트레이션: 비active → 409, 대상 미존재 → 404 --------------------


def test_delete_non_active_target_returns_409():
    app, _, engine_fake, _ = _build_app()
    _login(app, is_admin=True)
    engine_fake.error = DomainError(
        code=ErrorCode.CONFLICT, message="not active", http_status=409
    )
    client = TestClient(app)

    resp = client.delete("/documents/100")

    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"


def test_delete_missing_document_via_repo_guard_returns_404():
    app, _, _, repo_fake = _build_app()
    _login(app, is_admin=True)
    repo_fake.doc = None  # 어댑터는 통과(scalar=42)하나 repo 재조회가 None → 404 가드.
    client = TestClient(app)

    resp = client.delete("/documents/100")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 게이트: 생성(MEMBER) --------------------------------------------------------


def test_create_document_member_passes():
    app, service_fake, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)

    resp = client.post("/workspaces/42/documents", json={"title": "문서"})

    assert resp.status_code == 201
    assert service_fake.calls[-1][0] == "create_document"


def test_create_document_non_member_forbidden_403():
    """비멤버는 MEMBER 편집 게이트에서 403 (Req 4.6)."""
    app, _, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    resp = client.post("/workspaces/42/documents", json={"title": "문서"})

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_create_document_admin_bypasses():
    app, service_fake, _, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)  # 비멤버여도 admin bypass(INV-3).
    client = TestClient(app)

    resp = client.post("/workspaces/42/documents", json={"title": "문서"})

    assert resp.status_code == 201
    assert service_fake.calls[-1][0] == "create_document"


# --- 게이트: 목록(읽기 전역 개방, s26) ------------------------------------------


def test_list_documents_member_passes():
    app, service_fake, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)

    resp = client.get("/workspaces/42/documents")

    assert resp.status_code == 200
    assert service_fake.calls[-1][0] == "list_documents"


def test_list_documents_non_member_open_read_200():
    """비멤버 활성 사용자도 트리를 읽는다 → 200 (Req 3.2·3.8, 읽기 개방, 403 제거)."""
    app, service_fake, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)  # 비멤버.
    client = TestClient(app)

    resp = client.get("/workspaces/42/documents")

    assert resp.status_code == 200
    assert service_fake.calls[-1][0] == "list_documents"


def test_list_documents_missing_workspace_404():
    """존재하지 않는 워크스페이스의 트리 조회 → 404 (Req 3.7)."""
    app, _, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None, ws_exists=False)
    client = TestClient(app)

    resp = client.get("/workspaces/42/documents")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 게이트: /documents/{id} 조회(읽기 전역 개방, s26) --------------------------


def test_get_document_member_passes():
    app, service_fake, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)

    resp = client.get("/documents/100")

    assert resp.status_code == 200
    assert service_fake.calls[-1][0] == "get_document"


def test_get_document_non_member_open_read_200():
    """비멤버 활성 사용자도 문서 상세를 읽는다 → 200 (Req 3.1·3.8, 읽기 개방, 403 제거)."""
    app, service_fake, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)  # 비멤버.
    client = TestClient(app)

    resp = client.get("/documents/100")

    assert resp.status_code == 200
    assert service_fake.calls[-1][0] == "get_document"


# --- 게이트: /documents/{id} 변경(MEMBER) — patch·move·delete --------------------


@pytest.mark.parametrize("method,path,json_body", [
    ("patch", "/documents/100", {"title": "x"}),
    ("post", "/documents/100/move", {}),
    ("delete", "/documents/100", None),
])
def test_document_mutation_member_passes(method, path, json_body):
    app, _, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code in (200, 204), resp.text


@pytest.mark.parametrize("method,path,json_body", [
    ("patch", "/documents/100", {"title": "x"}),
    ("post", "/documents/100/move", {}),
    ("delete", "/documents/100", None),
])
def test_document_mutation_non_member_forbidden_403(method, path, json_body):
    """비멤버는 MEMBER 편집 게이트에서 403 (Req 4.6)."""
    app, _, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_document_mutation_admin_bypasses():
    app, _, engine_fake, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    resp = client.delete("/documents/100")

    assert resp.status_code == 204
    assert engine_fake.calls[-1] == ("trash_document", 100)


# --- /documents/{id} 대상 문서 미존재 → 어댑터 404 ------------------------------


@pytest.mark.parametrize("method,path,json_body", [
    ("get", "/documents/100", None),
    ("patch", "/documents/100", {"title": "x"}),
    ("post", "/documents/100/move", {}),
    ("delete", "/documents/100", None),
])
def test_document_route_missing_document_returns_404(method, path, json_body):
    app, _, _, _ = _build_app()
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
    # get_current_user 를 override 하지 않는다: 세션 쿠키 없이 요청하면 s01
    # get_current_user 가 db 접근 전에 401 을 낸다.
    app, _, _, _ = _build_app()
    client = TestClient(app)
    kwargs = {"json": json_body} if json_body is not None else {}

    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 스키마 검증 실패 → 422 -----------------------------------------------------


def test_create_document_missing_title_returns_422():
    app, _, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/workspaces/42/documents", json={})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_create_document_blank_title_returns_422():
    app, _, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.post("/workspaces/42/documents", json={"title": "   "})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_update_document_blank_title_returns_422():
    app, _, _, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.patch("/documents/100", json={"title": "   "})

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"
