/**
 * 앱 부트스트랩 조립부 (task 7.1, design.md "Architecture → Bootstrap").
 *
 * Provider 트리(외곽→내부)를 조립하고 데이터 라우터를 마운트한다:
 *   ErrorBoundary → SessionProvider → CurrentWorkspaceProvider
 *     → composeProviders(featureProviders) 슬롯 → RouterProvider
 *
 * - `ErrorBoundary`(최외곽): 하위 트리 렌더 예외를 포착해 앱 크래시 대신 복구 화면을 표시한다.
 * - `SessionProvider`: 로드 시 `/auth/me`(→`/me/settings`)로 세션을 부트스트랩한다(AC 5.1).
 * - `CurrentWorkspaceProvider`: Session 하위에 마운트되어 인증 시 `/workspaces` 를 로드한다(AC 9.2).
 * - `composeProviders(featureProviders, …)`: feature Provider 합성 슬롯(AC 10.3). s16 은 비어 있고
 *   s17+ 가 `main.tsx` 수기 편집 없이 이 배열로 자기 Provider 를 가산 등록한다.
 * - `RouterProvider`: `composeRouter(RouteModule[])` 로 단일 취합한 라우터를 마운트한다(AC 10.1).
 *
 * 라우터 생성 직후 {@link installNavigation} 으로 NavSeam 을 결선해, 전역 401 인터셉터가 실제
 * 라우팅으로 로그인 리다이렉트하도록 한다(AC 4.1/4.2).
 *
 * Requirements: 2.1(라우트 프레임 취합), 4.1/4.2(401→라우터 결선), 5.1(세션 부트스트랩),
 * 9.2(현재 WS 부트스트랩), 10.1(라우트 단일 취합), 10.3(Provider 합성 슬롯).
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { ErrorBoundary } from "@/app/ErrorBoundary";
import { installNavigation } from "@/app/installNavigation";
import { composeProviders } from "@/app/providers";
import type { ProviderComponent } from "@/app/providers";
import { composeRouter } from "@/app/routeModule";
import type { RouteModule } from "@/app/routeModule";
import { authRoutes } from "@/features/auth/routes";
import { workspaceRoutes } from "@/features/workspace/routes";
import { MembershipRoleProvider } from "@/features/workspace/context/membershipRoleSource";
import { SessionProvider } from "@/app/session/SessionProvider";
import { CurrentWorkspaceProvider } from "@/app/workspace-context/CurrentWorkspaceProvider";
import "@/index.css";

// feature 라우트 등록 슬롯 — s17(authRoutes: 게스트=로그인·보호=비밀번호 변경)에 이어 s18
// (workspaceRoutes: 보호=워크스페이스 관리·admin 서브트리)을 가산 등록한다(D-2 승인 append).
const featureRouteModules: RouteModule[] = [...authRoutes, ...workspaceRoutes];

// feature Provider 합성 슬롯 — s18 MembershipRoleProvider 를 등록해 CurrentWorkspaceProvider 하위·
// 라우터 상위에 마운트한다. 보호 화면의 owner 패널이 useMembershipRoleSource() 로 role 을 조달한다
// (D-1/D-2 승인). s16 앰비언트 role 은 null 유지(주입하지 않음).
const featureProviders: ProviderComponent[] = [MembershipRoleProvider];

// 단일 취합 지점: RouteModule[] → 데이터 라우터. 프레임(보호/게스트 슬롯·ProtectedRoute 래핑)은
// `@/app/router` 가 단일 소유하며 여기서 라우트를 수기 편집하지 않는다.
const router = composeRouter(featureRouteModules);

// 라우터 준비 완료 → NavSeam 결선(navigator + 정규 buildLoginPath). 이후 401 인터셉터가 실제
// 라우팅으로 returnTo 보존 로그인 리다이렉트를 수행한다.
installNavigation(router);

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found in index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <SessionProvider>
        <CurrentWorkspaceProvider>
          {composeProviders(featureProviders, <RouterProvider router={router} />)}
        </CurrentWorkspaceProvider>
      </SessionProvider>
    </ErrorBoundary>
  </StrictMode>,
);
