/**
 * 백엔드 공통 에러 계약(`app/common/errors.py`)의 프론트 미러링.
 *
 * 백엔드는 전 엔드포인트를 단일 `ErrorResponse`(code·message·field_errors) 형태로
 * 직렬화한다. 이 모듈은 그 계약을 프론트 타입으로 미러링하고, 임의의 응답 본문을
 * 안정적인 {@link ApiError} 로 정규화한다. 새 코드/필드를 발명하지 않는다(s01 계약 소비).
 *
 * Requirements: 3.3(정형 ErrorResponse→ApiError 매핑), 3.4(비정형→internal 기본 정규화,
 * 내부 세부정보 미노출).
 */

/**
 * 안정적인 에러 코드 카탈로그. 백엔드 `ErrorCode`(errors.py) 문자열 값과 1:1 미러링.
 * 백엔드가 카탈로그를 확장할 수 있으므로 소비 계약은 `ErrorCode | string` 을 허용한다.
 */
export type ErrorCode =
  | "unauthenticated"
  | "forbidden"
  | "validation_error"
  | "not_found"
  | "conflict"
  | "unprocessable"
  | "internal";

/** 필드 단위 검증 오류 항목. 백엔드 `FieldError` 미러링. */
export interface FieldError {
  field: string;
  message: string;
}

/** 전 엔드포인트 공통 단일 에러 응답 스키마. 백엔드 `ErrorResponse` 미러링. */
export interface ErrorResponse {
  code: ErrorCode | string;
  message: string;
  field_errors?: FieldError[] | null;
}

/** 비정형/파싱 불가 본문에 사용하는 안정적 기본 코드·메시지(내부 세부정보 미노출, AC 3.4). */
const INTERNAL_CODE = "internal" as const;
const GENERIC_INTERNAL_MESSAGE = "예기치 못한 오류가 발생했습니다.";

/**
 * 호출부가 단일 에러 계약으로 처리하는 정규화된 API 오류.
 *
 * `fieldErrors` 는 항상 배열이다(null/undefined → `[]`). `raw` 는 정형 응답을
 * 파싱한 경우에만 보존되며, 비정형 본문에서는 undefined 로 남긴다.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | string;
  readonly fieldErrors: FieldError[];
  readonly raw?: ErrorResponse;

  constructor(params: {
    status: number;
    code: ErrorCode | string;
    message: string;
    fieldErrors?: FieldError[];
    raw?: ErrorResponse;
  }) {
    super(params.message);
    this.name = "ApiError";
    this.status = params.status;
    this.code = params.code;
    this.fieldErrors = params.fieldErrors ?? [];
    this.raw = params.raw;
    // extends Error 상속 체인 복원(ES target/트랜스파일 환경 대비).
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFieldError(value: unknown): value is FieldError {
  return (
    isRecord(value) &&
    typeof value.field === "string" &&
    typeof value.message === "string"
  );
}

/** `field_errors` 를 안전하게 `FieldError[]` 로 정규화(정형 항목만 유지, 그 외 폐기). */
function normalizeFieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(isFieldError);
}

/**
 * 임의의 응답 본문을 {@link ApiError} 로 정규화한다.
 *
 * - 본문이 정형 `ErrorResponse`(객체이며 `code`·`message` 가 모두 문자열)이면
 *   code/message/field_errors 를 보존해 매핑한다(AC 3.3).
 * - 그 외(비객체·null·필수 필드 누락·타입 불일치·파싱 불가)는 내부 세부정보를
 *   노출하지 않는 안정적 `internal` 기본으로 정규화한다(AC 3.4).
 */
export function parseErrorResponse(status: number, body: unknown): ApiError {
  if (isRecord(body) && typeof body.code === "string" && typeof body.message === "string") {
    const raw: ErrorResponse = {
      code: body.code,
      message: body.message,
      field_errors: normalizeFieldErrors(body.field_errors),
    };
    return new ApiError({
      status,
      code: raw.code,
      message: raw.message,
      fieldErrors: raw.field_errors ?? [],
      raw,
    });
  }

  return new ApiError({
    status,
    code: INTERNAL_CODE,
    message: GENERIC_INTERNAL_MESSAGE,
  });
}
