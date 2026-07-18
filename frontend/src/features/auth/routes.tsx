/**
 * 등록 결선: authRoutes (design.md "features/auth → authRoutes (등록 결선)", Registration).
 *
 * 로그인 화면을 s16 게스트 접근 프레임(`scope: "guest"`, `ROUTES.login`)에, 본인 비밀번호 변경
 * 화면을 s16 보호 프레임(`scope: "protected"`)에 대응시키는 `RouteModule[]` 을 export 한다.
 * s16 `composeRouter`/`collectRoutesByScope` 취합 지점이 이를 각 슬롯에 합성한다(가산 등록).
 *
 * 경계: 프레임·가드·`returnTo` 규약은 s16 `@/app/router`·`ProtectedRoute` 가 단일 소유하며 여기서
 * 재정의하지 않는다. s17 은 `RouteModule[]`(경로·element)만 제공하고 `router.tsx`/`main.tsx` 프레임
 * 코드를 수기 편집하지 않는다. 로그인 경로 상수는 s16 `ROUTES.login` 을 그대로 사용(하드코딩 금지).
 *
 * Requirements:
 * - 1.1 로그인 화면을 게스트 프레임 대상 element 로 결선
 * - 4.1 본인 비밀번호 변경 화면을 보호 프레임 하위 경로로 결선
 * - 6.1 s16 `RouteModule` 계약(scope 슬롯)에만 결선(프레임 재정의 없음)
 * - 6.2/6.3 미인증 시 보호 경로는 s16 가드가 returnTo 보존 로그인으로 리다이렉트(프레임 소유)
 */

import type { RouteModule } from "@/app/routeModule";
import { ROUTES } from "@/app/routes";

import { LoginPage } from "./pages/LoginPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";

// s17 소유 화면 경로. s16 ROUTES(login/root/share)는 교차 관심사 상수이며, 비밀번호 변경 화면은
// s17 feature 소유 경로다(단일 소스로 여기 정의; 하드코딩 산재 금지). 보호 슬롯은 pathless 레이아웃
// (`ProtectedRoute`) 하위 자식이라 라우트 정의에는 상대 경로("settings/password")를, 네비게이션/테스트용
// 절대 경로는 이 상수(CHANGE_PASSWORD_PATH)를 쓴다.
export const CHANGE_PASSWORD_PATH = "/settings/password";

/** 로그인=게스트 슬롯, 비밀번호 변경=보호 슬롯으로 대응하는 s16 등록 결선 계약. */
export const authRoutes: RouteModule[] = [
  { scope: "guest", routes: [{ path: ROUTES.login, element: <LoginPage /> }] },
  { scope: "protected", routes: [{ path: "settings/password", element: <ChangePasswordPage /> }] },
];
