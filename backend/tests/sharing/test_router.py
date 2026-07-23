"""SharingRouter 결선 단위 테스트 (Task 3.1 / Req 2.1, 2.2, 2.3, 3.1, 3.6, 4.1,
6.1, 6.2, 6.3, 6.4, 7.2, 7.3).

design.md §Components → SharingRouter API Contract 표(카탈로그 행 34~37)와 게이트 결선을
검증한다. DB 없이 라우터 결선만 확인한다:

- 발급/토글(member 게이트): `get_share_link_service` 를 가짜로 override 하고 `get_current_user`·
  `get_db` 를 시나리오로 주입해 s07 `ws_role_for_document(MEMBER)` 게이트(문서 미존재→404,
  비멤버→403, 비인증→401, admin bypass)와 서비스 위임(issue_link·toggle_link)·응답
  (ShareLinkRead, share_url 포함)·게이트 off/비active 409 패스스루를 단위 검증한다.
- 공개 렌더/첨부 서빙(공개, 게이트 없음): `get_public_share_service` 를 가짜로 override 하고
  **세션 없이** 요청해도 서비스에 도달함을 확인해 공개 경로에 인증 의존성이 없음을 증명한다.
  유효 토큰 → 트리 200, 무효/미존재 토큰 → 서비스 404 통일, 링크 경유 첨부 → 바이너리 스트리밍,
  범위 밖/부재 → 404 를 검증한다.

핵심 불변식:
- 정확히 4개 엔드포인트가 등록된다(POST/PATCH /documents/{id}/share, GET /public/{token},
  GET /public/{token}/attachments/{aid}).
- 발급/토글은 MEMBER 게이트를 부착하고 공개 두 경로는 **인증 게이트가 없다**.
- 성공 계약: 발급/토글 200 + ShareLinkRead(share_url), 공개 렌더 200 + 트리, 파일 200 + 스트림.
- 발급/토글 거부: 비멤버 403, 비인증 401, 문서 미존재 404, 게이트 off/비active 409(서비스 패스스루).
- 공개 경로의 모든 무효/부재는 서비스가 404 로 통일(존재 추정 차단).
- 오류 본문은 s01 ErrorResponse(code/message) 형태.
"""

import io
from datetime import datetime
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.attachment.service import AttachmentBinary
from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers
from app.sharing.router import (
    get_public_share_service,
    get_share_link_service,
)
from app.sharing.router import router as sharing_router
from app.sharing.schemas import (
    PublicDocumentNode,
    PublicDocumentRead,
    ShareLinkRead,
    ShareLinkUpdate,
)

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_LINK_READ = ShareLinkRead(
    id=900,
    document_id=100,
    token="tok-abc",
    is_enabled=True,
    share_url="/public/tok-abc",
    created_at=_NOW,
)
_PUBLIC_TREE = PublicDocumentRead(
    root=PublicDocumentNode(
        id=100,
        title="공유 문서",
        content_html="<p>hello</p>",
        children=[
            PublicDocumentNode(
                id=101, title="자식", content_html="<p>child</p>", children=[]
            )
        ],
    )
)
_PNG_BYTES = b"\x89PNG\r\n\x1a\nDUMMYIMAGE"


class _FakeShareLinkService:
    """ShareLinkService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s14 계약). 호출을 기록하고 canned 응답을 반환한다.
    `issue_error`/`toggle_error` 를 설정하면 대응 메서드가 이를 raise 해 게이트 off/비active
    409 패스스루를 검증한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.issue_error: DomainError | None = None
        self.toggle_error: DomainError | None = None
        # 조회(get_link)는 읽기 전용이라 오류를 만들지 않는다(게이트가 401/403/404 산출).
        # 기본은 링크 존재; `get_result=None` 으로 "링크 없음"(200+null)을 검증한다.
        self.get_result: ShareLinkRead | None = _LINK_READ

    def issue_link(self, db, ctx, document_id) -> ShareLinkRead:
        self.calls.append(("issue_link", ctx.user_id, document_id))
        if self.issue_error is not None:
            raise self.issue_error
        return _LINK_READ

    def toggle_link(self, db, document_id, payload) -> ShareLinkRead:
        self.calls.append(("toggle_link", document_id, payload.is_enabled))
        if self.toggle_error is not None:
            raise self.toggle_error
        return _LINK_READ

    def get_link(self, db, document_id) -> ShareLinkRead | None:
        self.calls.append(("get_link", document_id))
        return self.get_result


class _FakePublicShareService:
    """PublicShareService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다. 호출을 기록하고 canned 응답을 반환한다.
    `render_error`/`serve_error` 를 설정하면 대응 메서드가 이를 raise 해 무효/부재 404
    통일을 검증한다. 공개 경로이므로 ctx 인자가 없다(인증 우회 증명).
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.render_error: DomainError | None = None
        self.serve_error: DomainError | None = None
        self.binary: AttachmentBinary | None = None

    def render_public_document(self, db, token) -> PublicDocumentRead:
        self.calls.append(("render_public_document", token))
        if self.render_error is not None:
            raise self.render_error
        return _PUBLIC_TREE

    def serve_public_attachment(self, db, token, attachment_id) -> AttachmentBinary:
        self.calls.append(("serve_public_attachment", token, attachment_id))
        if self.serve_error is not None:
            raise self.serve_error
        return self.binary or AttachmentBinary(
            stream=io.BytesIO(_PNG_BYTES),
            content_type="image/png",
            filename="pic.png",
        )


# --- 가짜 DB 세션: 문서→WS 어댑터(scalar)·resolver(query) 접근을 지원 -----------------


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
    """문서→WS 어댑터 매핑과 resolver 접근을 지원한다:

    - `db.scalar`(s07 `get_workspace_id`, 문서→ws 매핑) → workspace_id(또는 None: 문서 미존재).
    - `db.query(WorkspaceMember).filter(...).one_or_none()`(s01 resolver) → 멤버 role.
    """

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
    app.include_router(sharing_router)

    share_fake = _FakeShareLinkService()
    public_fake = _FakePublicShareService()
    app.dependency_overrides[get_share_link_service] = lambda: share_fake
    app.dependency_overrides[get_public_share_service] = lambda: public_fake
    # 기본: 문서는 workspace_id=42 에 존재(어댑터 매핑 성공).
    _set_db(app, workspace_id=42, role=None)
    return app, share_fake, public_fake


def _login(app: FastAPI, *, user_id: int = 7, is_admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=user_id, is_admin=is_admin
    )


def _set_db(app: FastAPI, *, workspace_id, role) -> None:
    """get_db 를 override — 어댑터엔 scalar(workspace_id), resolver 엔 role 멤버를 노출한다.
    `workspace_id=None` 이면 문서 미존재(어댑터 404)."""
    member = _FakeMember(role) if role is not None else None

    def _fake_db():
        yield _FakeSession(workspace_id=workspace_id, member=member)

    app.dependency_overrides[get_db] = _fake_db


# 발급/토글/조회 라우트(미인증 401 검증에 재사용) — 셋 다 동일 member 게이트.
_SHARE_ROUTES = [
    ("post", "/documents/100/share"),
    ("patch", "/documents/100/share"),
    ("get", "/documents/100/share"),
]


def _toggle(client, path="/documents/100/share", *, is_enabled=False):
    return client.patch(path, json={"is_enabled": is_enabled})


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_five_routes_registered():
    app, _, _ = _build_app()
    paths = app.openapi()["paths"]
    ops = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
    }
    assert ops == {
        ("/documents/{id}/share", "POST"),
        ("/documents/{id}/share", "PATCH"),
        ("/documents/{id}/share", "GET"),
        ("/public/{token}", "GET"),
        ("/public/{token}/attachments/{aid}", "GET"),
    }


# --- 발급(POST) 성공 계약(admin 인증으로 게이트 bypass) --------------------------


def test_issue_member_returns_200_share_link():
    app, share_fake, _ = _build_app()
    _login(app, user_id=7, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)

    resp = client.post("/documents/100/share")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == 900
    assert body["token"] == "tok-abc"
    assert body["is_enabled"] is True
    assert body["share_url"] == "/public/tok-abc"
    call = share_fake.calls[-1]
    assert call == ("issue_link", 7, 100)  # ctx.user_id·경로 문서 id 전달


def test_issue_admin_bypasses():
    app, share_fake, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)  # 비멤버여도 admin bypass(INV-3).
    client = TestClient(app)

    resp = client.post("/documents/100/share")

    assert resp.status_code == 200, resp.text
    assert share_fake.calls[-1][0] == "issue_link"


def test_issue_non_member_forbidden_403():
    """비멤버는 MEMBER 발급 게이트에서 403 (Req 4.6)."""
    app, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    resp = client.post("/documents/100/share")

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_issue_missing_document_returns_404():
    app, _, _ = _build_app()
    _login(app, user_id=99, is_admin=True)  # admin 이어도 어댑터가 문서 부재로 404.
    _set_db(app, workspace_id=None, role=None)  # scalar → None: 문서 미존재.
    client = TestClient(app)

    resp = client.post("/documents/100/share")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_issue_gate_off_service_409_passthrough():
    app, share_fake, _ = _build_app()
    _login(app, is_admin=True)
    share_fake.issue_error = DomainError(
        code=ErrorCode.CONFLICT, message="게이트 off", http_status=409
    )
    client = TestClient(app)

    resp = client.post("/documents/100/share")

    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "conflict"
    assert isinstance(body["message"], str) and body["message"]
    # 게이트 통과 후 서비스까지 도달했음(비active/게이트 off 판정은 서비스 소관).
    assert share_fake.calls[-1][0] == "issue_link"


# --- 토글(PATCH) 성공 계약 + 게이트 ---------------------------------------------


def test_toggle_member_returns_200_share_link():
    app, share_fake, _ = _build_app()
    _login(app, user_id=7, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)

    resp = _toggle(client, is_enabled=False)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == 900
    assert body["share_url"] == "/public/tok-abc"
    call = share_fake.calls[-1]
    assert call == ("toggle_link", 100, False)  # 경로 문서 id·payload 전달


def test_toggle_admin_bypasses():
    app, share_fake, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)  # 비멤버여도 admin bypass.
    client = TestClient(app)

    resp = _toggle(client, is_enabled=True)

    assert resp.status_code == 200, resp.text
    assert share_fake.calls[-1] == ("toggle_link", 100, True)


def test_toggle_non_member_forbidden_403():
    """비멤버는 MEMBER 토글 게이트에서 403 (Req 4.6)."""
    app, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    resp = _toggle(client)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_toggle_missing_document_returns_404():
    app, _, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=None, role=None)  # 문서 미존재.
    client = TestClient(app)

    resp = _toggle(client)

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_toggle_activation_blocked_service_409_passthrough():
    app, share_fake, _ = _build_app()
    _login(app, is_admin=True)
    share_fake.toggle_error = DomainError(
        code=ErrorCode.CONFLICT, message="활성화 불가", http_status=409
    )
    client = TestClient(app)

    resp = _toggle(client, is_enabled=True)

    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"
    assert share_fake.calls[-1][0] == "toggle_link"


# --- 조회(GET) 성공 계약 + 게이트 (발급·전환과 동일 게이트 재사용) -----------------


def test_get_member_returns_200_share_link():
    """member 는 조회 게이트를 통과하고 링크가 있으면 200 + ShareLinkRead (Req 1.1)."""
    app, share_fake, _ = _build_app()
    _login(app, user_id=7, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    client = TestClient(app)

    resp = client.get("/documents/100/share")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == 900
    assert body["token"] == "tok-abc"
    assert body["is_enabled"] is True
    assert body["share_url"] == "/public/tok-abc"
    assert share_fake.calls[-1] == ("get_link", 100)  # 경로 문서 id 전달


def test_get_member_no_link_returns_200_null():
    """링크가 없으면 오류가 아니라 200 + 본문 null (Req 1.2, 발급/토글과 균질)."""
    app, share_fake, _ = _build_app()
    _login(app, user_id=7, is_admin=False)
    _set_db(app, workspace_id=42, role="member")
    share_fake.get_result = None  # 링크 없음
    client = TestClient(app)

    resp = client.get("/documents/100/share")

    assert resp.status_code == 200, resp.text
    assert resp.json() is None  # 본문 null(204 아님)
    assert share_fake.calls[-1] == ("get_link", 100)


def test_get_admin_bypasses():
    """비멤버 admin 은 조회 게이트를 bypass 한다 (Req 1.7, INV-3, 발급/토글과 동일)."""
    app, share_fake, _ = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)  # 비멤버여도 admin bypass.
    client = TestClient(app)

    resp = client.get("/documents/100/share")

    assert resp.status_code == 200, resp.text
    assert share_fake.calls[-1] == ("get_link", 100)


def test_get_non_member_forbidden_403():
    """비멤버·비admin 은 조회 게이트에서 403 (Req 1.6, 발급/토글과 동일)."""
    app, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    resp = client.get("/documents/100/share")

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_get_missing_document_returns_404():
    """문서 부재는 게이트 어댑터가 판정 전에 404 (Req 1.4, 발급/토글과 동일)."""
    app, _, _ = _build_app()
    _login(app, user_id=99, is_admin=True)  # admin 이어도 어댑터가 문서 부재로 404.
    _set_db(app, workspace_id=None, role=None)  # scalar → None: 문서 미존재.
    client = TestClient(app)

    resp = client.get("/documents/100/share")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --- 발급/토글/조회 미인증(세션 없음) → 401 --------------------------------------


@pytest.mark.parametrize("method,path", _SHARE_ROUTES)
def test_share_routes_unauthenticated_401(method, path):
    # get_current_user 를 override 하지 않는다: 세션 쿠키 없이 요청하면 s01
    # get_current_user 가 db 접근 전에 401 을 낸다.
    app, _, _ = _build_app()
    client = TestClient(app)

    if method == "post":
        resp = client.post(path)
    elif method == "patch":
        resp = _toggle(client, path=path)
    else:
        resp = client.get(path)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 공개 렌더(GET /public/{token}) — 인증 게이트 없음 ---------------------------


def test_public_render_returns_200_tree_without_auth():
    app, _, public_fake = _build_app()
    # 로그인하지 않는다(세션 없음): 공개 경로는 인증 의존성이 없어 서비스에 도달한다.
    client = TestClient(app)

    resp = client.get("/public/tok-abc")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["root"]["id"] == 100
    assert body["root"]["title"] == "공유 문서"
    assert body["root"]["content_html"] == "<p>hello</p>"
    assert body["root"]["children"][0]["id"] == 101
    assert public_fake.calls[-1] == ("render_public_document", "tok-abc")


def test_public_render_forwards_path_token():
    app, _, public_fake = _build_app()
    client = TestClient(app)

    resp = client.get("/public/some-other-token")

    assert resp.status_code == 200
    assert public_fake.calls[-1] == ("render_public_document", "some-other-token")


def test_public_render_unknown_token_404_unified():
    app, _, public_fake = _build_app()
    public_fake.render_error = DomainError(
        code=ErrorCode.NOT_FOUND, message="공유 링크를 찾을 수 없습니다", http_status=404
    )
    client = TestClient(app)

    resp = client.get("/public/nope")

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "not_found"
    assert isinstance(body["message"], str) and body["message"]
    assert public_fake.calls[-1][0] == "render_public_document"


# --- 링크 경유 첨부 서빙(GET /public/{token}/attachments/{aid}) — 인증 게이트 없음 --


def test_public_attachment_streams_binary_without_auth():
    app, _, public_fake = _build_app()
    public_fake.binary = AttachmentBinary(
        stream=io.BytesIO(_PNG_BYTES),
        content_type="image/png",
        filename="pic.png",
    )
    client = TestClient(app)

    resp = client.get("/public/tok-abc/attachments/500")

    assert resp.status_code == 200
    assert resp.content == _PNG_BYTES  # 정확한 바이트 스트리밍
    assert resp.headers["content-type"].startswith("image/png")
    assert public_fake.calls[-1] == ("serve_public_attachment", "tok-abc", 500)


def test_public_attachment_non_ascii_filename_does_not_500():
    """비-ASCII(한글) 원본명 첨부의 링크 경유 서빙이 500 이 아니라 200 이어야 한다(회귀).

    과거 이 라우터가 `Content-Disposition: inline; filename="<원본명>"` 을 개별 복제해, 게스트
    뷰가 `집.png` 같은 한글 원본명 첨부를 로드하면 Starlette 의 latin-1 헤더 인코딩에서
    `UnicodeEncodeError` 로 500 이 나 이미지가 깨졌다(s12 인증 서빙은 이미 RFC 5987 로 안전
    인코딩했으나 이 공개 경로만 divergence). 이제 공용 `content_disposition_inline` 을 재사용해
    `filename*=UTF-8''` 로 안전하게 직렬화한다.
    """
    korean_name = "집.png"
    app, _, public_fake = _build_app()
    public_fake.binary = AttachmentBinary(
        stream=io.BytesIO(_PNG_BYTES),
        content_type="image/png",
        filename=korean_name,
    )
    client = TestClient(app)

    resp = client.get("/public/tok-abc/attachments/11")

    # 핵심 회귀: 한글 파일명이어도 헤더 인코딩에서 500 이 나지 않는다.
    assert resp.status_code == 200, resp.text
    assert resp.content == _PNG_BYTES
    # RFC 5987 로 UTF-8 percent-encoding 된 파일명 파라미터를 포함한다(ASCII 폴백도 공존).
    disposition = resp.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert quote(korean_name, safe="") in disposition


def test_public_attachment_forwards_path_params():
    app, _, public_fake = _build_app()
    client = TestClient(app)

    resp = client.get("/public/xyz/attachments/777")

    assert resp.status_code == 200
    assert public_fake.calls[-1] == ("serve_public_attachment", "xyz", 777)


def test_public_attachment_out_of_scope_404_unified():
    app, _, public_fake = _build_app()
    public_fake.serve_error = DomainError(
        code=ErrorCode.NOT_FOUND, message="공유 링크를 찾을 수 없습니다", http_status=404
    )
    client = TestClient(app)

    resp = client.get("/public/tok-abc/attachments/500")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    assert public_fake.calls[-1][0] == "serve_public_attachment"


# --- 오류 본문: s01 ErrorResponse 형태(Req 7.2) ---------------------------------


def test_error_body_is_s01_error_response_shape():
    app, _, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None)
    client = TestClient(app)

    # 비멤버는 발급(MEMBER) 게이트에서 403.
    resp = client.post("/documents/100/share")

    assert resp.status_code == 403
    body = resp.json()
    assert set(("code", "message")).issubset(body.keys())
    assert body["code"] == "forbidden"
    assert isinstance(body["message"], str) and body["message"]
