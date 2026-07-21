"""첨부 조회·다운로드 읽기 전역 개방 게이트 검증 (Task 3.3 / Req 3.4, 3.6, 3.7, 3.8, 7.2).

s26-open-access-roles 는 첨부 서빙(`GET /attachments/{id}`)을 role 위임 없는 활성 사용자
게이트로 전환한다:
- 서빙은 신규 `active_user_for_attachment`(첨부 id→ws 매핑, 부재 404, role 없음)로 게이팅한다.

핵심 주장: 비멤버 활성 사용자가 존재하는 첨부를 조회·다운로드하면 403 이 아니라 200 을 받고
(R3.4·R3.8·R7.2), 부재 첨부는 404(R3.7), 미인증은 401(R3.6)이다. 보관(is_archived) 첨부의
서빙 차단(role 무관 404)은 **권한 이전 서비스 단계**에서 그대로 처리되며, 읽기 게이트 전환이
이 불변식을 바꾸지 않는다(서비스가 여전히 404). 업로드 라우트는 멤버 게이트를 유지하므로
여기서 검증하지 않는다.

DB 없이 라우터 결선만 확인한다(test_router.py 와 동일한 fake 세션 패턴): 어댑터의
`db.get`(첨부→ws)만 지원하는 가짜 세션을 주입하고, 서비스는 canned 응답 스텁으로 대체한다.
"""

import io
from datetime import datetime

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.attachment.router import get_attachment_service
from app.attachment.router import router as attachment_router
from app.attachment.service import AttachmentBinary
from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers

_PNG_BYTES = b"\x89PNG\r\n\x1a\nDUMMYIMAGE"


class _FakeAttachmentService:
    """AttachmentService 서빙 인터페이스를 흉내내는 최소 스텁(serve 만 필요).

    `serve_error` 를 설정하면 `serve_attachment` 가 이를 raise 해 서비스 오류 패스스루
    (보관 404)를 검증한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.serve_error: DomainError | None = None

    def serve_attachment(self, db, attachment_id) -> AttachmentBinary:
        self.calls.append(("serve_attachment", attachment_id))
        if self.serve_error is not None:
            raise self.serve_error
        return AttachmentBinary(
            stream=io.BytesIO(_PNG_BYTES),
            content_type="image/png",
            filename="pic.png",
        )


class _FakeAttachment:
    """`active_user_for_attachment` 어댑터가 첨부 존재/workspace 매핑에 쓰는 자리끼."""

    def __init__(self, workspace_id: int) -> None:
        self.workspace_id = workspace_id


class _FakeSession:
    """읽기 게이트의 첨부 매핑 접근만 지원한다.

    - ``active_user_for_attachment`` → ``db.get(Attachment, id)`` 로 첨부 존재검사
      (None=부재). role 판정이 없으므로 멤버 조회(``db.query``)는 호출되지 않는다.
    """

    def __init__(self, *, attachment) -> None:
        self._attachment = attachment

    def get(self, model, ident):
        return self._attachment


def _build_app(*, attachment_ws=42):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(attachment_router)

    service_fake = _FakeAttachmentService()
    app.dependency_overrides[get_attachment_service] = lambda: service_fake

    attachment = _FakeAttachment(attachment_ws) if attachment_ws is not None else None

    def _fake_db():
        yield _FakeSession(attachment=attachment)

    app.dependency_overrides[get_db] = _fake_db
    return app, service_fake


def _login_non_member(app: FastAPI) -> None:
    """멤버십 없는 활성 사용자로 인증 컨텍스트를 주입한다(is_admin=False)."""
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=7, is_admin=False
    )


# --- 비멤버 활성 사용자 → 200 (403 아님) : R3.4·R3.8·R7.2 ----------------------


def test_non_member_serves_attachment_200_not_403():
    """비멤버 활성 사용자가 존재하는 첨부를 조회하면 403 이 아니라 200 + 바이너리."""
    app, service_fake = _build_app(attachment_ws=42)
    _login_non_member(app)
    client = TestClient(app)

    resp = client.get("/attachments/500")

    assert resp.status_code == 200, resp.text
    assert resp.content == _PNG_BYTES
    assert resp.headers["content-type"].startswith("image/png")
    assert service_fake.calls[-1] == ("serve_attachment", 500)


def test_non_member_downloads_attachment_forwards_path_id():
    """비멤버 활성 사용자의 다운로드도 200 이며 경로 첨부 id 를 서비스에 전달한다."""
    app, service_fake = _build_app(attachment_ws=42)
    _login_non_member(app)
    client = TestClient(app)

    resp = client.get("/attachments/777")

    assert resp.status_code == 200, resp.text
    assert service_fake.calls[-1] == ("serve_attachment", 777)


# --- 부재 첨부 → 404 : R3.7 ----------------------------------------------------


def test_absent_attachment_serve_404():
    """존재하지 않는 첨부 id 는 어댑터 매핑 실패로 404(role 판정 이전)."""
    app, _ = _build_app(attachment_ws=None)  # db.get None = 첨부 부재
    _login_non_member(app)
    client = TestClient(app)

    resp = client.get("/attachments/999")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 보관 첨부 → 404 (서비스 단계 불변식 유지) : R3.4/8.10 ---------------------


def test_archived_attachment_still_404_after_gate_swap():
    """보관 첨부는 게이트 통과 후에도 서비스가 role 무관 404 로 차단한다(불변식 유지).

    읽기 게이트 전환(active_user_for_attachment)이 보관 차단을 게이트로 옮기지 않았음을
    확인한다: 게이트는 활성 비멤버를 통과시키지만 서비스가 여전히 404 를 낸다.
    """
    app, service_fake = _build_app(attachment_ws=42)
    _login_non_member(app)
    service_fake.serve_error = DomainError(
        code=ErrorCode.NOT_FOUND, message="첨부를 찾을 수 없습니다", http_status=404
    )
    client = TestClient(app)

    resp = client.get("/attachments/500")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    # 게이트를 통과해 서비스까지 도달했음(보관 차단은 서비스 소관).
    assert service_fake.calls[-1] == ("serve_attachment", 500)


# --- 미인증 → 401 : R3.6 -------------------------------------------------------


def test_unauthenticated_serve_401():
    """세션 없이 첨부를 조회하면 get_current_user 가 첨부 조회 이전에 401 을 낸다."""
    app, _ = _build_app()
    client = TestClient(app)  # 로그인 override 없음 → 실제 get_current_user

    resp = client.get("/attachments/500")

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 게이트 결선 계약: 서빙 라우트가 신규 게이트에 의존한다 ---------------------


def test_serve_route_depends_on_open_access_gate():
    """서빙(GET /attachments/{id})은 active_user_for_attachment 에 의존한다."""
    from app.attachment.dependencies import active_user_for_attachment

    serve_deps = {
        d.call for d in _route_dependencies("/attachments/{id}", "GET")
    }

    assert active_user_for_attachment in serve_deps


def _route_dependencies(path: str, method: str):
    """지정 라우트의 의존성(Depends) 목록을 돌려준다."""
    for route in attachment_router.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route, "methods", set()
        ):
            return route.dependant.dependencies
    raise AssertionError(f"route not found: {method} {path}")
