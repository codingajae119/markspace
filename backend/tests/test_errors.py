"""공통 에러 모델·코드 카탈로그·전역 예외 핸들러 단위 테스트 (Requirement 3.1~3.8).

각 예외 유형이 단일 ``ErrorResponse`` 형태(code/message/field_errors)로
직렬화됨을 관찰 가능하게 검증한다. 테스트마다 throwaway FastAPI 앱에
``register_error_handlers`` 를 등록하고 각 예외를 raise 하는 스텁 라우트를
두어 ``TestClient`` 로 응답을 단언한다.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.common.errors import (
    DomainError,
    ErrorCode,
    ErrorResponse,
    FieldError,
    register_error_handlers,
)


class _Payload(BaseModel):
    name: str
    count: int


def _build_app() -> FastAPI:
    """각 예외 유형을 raise 하는 스텁 라우트로 구성된 테스트 앱."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/not-found")
    def _not_found():
        raise DomainError(ErrorCode.NOT_FOUND, "gone", 404)

    @app.get("/conflict")
    def _conflict():
        raise DomainError(ErrorCode.CONFLICT, "lock held", 409)

    @app.post("/validate")
    def _validate(payload: _Payload):
        return {"ok": True}

    @app.get("/unauthenticated")
    def _unauthenticated():
        raise HTTPException(status_code=401, detail="no session")

    @app.get("/forbidden")
    def _forbidden():
        raise HTTPException(status_code=403, detail="not allowed")

    @app.get("/http-404")
    def _http_404():
        raise HTTPException(status_code=404, detail="missing")

    @app.get("/boom")
    def _boom():
        raise ValueError("secret db string")

    return app


@pytest.fixture
def client() -> TestClient:
    # 500 핸들러 응답을 관찰하려면 서버 예외 재전파를 꺼야 한다.
    return TestClient(_build_app(), raise_server_exceptions=False)


def test_domain_error_not_found_serializes(client):
    """DomainError(NOT_FOUND) → 404 + 단일 ErrorResponse 형태 (Req 3.5)."""
    resp = client.get("/not-found")
    assert resp.status_code == 404
    assert resp.json() == {
        "code": "not_found",
        "message": "gone",
        "field_errors": None,
    }


def test_request_validation_error_maps_to_422_with_field_errors(client):
    """요청 본문 검증 실패 → 422 + 비어있지 않은 field_errors (Req 3.2)."""
    resp = client.post("/validate", json={"count": "not-an-int"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == ErrorCode.VALIDATION_ERROR.value
    assert isinstance(body["field_errors"], list)
    assert len(body["field_errors"]) >= 1
    fields = {fe["field"] for fe in body["field_errors"]}
    # 누락된 name, 형변환 실패한 count 가 필드로 보고되어야 한다.
    assert "name" in fields
    assert "count" in fields
    # loc 선행 "body" 세그먼트는 필드 경로에서 제외된다.
    for fe in body["field_errors"]:
        assert not fe["field"].startswith("body")
        assert fe["message"]


def test_http_exception_401_maps_to_unauthenticated(client):
    """HTTPException(401) → 401 code=unauthenticated (Req 3.3)."""
    resp = client.get("/unauthenticated")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == "unauthenticated"
    assert body["message"] == "no session"
    assert body["field_errors"] is None


def test_http_exception_403_maps_to_forbidden(client):
    """HTTPException(403) → 403 code=forbidden (Req 3.4)."""
    resp = client.get("/forbidden")
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_http_exception_404_maps_to_not_found(client):
    """HTTPException(404) → 404 code=not_found (Req 3.5)."""
    resp = client.get("/http-404")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_domain_error_conflict_serializes(client):
    """DomainError(CONFLICT) → 409 code=conflict (Req 3.6)."""
    resp = client.get("/conflict")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "conflict"
    assert body["message"] == "lock held"


def test_unhandled_exception_maps_to_500_without_leak(client):
    """미처리 예외 → 500 code=internal, 내부 세부정보 미노출 (Req 3.7)."""
    resp = client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "internal"
    assert body["field_errors"] is None
    # 내부 예외 문자열/스택이 응답에 새어나오면 안 된다.
    assert "secret db string" not in resp.text
    assert "ValueError" not in resp.text
    assert "Traceback" not in resp.text


def test_error_code_catalog_has_all_members(client):
    """ErrorCode 에러 코드 카탈로그가 7개 멤버·정확한 문자열 값을 갖는다 (Req 3.1, 3.8)."""
    expected = {
        "UNAUTHENTICATED": "unauthenticated",
        "FORBIDDEN": "forbidden",
        "VALIDATION_ERROR": "validation_error",
        "NOT_FOUND": "not_found",
        "CONFLICT": "conflict",
        "UNPROCESSABLE": "unprocessable",
        "INTERNAL": "internal",
    }
    actual = {member.name: member.value for member in ErrorCode}
    assert actual == expected
    # str Enum 이어야 JSON 직렬화 계약이 성립한다.
    assert ErrorCode.NOT_FOUND == "not_found"


def test_error_response_and_field_error_schema():
    """단일 ErrorResponse 스키마 형태·기본값 (Req 3.1)."""
    er = ErrorResponse(code="internal", message="x")
    assert er.field_errors is None
    fe = FieldError(field="name", message="required")
    er2 = ErrorResponse(code="validation_error", message="bad", field_errors=[fe])
    dumped = er2.model_dump()
    assert dumped["field_errors"][0] == {"field": "name", "message": "required"}
