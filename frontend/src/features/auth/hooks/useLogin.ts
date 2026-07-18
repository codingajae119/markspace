/**
 * 로그인 useCase 훅 (design.md "features/auth/hooks → useLogin").
 *
 * 자격 제출 → `authApi.login()` → s16 `useSession().refresh()` 로 세션을 확정한 뒤
 * `resolveReturnTo(location.search)` 경로로 네비게이션한다(returnTo 없으면 기본 홈).
 * 실패 시 `ApiError` 를 상태로 보관해 폼이 `ErrorMessage` 로 인라인 표시하게 하고(리다이렉트 없음),
 * 진행 중 `submitting` 플래그로 중복 제출을 방지한다. 재제출 시 직전 오류를 해제한다.
 *
 * 계약 경계(모두 s16 소비, 재구현 금지):
 * - 세션 write 는 `useSession().refresh()` 단일 진입점으로만 수행(세션 컨텍스트는 s16 소유).
 * - 복귀 경로 파싱/기본값(홈)은 `resolveReturnTo` 규약에만 위임(로컬 재구현 금지).
 * - 로그인 401 인라인 처리는 authApi 의 `skipAuthRedirect` 경로로 이미 분리되어 있다.
 *
 * Requirements:
 * - 1.2 자격 제출(`authApi.login`) / 1.3 성공 시 세션 반영 후 복귀
 * - 1.4 진행 중 중복 제출 방지(`submitting`) / 1.5 returnTo 복귀(없으면 기본 홈) 위임
 * - 2.1 실패 시 인라인 error 세팅·리다이렉트 없음 / 2.3 skipAuthRedirect 경로 유지
 * - 2.5 재제출 시 직전 오류 해제 / 5.1 세션 반영은 refresh 단일 진입점
 */

import { useCallback, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";

import { authApi } from "../api/authApi";
import type { LoginRequest } from "../api/authApi";
import { useSession } from "@/app/session/useSession";
import { resolveReturnTo } from "@/app/routes";
import { ApiError } from "@/shared/api/errors";

/** useLogin 이 노출하는 제출 액션·진행 상태·인라인 오류. */
export interface UseLoginResult {
  submit: (credentials: LoginRequest) => Promise<void>;
  submitting: boolean;
  error: ApiError | null;
}

/**
 * 로그인 제출·세션 반영·returnTo 복귀와 진행/오류 상태를 노출한다.
 */
export function useLogin(): UseLoginResult {
  const navigate = useNavigate();
  const location = useLocation();
  const { refresh } = useSession();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = useCallback(
    async (credentials: LoginRequest): Promise<void> => {
      // 재제출 시 직전 오류 해제(Req 2.5) + 진행 표시(Req 1.4).
      setSubmitting(true);
      setError(null);
      try {
        await authApi.login(credentials);
        // 성공: 세션 확정(Req 5.1) 후 복귀(Req 1.3·1.5). refresh 이전 리다이렉트를 피한다.
        await refresh();
        navigate(resolveReturnTo(location.search));
      } catch (caught) {
        // apiClient 는 비정상 응답을 항상 ApiError 로 던진다. 그 외는 안전하게 무시(Req 2.1).
        if (caught instanceof ApiError) {
          setError(caught);
        }
        // 실패 시 네비게이션하지 않는다(리다이렉트 없음).
      } finally {
        setSubmitting(false);
      }
    },
    [refresh, navigate, location.search],
  );

  return { submit, submitting, error };
}
