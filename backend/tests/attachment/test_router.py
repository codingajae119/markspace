"""AttachmentRouter 결선 단위 테스트 (Task 3.1 / Req 1.1, 1.5, 2.1, 2.3, 2.4, 3.3,
3.4, 3.5, 3.6, 6.2, 6.3, 7.2, 7.3).

design.md §Components → AttachmentRouter API Contract 표(카탈로그 행 32~33)와 두 System
Flows(첨부 생성 / 첨부 조회 서빙)의 게이트 결선을 검증한다. DB 없이 라우터 결선만 확인한다:

- 결선/스키마/위임: `get_attachment_service` 를 가짜로 override 하고 `get_current_user` 를
  인증 컨텍스트로 주입해 2개 엔드포인트의 경로·메서드·상태코드·응답(스키마/바이너리)·서비스
  위임과 **content-type 기반 kind 추론**(image/* → image, 그 외 → file, 명시 Form 우선)을
  단위 검증한다.
- 실제 게이트 동작(401/403/404/admin-bypass): `get_current_user` 로 인증 컨텍스트를 주입하고
  `get_db` 를 가짜 세션으로 교체해 두 게이트 계열을 재현한다:
    * `POST /documents/{id}/attachments` → s07 `ws_role_for_document`(문서 id → workspace_id
      매핑; `db.scalar`) 후 s01 위임(`db.query`).
    * `GET /attachments/{id}` → s12 `ws_role_for_attachment`(첨부 id → workspace_id 매핑;
      `db.get`) 후 s01 위임(`db.query`).

핵심 불변식:
- 정확히 2개 엔드포인트가 등록된다(POST /documents/{id}/attachments, GET /attachments/{id}).
- 업로드는 EDITOR, 조회는 VIEWER 게이트를 부착한다.
- 성공 계약: 업로드 201 + AttachmentRead(url=/attachments/{id}), 조회 200 + 바이너리 스트림.
- kind 추론: image/* content-type → image, 그 외 → file; 명시 Form kind 가 추론을 이긴다.
- 보관 첨부 조회 → 서비스가 role 무관 404(admin 포함), 크기 초과 → 서비스 422 패스스루.
- 대상 문서 미존재(업로드)·첨부 미존재(조회) → 어댑터 404. 비인증 → 401, 부적격 role → 403.
- 오류 본문은 s01 ErrorResponse(code/message) 형태.
"""

import io
from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.attachment.router import get_attachment_service
from app.attachment.router import router as attachment_router
from app.attachment.schemas import AttachmentKind, AttachmentRead
from app.attachment.service import AttachmentBinary
from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode, register_error_handlers

_NOW = datetime(2026, 1, 1, 0, 0, 0)
_ATT_READ = AttachmentRead(
    id=500,
    workspace_id=42,
    document_id=100,
    kind=AttachmentKind.IMAGE,
    original_name="pic.png",
    is_archived=False,
    created_at=_NOW,
    url="/attachments/500",
)
_PNG_BYTES = b"\x89PNG\r\n\x1a\nDUMMYIMAGE"


class _FakeAttachmentService:
    """AttachmentService 인터페이스를 흉내내는 최소 가짜(스텁).

    서비스 메서드는 db 를 첫 인자로 받는다(s12 계약). 호출을 기록하고 canned 응답을 반환한다.
    `upload_error`/`serve_error` 를 설정하면 대응 메서드가 이를 raise 해 서비스 오류
    패스스루(크기 초과 422·보관 404)를 검증한다. `binary` 로 서빙 바이너리를 주입한다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.upload_error: DomainError | None = None
        self.serve_error: DomainError | None = None
        self.binary: AttachmentBinary | None = None

    def upload_attachment(
        self, db, ctx, document_id, *, kind, upload_filename, stream, size
    ) -> AttachmentRead:
        self.calls.append(
            ("upload_attachment", ctx.user_id, document_id, kind, upload_filename, size)
        )
        if self.upload_error is not None:
            raise self.upload_error
        return _ATT_READ

    def serve_attachment(self, db, attachment_id) -> AttachmentBinary:
        self.calls.append(("serve_attachment", attachment_id))
        if self.serve_error is not None:
            raise self.serve_error
        return self.binary or AttachmentBinary(
            stream=io.BytesIO(_PNG_BYTES),
            content_type="image/png",
            filename="pic.png",
        )


# --- 가짜 DB 세션: 두 어댑터(scalar/get)·resolver(query) 접근을 지원 -----------------


class _FakeMember:
    def __init__(self, role: str) -> None:
        self.role = role


class _FakeAttachment:
    """`ws_role_for_attachment` 어댑터가 workspace_id 확정에만 쓰는 자리끼."""

    def __init__(self, workspace_id: int) -> None:
        self.workspace_id = workspace_id


class _FakeQuery:
    def __init__(self, member) -> None:
        self._member = member

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def one_or_none(self):
        return self._member


class _FakeSession:
    """어댑터의 두 매핑 접근과 resolver 접근을 지원한다:

    - `db.scalar`(s07 `get_workspace_id`, 업로드 문서→ws 매핑) → workspace_id(또는 None).
    - `db.get`(s12 `AttachmentRepository.get`, 조회 첨부→ws 매핑) → 첨부(또는 None).
    - `db.query(WorkspaceMember).filter(...).one_or_none()`(s01 resolver) → 멤버 role.
    """

    def __init__(self, *, workspace_id, member, attachment) -> None:
        self._workspace_id = workspace_id
        self._member = member
        self._attachment = attachment

    def scalar(self, *args, **kwargs):
        return self._workspace_id

    def get(self, model, ident):
        return self._attachment

    def query(self, model) -> _FakeQuery:
        return _FakeQuery(self._member)


def _build_app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test", session_cookie="sid")
    register_error_handlers(app)
    app.include_router(attachment_router)

    service_fake = _FakeAttachmentService()
    app.dependency_overrides[get_attachment_service] = lambda: service_fake
    # 기본: 문서/첨부 모두 workspace_id=42 에 존재(어댑터 매핑 성공).
    _set_db(app, workspace_id=42, role=None, attachment_ws=42)
    return app, service_fake


def _login(app: FastAPI, *, user_id: int = 7, is_admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=user_id, is_admin=is_admin
    )


def _set_db(app: FastAPI, *, workspace_id, role, attachment_ws=42) -> None:
    """get_db 를 override — 업로드 어댑터엔 scalar(workspace_id), 조회 어댑터엔 get(첨부),
    resolver 엔 role 멤버를 노출한다. `attachment_ws=None` 이면 첨부 미존재(조회 404)."""
    member = _FakeMember(role) if role is not None else None
    attachment = _FakeAttachment(attachment_ws) if attachment_ws is not None else None

    def _fake_db():
        yield _FakeSession(
            workspace_id=workspace_id, member=member, attachment=attachment
        )

    app.dependency_overrides[get_db] = _fake_db


# 각 라우트를 (method, path, kind) 로 나열(미인증 401 검증에 재사용).
_ROUTES = [
    ("post", "/documents/100/attachments"),
    ("get", "/attachments/500"),
]


def _upload(client, path="/documents/100/attachments", *, filename="pic.png",
            data=_PNG_BYTES, content_type="image/png", kind=None):
    files = {"file": (filename, data, content_type)}
    form = {"kind": kind} if kind is not None else None
    return client.post(path, files=files, data=form)


# --- 엔드포인트 등록/경로 --------------------------------------------------------


def test_exactly_two_routes_registered():
    app, _ = _build_app()
    paths = app.openapi()["paths"]
    ops = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
    }
    assert ops == {
        ("/documents/{id}/attachments", "POST"),
        ("/attachments/{id}", "GET"),
    }


# --- 업로드 성공 계약(admin 인증으로 게이트 bypass) + kind 추론 -------------------


def test_upload_image_returns_201_infers_image_kind():
    app, service_fake = _build_app()
    _login(app, user_id=7, is_admin=True)
    client = TestClient(app)

    resp = _upload(client, filename="pic.png", content_type="image/png")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == 500
    assert body["url"] == "/attachments/500"
    call = service_fake.calls[-1]
    assert call[0] == "upload_attachment"
    assert call[1] == 7  # ctx.user_id 전달
    assert call[2] == 100  # 경로 문서 id
    assert call[3] == AttachmentKind.IMAGE  # image/* → image 추론
    assert call[4] == "pic.png"  # 원본 파일명
    assert call[5] == len(_PNG_BYTES)  # 크기 산정


def test_upload_non_image_infers_file_kind():
    app, service_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = _upload(
        client, filename="doc.pdf", data=b"%PDF-1.4 data",
        content_type="application/pdf",
    )

    assert resp.status_code == 201, resp.text
    assert service_fake.calls[-1][3] == AttachmentKind.FILE  # 비-image → file 추론


def test_upload_explicit_kind_form_overrides_inference():
    app, service_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    # content-type 은 image/* 이지만 명시 kind=file 가 추론을 이긴다.
    resp = _upload(client, filename="pic.png", content_type="image/png", kind="file")

    assert resp.status_code == 201, resp.text
    assert service_fake.calls[-1][3] == AttachmentKind.FILE


def test_upload_returns_attachment_read_shape():
    app, _ = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = _upload(client)

    assert resp.status_code == 201
    body = resp.json()
    # AttachmentRead 규약 필드가 모두 직렬화된다(Req 7.1·7.2).
    for key in (
        "id", "workspace_id", "document_id", "kind", "original_name",
        "is_archived", "created_at", "url",
    ):
        assert key in body
    assert body["kind"] == "image"


# --- 업로드 게이트: EDITOR ------------------------------------------------------


def test_upload_editor_passes():
    app, service_fake = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="editor")
    client = TestClient(app)

    resp = _upload(client)

    assert resp.status_code == 201, resp.text
    assert service_fake.calls[-1][0] == "upload_attachment"


@pytest.mark.parametrize("role", ["viewer", None])
def test_upload_below_editor_forbidden_403(role):
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=role)
    client = TestClient(app)

    resp = _upload(client)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_upload_admin_bypasses():
    app, service_fake = _build_app()
    _login(app, user_id=99, is_admin=True)
    _set_db(app, workspace_id=42, role=None)  # 비멤버여도 admin bypass(INV-3).
    client = TestClient(app)

    resp = _upload(client)

    assert resp.status_code == 201
    assert service_fake.calls[-1][0] == "upload_attachment"


def test_upload_missing_document_returns_404():
    app, _ = _build_app()
    _login(app, user_id=99, is_admin=True)  # admin 이어도 어댑터가 문서 부재로 404.
    _set_db(app, workspace_id=None, role=None)  # scalar → None: 문서 미존재.
    client = TestClient(app)

    resp = _upload(client)

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_upload_oversize_service_422_passthrough():
    app, service_fake = _build_app()
    _login(app, is_admin=True)
    service_fake.upload_error = DomainError(
        code=ErrorCode.UNPROCESSABLE, message="크기 초과", http_status=422
    )
    client = TestClient(app)

    resp = _upload(client)

    assert resp.status_code == 422
    assert resp.json()["code"] == "unprocessable"
    # 서비스까지 도달했음(게이트 통과 후 서비스가 거부).
    assert service_fake.calls[-1][0] == "upload_attachment"


# --- 조회 성공 계약: 바이너리 스트리밍 ------------------------------------------


def test_serve_returns_200_binary_stream():
    app, service_fake = _build_app()
    _login(app, is_admin=True)
    service_fake.binary = AttachmentBinary(
        stream=io.BytesIO(_PNG_BYTES),
        content_type="image/png",
        filename="pic.png",
    )
    client = TestClient(app)

    resp = client.get("/attachments/500")

    assert resp.status_code == 200
    assert resp.content == _PNG_BYTES  # 정확한 바이트 스트리밍
    assert resp.headers["content-type"].startswith("image/png")
    assert service_fake.calls[-1] == ("serve_attachment", 500)


def test_serve_forwards_path_attachment_id():
    app, service_fake = _build_app()
    _login(app, is_admin=True)
    client = TestClient(app)

    resp = client.get("/attachments/777")

    assert resp.status_code == 200
    assert service_fake.calls[-1] == ("serve_attachment", 777)


# --- 조회 게이트: VIEWER --------------------------------------------------------


def test_serve_viewer_passes():
    app, service_fake = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="viewer", attachment_ws=42)
    client = TestClient(app)

    resp = client.get("/attachments/500")

    assert resp.status_code == 200
    assert service_fake.calls[-1][0] == "serve_attachment"


def test_serve_non_member_forbidden_403():
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role=None, attachment_ws=42)
    client = TestClient(app)

    resp = client.get("/attachments/500")

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_serve_missing_attachment_returns_404():
    app, _ = _build_app()
    _login(app, user_id=99, is_admin=True)  # admin 이어도 어댑터가 첨부 부재로 404.
    _set_db(app, workspace_id=42, role=None, attachment_ws=None)  # 첨부 미존재.
    client = TestClient(app)

    resp = client.get("/attachments/500")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_serve_archived_returns_404_even_for_admin():
    """보관 첨부는 서비스가 role 무관 404(admin 포함)로 처리한다(Req 6.2·6.3, 8.10)."""
    app, service_fake = _build_app()
    _login(app, user_id=99, is_admin=True)  # 게이트는 admin bypass 로 통과.
    service_fake.serve_error = DomainError(
        code=ErrorCode.NOT_FOUND, message="첨부를 찾을 수 없습니다", http_status=404
    )
    client = TestClient(app)

    resp = client.get("/attachments/500")

    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    # 게이트를 통과해 서비스까지 도달했음(role 무관 차단은 서비스 소관).
    assert service_fake.calls[-1] == ("serve_attachment", 500)


# --- 미인증(세션 없음) → 401 ----------------------------------------------------


@pytest.mark.parametrize("method,path", _ROUTES)
def test_unauthenticated_401(method, path):
    # get_current_user 를 override 하지 않는다: 세션 쿠키 없이 요청하면 s01
    # get_current_user 가 db 접근 전에 401 을 낸다.
    app, _ = _build_app()
    client = TestClient(app)

    if method == "post":
        resp = _upload(client, path=path)
    else:
        resp = client.get(path)

    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --- 오류 본문: s01 ErrorResponse 형태(Req 7.2) ---------------------------------


def test_error_body_is_s01_error_response_shape():
    app, _ = _build_app()
    _login(app, user_id=3, is_admin=False)
    _set_db(app, workspace_id=42, role="viewer", attachment_ws=42)
    client = TestClient(app)

    # viewer 는 업로드(EDITOR) 게이트에서 403.
    resp = _upload(client)

    assert resp.status_code == 403
    body = resp.json()
    assert set(("code", "message")).issubset(body.keys())
    assert body["code"] == "forbidden"
    assert isinstance(body["message"], str) and body["message"]
