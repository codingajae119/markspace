"""공통 에러 응답 모델·코드 카탈로그·전역 예외 핸들러 (Requirement 3.1~3.8).

전 엔드포인트가 동일한 :class:`ErrorResponse` 형태로 오류를 직렬화하도록
단일 변환 지점을 제공한다. :func:`register_error_handlers` 를 ``create_app()``
에서 호출하면 아래 4종 예외가 공통 응답으로 변환된다.

- :class:`DomainError` — 하위 spec 이 raise 하는 도메인 예외 → 자신의 ``http_status``.
- ``RequestValidationError`` — 요청 검증 실패 → 422 + field_errors.
- ``HTTPException`` (Starlette/FastAPI) — status_code → 표준 ErrorCode 매핑.
- 미처리 ``Exception`` — 500, 내부 세부정보 미노출(서버 로그로만 기록).

의존 방향: 이 모듈은 fastapi/starlette/pydantic 만 import 하며 feature 도메인·
db·model·auth 를 import 하지 않는다.
"""

from __future__ import annotations

import logging
from enum import Enum

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class FieldError(BaseModel):
    """필드 단위 검증 오류 항목."""

    field: str
    message: str


class ErrorResponse(BaseModel):
    """전 엔드포인트 공통 단일 에러 응답 스키마 (Req 3.1)."""

    code: str  # ErrorCode 값
    message: str  # 사람이 읽을 메시지
    field_errors: list[FieldError] | None = None


class ErrorCode(str, Enum):
    """안정적인 에러 코드 카탈로그 (Req 3.8).

    문자열 값은 클라이언트·통합 테스트가 의존하는 계약이므로 변경 금지.
    """

    UNAUTHENTICATED = "unauthenticated"  # 401
    FORBIDDEN = "forbidden"  # 403
    VALIDATION_ERROR = "validation_error"  # 422 (요청 검증 실패)
    NOT_FOUND = "not_found"  # 404
    CONFLICT = "conflict"  # 409 (상태/불변식 충돌)
    UNPROCESSABLE = "unprocessable"  # 422 (도메인 규칙 위반)
    INTERNAL = "internal"  # 500


class DomainError(Exception):
    """하위 spec 이 raise 하는 도메인 예외의 기반 클래스.

    전역 핸들러가 ``http_status`` 와 ``code`` 를 그대로 사용해 공통 응답으로
    변환하므로, feature 는 이 예외(또는 하위 클래스)를 raise 하기만 하면 된다.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int,
        field_errors: list[FieldError] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.field_errors = field_errors


# HTTP status_code → 표준 ErrorCode 매핑(카탈로그). 미정의 status 는 status 값을
# 코드 문자열로 그대로 사용한다.
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    500: ErrorCode.INTERNAL,
}


def _error_json(status_code: int, response: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _loc_to_field(loc: tuple[object, ...]) -> str:
    """pydantic 오류 loc 경로를 필드 이름으로 변환.

    선행 "body"/"query"/"path"/"header"/"cookie" 세그먼트는 위치 표시일 뿐이므로
    제외하고, 남은 경로를 점(.)으로 잇는다. 남는 세그먼트가 없으면 위치명을 쓴다.
    """
    parts = list(loc)
    if parts and parts[0] in ("body", "query", "path", "header", "cookie"):
        location = parts[0]
        parts = parts[1:]
        if not parts:
            return str(location)
    return ".".join(str(p) for p in parts)


def register_error_handlers(app: FastAPI) -> None:
    """전역 예외 핸들러를 앱에 등록한다 (Req 3.2~3.7)."""

    @app.exception_handler(DomainError)
    async def _handle_domain_error(request, exc: DomainError) -> JSONResponse:
        return _error_json(
            exc.http_status,
            ErrorResponse(
                code=exc.code.value,
                message=exc.message,
                field_errors=exc.field_errors,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors = [
            FieldError(field=_loc_to_field(err.get("loc", ())), message=err.get("msg", ""))
            for err in exc.errors()
        ]
        return _error_json(
            422,
            ErrorResponse(
                code=ErrorCode.VALIDATION_ERROR.value,
                message="Request validation failed",
                field_errors=field_errors,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code)
        code_value = code.value if code is not None else str(exc.status_code)
        detail = exc.detail
        message = detail if isinstance(detail, str) else str(detail)
        return _error_json(
            exc.status_code,
            ErrorResponse(code=code_value, message=message),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request, exc: Exception) -> JSONResponse:
        # 스택·예외 문자열은 서버 로그로만 기록하고 응답에는 노출하지 않는다(Req 3.7).
        logger.exception("Unhandled exception during request processing")
        return _error_json(
            500,
            ErrorResponse(
                code=ErrorCode.INTERNAL.value,
                message="Internal Server Error",
            ),
        )


# FastAPI 의 HTTPException 은 Starlette HTTPException 의 하위 클래스이므로
# StarletteHTTPException 핸들러가 둘 다 처리한다. 명시적 재노출(사용 편의).
__all__ = [
    "DomainError",
    "ErrorCode",
    "ErrorResponse",
    "FieldError",
    "HTTPException",
    "register_error_handlers",
]
