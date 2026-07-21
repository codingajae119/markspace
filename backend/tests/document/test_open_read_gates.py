"""문서 트리·상세 읽기 전역 개방 게이트 검증 (Task 3.2 / Req 3.1, 3.2, 3.6, 3.7, 3.8, 7.2).

s26-open-access-roles 는 문서 읽기(트리 목록·상세)를 role 위임 없는 활성 사용자 게이트로
전환한다:
- 트리 목록(`GET /workspaces/{workspace_id}/documents`)은 공통 `require_active_workspace`
  (활성+WS 존재→404, role 없음)로 게이팅한다.
- 상세(`GET /documents/{id}`)는 신규 `active_user_for_document`(문서 id→ws 매핑, 부재 404,
  role 없음)로 게이팅한다.

핵심 주장: 비멤버 활성 사용자가 존재하는 문서/트리를 조회하면 403 이 아니라 200 을 받고
(R3.8·R7.2), 부재 리소스는 404(R3.7), 미인증은 401(R3.6)이다. 편집 라우트(생성·수정·이동·
삭제)는 여전히 멤버 게이트를 유지하므로 여기서 검증하지 않는다.

DB 없이 라우터 결선만 확인한다(test_router.py 와 동일한 fake 세션 패턴): 어댑터의
`db.scalar`(문서→ws)와 `require_active_workspace` 의 `db.query(Workspace.id).first()` 를
모두 지원하는 가짜 세션을 주입하고, 서비스는 canned 응답 스텁으로 대체한다.
"""

from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.document.router import get_document_service
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
    """DocumentService 인터페이스를 흉내내는 최소 스텁(읽기 두 메서드만 필요)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_document(self, db, document_id) -> DocumentRead:
        self.calls.append(("get_document", document_id))
        return _DOC_READ

    def list_documents(self, db, workspace_id, limit, offset) -> Page[DocumentRead]:
        self.calls.append(("list_documents", workspace_id, limit, offset))
        return _DOC_PAGE


class _FakeQuery:
    def __init__(self, result) -> None:
        self._result = result

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def first(self):
        return self._result

    def one_or_none(self):
        return self._result


class _FakeSession:
    """읽기 게이트 두 접근을 지원한다.

    - ``active_user_for_document`` → ``db.scalar`` 로 문서→workspace_id(None=부재).
    - ``require_active_workspace`` → ``db.query(Workspace.id).filter(...).first()`` 로
      WS 존재검사(None=부재).
    """

    def __init__(self, *, ws_exists: bool, doc_ws_id) -> None:
        self._ws_exists = ws_exists
        self._doc_ws_id = doc_ws_id

    def scalar(self, *args, **kwargs):
        return self._doc_ws_id

    def query(self, model) -> _FakeQuery:
        return _FakeQuery((1,) if self._ws_exists else None)


def _build_app(*, ws_exists: bool = True, doc_ws_id=42):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(document_router)

    service_fake = _FakeDocumentService()
    app.dependency_overrides[get_document_service] = lambda: service_fake

    def _fake_db():
        yield _FakeSession(ws_exists=ws_exists, doc_ws_id=doc_ws_id)

    app.dependency_overrides[get_db] = _fake_db
    return app, service_fake


def _login_non_member(app: FastAPI) -> None:
    """멤버십 없는 활성 사용자로 인증 컨텍스트를 주입한다(is_admin=False)."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=7, is_admin=False
    )


# --- 비멤버 활성 사용자 → 200 (403 아님) : R3.8·R7.2 ----------------------------


def test_non_member_reads_document_detail_200_not_403():
    """비멤버 활성 사용자가 존재하는 문서 상세를 조회하면 403 이 아니라 200."""
    app, service_fake = _build_app(doc_ws_id=42)
    _login_non_member(app)
    client = TestClient(app)

    resp = client.get("/documents/100")

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == 100
    assert service_fake.calls[-1] == ("get_document", 100)


def test_non_member_reads_document_tree_200_not_403():
    """비멤버 활성 사용자가 존재하는 WS 의 문서 트리를 조회하면 403 이 아니라 200."""
    app, service_fake = _build_app(ws_exists=True)
    _login_non_member(app)
    client = TestClient(app)

    resp = client.get("/workspaces/42/documents")

    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1
    assert service_fake.calls[-1] == ("list_documents", 42, 50, 0)


# --- 부재 리소스 → 404 : R3.7 --------------------------------------------------


def test_absent_document_detail_404():
    """존재하지 않는 문서 id 는 어댑터 매핑 실패로 404(role 판정 이전)."""
    app, _ = _build_app(doc_ws_id=None)  # scalar None = 문서 부재
    _login_non_member(app)
    client = TestClient(app)

    resp = client.get("/documents/999")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_absent_workspace_tree_404():
    """존재하지 않는 워크스페이스 트리 조회는 404."""
    app, _ = _build_app(ws_exists=False)  # first() None = WS 부재
    _login_non_member(app)
    client = TestClient(app)

    resp = client.get("/workspaces/999/documents")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 미인증 → 401 : R3.6 -------------------------------------------------------


def test_unauthenticated_document_detail_401():
    """세션 없이 문서 상세를 조회하면 get_current_user 가 401 을 낸다."""
    app, _ = _build_app()
    client = TestClient(app)  # 로그인 override 없음 → 실제 get_current_user

    resp = client.get("/documents/100")

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


def test_unauthenticated_document_tree_401():
    """세션 없이 문서 트리를 조회하면 get_current_user 가 401 을 낸다."""
    app, _ = _build_app()
    client = TestClient(app)

    resp = client.get("/workspaces/42/documents")

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 게이트 결선 계약: 읽기 라우트가 신규 게이트에 의존한다 ---------------------


def test_read_routes_depend_on_open_access_gates():
    """상세=active_user_for_document, 트리=require_active_workspace 에 의존한다."""
    from app.common.permissions import require_active_workspace
    from app.document.dependencies import active_user_for_document

    detail_deps = {
        d.call for d in _route_dependencies("/documents/{id}", "GET")
    }
    tree_deps = {
        d.call for d in _route_dependencies("/workspaces/{workspace_id}/documents", "GET")
    }

    assert active_user_for_document in detail_deps
    assert require_active_workspace in tree_deps


def _route_dependencies(path: str, method: str):
    """지정 라우트의 의존성(Depends) 목록을 돌려준다."""
    for route in document_router.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route, "methods", set()
        ):
            return route.dependant.dependencies
    raise AssertionError(f"route not found: {method} {path}")
