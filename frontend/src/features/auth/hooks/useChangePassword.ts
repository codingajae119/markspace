/**
 * 본인 비밀번호 변경 useCase 훅 (design.md "features/auth/hooks → useChangePassword").
 *
 * 현재/새 비밀번호 제출 → `authApi.changePassword()` 호출. 성공(204) 시 `succeeded=true`,
 * 실패(422) 시 `ApiError` 를 상태로 보관해 폼이 `ErrorMessage` 로 표시하게 한다. 실패 유형
 * (현재 비밀번호 불일치 `unprocessable` vs 새 비밀번호 정책 위반 `validation_error`)을 프론트에서
 * 분기하지 않고 `ApiError` 를 그대로 표면화한다(component 가 `ErrorMessage` 에 위임). 대상은 항상
 * 현재 세션 사용자이며(타인 지정 인자 없음), 세션·라우팅은 접촉하지 않는다.
 *
 * 계약 경계(모두 s16 소비, 재구현 금지):
 * - `/auth/password` 호출·에러 정규화는 authApi(→ s16 apiClient)가 소유하며 여기서 재구현하지 않는다.
 * - 오류 표시 계약은 s16 `ApiError`/`ErrorMessage` 단일 계약을 재사용한다(사유별 메시지 발명 금지).
 *
 * Requirements:
 * - 4.2 제출 시 `POST /auth/password`(본문 `current_password`·`new_password`) 호출
 * - 4.3 성공(204) 시 성공 상태 표시 / 4.4 422 `unprocessable`(현재 비밀번호 불일치) 표면화
 * - 4.5 422 `validation_error`(새 비밀번호 정책 위반, `field_errors`) 표면화
 * - 4.6 정책 최종 강제는 백엔드 계약(422)이 소유(프론트 검증은 보안 경계 아님)
 */

import { useCallback, useState } from "react";

import { authApi } from "../api/authApi";
import type { PasswordChangeRequest } from "../api/authApi";
import { ApiError } from "@/shared/api/errors";

/** useChangePassword 가 노출하는 제출 액션·진행 상태·성공/오류 상태. */
export interface UseChangePasswordResult {
  submit: (input: PasswordChangeRequest) => Promise<void>;
  submitting: boolean;
  succeeded: boolean;
  error: ApiError | null;
}

/**
 * 비밀번호 변경 제출과 성공/오류 상태를 노출한다. 대상은 항상 현재 세션 사용자.
 */
export function useChangePassword(): UseChangePasswordResult {
  const [submitting, setSubmitting] = useState(false);
  const [succeeded, setSucceeded] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = useCallback(async (input: PasswordChangeRequest): Promise<void> => {
    // 재제출 시 직전 결과 신호(성공/오류)를 해제하고 진행 표시.
    setSubmitting(true);
    setSucceeded(false);
    setError(null);
    try {
      await authApi.changePassword(input);
      // 204 성공: 성공 상태 확정(Req 4.3). error 는 위에서 이미 해제됨.
      setSucceeded(true);
    } catch (caught) {
      // apiClient 는 비정상 응답(422 두 갈래 포함)을 항상 ApiError 로 던진다. 유형 분기 없이 그대로 보관(Req 4.4·4.5).
      if (caught instanceof ApiError) {
        setError(caught);
      }
    } finally {
      setSubmitting(false);
    }
  }, []);

  return { submit, submitting, succeeded, error };
}
