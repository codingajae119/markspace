/**
 * 공통 에러 표시 유틸 (design.md "shared / ui → UiPrimitives", 계약 `ErrorMessage`).
 *
 * 정규화된 {@link ApiError} 의 `message` 와 `fieldErrors`(백엔드 `field_errors` 미러링)만
 * 사용자에게 표시한다. 내부 세부정보(status·raw·스택 등)는 노출하지 않는다 — 백엔드가 이미
 * 500 내부를 감춘 안정적 계약을 제공하므로, 여기서는 ApiError 가 실은 값만 그대로 보여준다.
 *
 * - `error` 가 `null` 이면 `null` 을 반환하여 아무것도 렌더하지 않는다.
 * - `fieldErrors` 가 비어 있지 않으면 `field: message` 목록으로 표시하고, 각 항목은 `field`
 *   이름을 안정적 key 로 사용한다(AC 7.4).
 *
 * Requirements: 7.4(message·field_errors 표시), 7.5(Tailwind 4).
 */

import type { ReactElement } from "react";

import type { ApiError } from "@/shared/api/errors";

export interface ErrorMessageProps {
  /** 표시할 정규화된 API 오류. `null` 이면 렌더하지 않는다. */
  error: ApiError | null;
}

/** `error` 의 message 와(있으면) field_errors 목록을 표시. `null` → 렌더 없음. */
export function ErrorMessage({ error }: ErrorMessageProps): ReactElement | null {
  if (error === null) {
    return null;
  }

  const hasFieldErrors = error.fieldErrors.length > 0;

  return (
    <div
      role="alert"
      className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      <p className="font-medium">{error.message}</p>
      {hasFieldErrors ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {error.fieldErrors.map((fieldError) => (
            <li key={fieldError.field}>
              <span className="font-medium">{fieldError.field}</span>
              {": "}
              {fieldError.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
