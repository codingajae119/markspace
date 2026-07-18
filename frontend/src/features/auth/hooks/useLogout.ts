/**
 * 로그아웃 useCase 훅 (design.md "features/auth/hooks → useLogout" + "로그아웃 플로우").
 *
 * `authApi.logout()` → s16 `useSession().refresh()`(미인증 전이 확정) → `navigate(ROUTES.login)`.
 * 순서는 logout → refresh → navigate 를 반드시 지켜, 세션 미인증 전이가 확정된 뒤에만 로그인 경로로
 * 이동한다. 진행 중 `submitting` 플래그로 중복 실행을 막고 `finally` 에서 리셋한다.
 *
 * 계약 경계(모두 s16 소비, 재구현 금지):
 * - 세션 반영은 `useSession().refresh()` 단일 진입점으로만 수행(세션 컨텍스트는 s16 소유, 자체 세션 스토어 없음).
 * - 이동 목적지는 s16 `ROUTES.login` 상수 사용(경로 하드코딩 금지).
 * - 세션이 이미 만료된 경우의 전역 401 인터셉터 이동 보장은 s16 소유(여기서 별도 처리하지 않음).
 *
 * Requirements:
 * - 3.2 로그아웃 액션(`authApi.logout`) / 3.3 로그아웃 후 세션 반영 + 로그인 이동
 * - 3.4 진행 중 중복 실행 방지(`submitting`) / 5.1 세션 반영은 refresh 단일 진입점
 */

import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { authApi } from "../api/authApi";
import { useSession } from "@/app/session/useSession";
import { ROUTES } from "@/app/routes";

/** useLogout 이 노출하는 로그아웃 액션·진행 상태. */
export interface UseLogoutResult {
  submit: () => Promise<void>;
  submitting: boolean;
}

/**
 * 로그아웃 제출·세션 미인증 전이·로그인 이동과 진행 상태를 노출한다.
 */
export function useLogout(): UseLogoutResult {
  const navigate = useNavigate();
  const { refresh } = useSession();
  const [submitting, setSubmitting] = useState(false);
  // in-flight 가드: state 는 비동기 반영이라 같은 tick 재호출을 못 막으므로 ref 로 즉시 차단(Req 3.4).
  const inFlight = useRef(false);

  const submit = useCallback(async (): Promise<void> => {
    // 진행 중이면 중복 실행을 무시한다(Req 3.4).
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setSubmitting(true);
    try {
      // 순서 고정: logout → refresh(미인증 전이 확정) → navigate. 전이 확정 전 이동을 피한다(Req 3.3·5.1).
      await authApi.logout();
      await refresh();
      navigate(ROUTES.login);
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }, [refresh, navigate]);

  return { submit, submitting };
}
