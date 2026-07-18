/**
 * 인증 엔드포인트(`/auth/*`)의 얇은 타입 래퍼 (design.md "features/auth/api → authApi").
 *
 * s16 공용 `apiClient` 위에 로그인·로그아웃·비밀번호 변경 호출만 타입 안전하게 얹는다. fetch·base URL·
 * credentials·에러 파싱·전역 401 인터셉터는 s16 단일 지점(apiClient)이 소유하므로 여기서 재구현하지 않고
 * 위임한다. 로그인만 `skipAuthRedirect: true` 로 호출해 401 을 인라인 처리 가능하게 하고(전역 리다이렉트 우회),
 * 로그아웃·비밀번호 변경은 기본 경로(전역 401 인터셉터 활성)를 유지한다.
 *
 * Requirements:
 * - 1.2 로그인 자격 제출(`POST /auth/login`) / 3.2 로그아웃(`POST /auth/logout`)
 * - 4.2 본인 비밀번호 변경(`POST /auth/password`) / 6.1 소비 경계(교차 관심사 재구현 금지)
 * - 6.4 feature 격리(다른 feature import 없이 s16 `app`·`shared`만 소비)
 *
 * 계약 경계: 응답 사용자 타입은 s16 정본 `AuthUser`(세션 컨텍스트 타입)를 import 재사용하며 로컬 재선언하지
 * 않는다(drift 방지). 요청 본문 타입만 백엔드 스키마(`LoginRequest`·`PasswordChangeRequest`)를 미러링한다.
 */

import { apiClient } from "@/shared/api/client";
import type { AuthUser } from "@/app/session/SessionProvider";

/** `POST /auth/login` 요청 본문(백엔드 `LoginRequest` 미러). */
export interface LoginRequest {
  login_id: string;
  password: string;
}

/** `POST /auth/password` 요청 본문(백엔드 `PasswordChangeRequest` 미러). */
export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

/**
 * 로그인. 성공 시 정본 `AuthUser` 반환. `skipAuthRedirect: true` 로 호출해 401(단일 `unauthenticated`)이
 * 전역 로그인 리다이렉트를 트리거하지 않고 폼에서 인라인 표면화되도록 한다(REQ 2.3).
 */
function login(input: LoginRequest): Promise<AuthUser> {
  return apiClient.post<AuthUser>("/auth/login", input, { skipAuthRedirect: true });
}

/** 로그아웃. 기본 경로(전역 401 인터셉터 활성)로 호출한다. */
function logout(): Promise<void> {
  return apiClient.post<void>("/auth/logout");
}

/** 본인 비밀번호 변경. 대상은 항상 현재 세션 사용자이며 기본 경로로 호출한다. */
function changePassword(input: PasswordChangeRequest): Promise<void> {
  return apiClient.post<void>("/auth/password", input);
}

/** 하위 훅(useLogin·useLogout·useChangePassword)이 소비하는 얇은 인증 API. */
export const authApi = {
  login,
  logout,
  changePassword,
};
