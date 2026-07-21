/**
 * 세션 컨텍스트 부트스트랩 provider (design.md "app / session → SessionProvider & useSession").
 *
 * 앱 로드(및 `refresh()`) 시 `GET /auth/me`(`skipAuthRedirect:true`)로 현재 사용자를 확정하고,
 * 성공하면 `GET /me/settings`로 본인 설정을 이어 로드한다. 결과를 tri-state
 * `SessionState`(loading|authenticated|unauthenticated) + `user`(is_admin 포함) + `settings`
 * + `refresh()` 로 노출한다. 로그인/로그아웃 write 흐름은 s17 이 `refresh()` 진입점으로 소비한다.
 *
 * Requirements:
 * - 5.1 `/auth/me` 로 사용자 확정 후 컨텍스트 노출 / 5.2 성공 시 `/me/settings` 로드
 * - 5.3 `/auth/me` 401 → 미인증 확정, 설정 로드 건너뜀(부트스트랩 예외: 리다이렉트 없음)
 * - 5.4 loading·authenticated·unauthenticated tri-state 노출 / 5.5 `refresh()` 재부트스트랩 진입점
 * - 5.6 `is_admin` 노출(권한 게이팅 admin override, INV-3)
 *
 * 계약 경계: `AuthUser`/`UserSettings` 는 백엔드 `AuthUserRead`/`UserSettingsRead`(각각
 * `backend/app/auth/schemas.py`·`backend/app/user_settings/schemas.py`)를 미러링만 하며 필드를
 * 발명하지 않는다. 전역 401 리다이렉트는 apiClient 단일 지점 소유이므로 여기서 재구현하지 않는다.
 */

import { createContext, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";

/** `GET /auth/me` → `AuthUserRead` 미러(민감 필드 제외). */
export interface AuthUser {
  id: number;
  login_id: string;
  name: string;
  email: string | null;
  is_admin: boolean;
}

/** `GET /me/settings` → `UserSettingsRead` 미러. */
export interface UserSettings {
  autosave_enabled: boolean;
  /** 마지막 선택 워크스페이스 id(재로그인·새 브라우저 복원용). 미선택 시 null. */
  last_selected_workspace_id: number | null;
}

/** 부트스트랩 판정 tri-state. authenticated 는 사용자 확정, settings 는 nullable. */
export type SessionState =
  | { status: "loading" }
  | { status: "authenticated"; user: AuthUser; settings: UserSettings | null }
  | { status: "unauthenticated" };

/** 컨텍스트 노출 형태: 상태 + 재부트스트랩 진입점. */
export type SessionContextValue = SessionState & { refresh: () => Promise<void> };

/**
 * 세션 컨텍스트. provider 밖 소비를 감지하기 위해 기본값을 `null` 로 둔다(useSession 가드).
 * useSession 훅이 이 컨텍스트를 소비한다.
 */
export const SessionContext = createContext<SessionContextValue | null>(null);

/** 401 미인증 판정: ApiError 이며 상태 401 또는 코드 `unauthenticated`(AC 5.3). */
function isUnauthenticated(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.code === "unauthenticated");
}

/**
 * 세션 컨텍스트 provider. status 와 무관하게 항상 `children` 을 렌더한다(라우트 게이팅은 3.3
 * ProtectedRoute 소유). 마운트 시 1회 부트스트랩하고 `refresh()` 로 재실행할 수 있다.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  // 언마운트 후 setState 방지 + 최신 실행만 반영(refresh 와 마운트 부트스트랩 경합 시 latest-wins).
  const mountedRef = useRef(true);
  const runIdRef = useRef(0);

  const bootstrap = useCallback(async (): Promise<void> => {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    // 최신 실행이며 여전히 마운트 상태일 때만 반영.
    const apply = (next: SessionState): void => {
      if (mountedRef.current && runIdRef.current === runId) {
        setState(next);
      }
    };

    let user: AuthUser;
    try {
      // skipAuthRedirect:true — 부트스트랩 401 이 전역 로그인 리다이렉트를 트리거하지 않게(AC 5.3, 4.4).
      user = await apiClient.get<AuthUser>("/auth/me", { skipAuthRedirect: true });
    } catch (error) {
      // 401 은 미인증 확정 + 설정 로드 건너뜀(AC 5.3). 그 외 실패도 세션을 확정할 수 없어(tri-state 에
      // error 상태 없음) 미인증으로 수렴한다(로딩 고착 방지, 리다이렉트 없음).
      if (isUnauthenticated(error)) {
        apply({ status: "unauthenticated" });
        return;
      }
      apply({ status: "unauthenticated" });
      return;
    }

    // /auth/me 성공 → 인증 확정. 설정 로드는 실패해도 인증을 무르지 않고 settings:null 로 남긴다(AC 5.2).
    let settings: UserSettings | null = null;
    try {
      settings = await apiClient.get<UserSettings>("/me/settings");
    } catch {
      settings = null;
    }

    apply({ status: "authenticated", user, settings });
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void bootstrap();
    return () => {
      mountedRef.current = false;
    };
  }, [bootstrap]);

  const value = useMemo<SessionContextValue>(
    () => ({ ...state, refresh: bootstrap }),
    [state, bootstrap],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
