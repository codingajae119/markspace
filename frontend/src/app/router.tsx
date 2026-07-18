/**
 * 라우터 셸: 보호/게스트 라우트 프레임 (design.md "app / router → Router & ProtectedRoute").
 *
 * 라우트 트리 최상위에 게스트 라우트(`/share/:token`, 인증 가드 없음)와 보호 영역
 * (`ProtectedRoute` 레이아웃 하위)을 등록하는 **정적 프레임**을 정의한다. 하위 spec 화면은
 * 이 프레임의 슬롯에 자식 라우트로 등록만 하며(내용은 s17~s22 소유), s16 은 프레임·경로
 * 규약만 소유한다.
 *
 * ## 등록 seam (3.5 / 7.1 결선 지점)
 * feature 라우트를 가산(additive) 합성하는 정식 메커니즘(`composeRouter(RouteModule[])`)은
 * task 3.5 소유다. 이 task 는 그 메커니즘이 플러그인할 **명시적 슬롯**만 노출한다:
 * {@link createAppRoutes} 가 `protectedRoutes`(보호 슬롯: `ProtectedRoute` 하위 자식)와
 * `guestRoutes`(게스트 슬롯: 가드 없는 최상위)를 파라미터로 받아 프레임에 주입한다. 3.5 의
 * `composeRouter` 와 7.1 조립은 `RouteModule[]` 을 scope 별로 분류해 이 파라미터로 전달하면
 * 된다(이 파일 수기 편집 없이 가산 등록). `composeRouter` 는 아직 존재하지 않으므로 import
 * 하지 않는다 — 이 모듈은 자립적이며 지금 테스트 가능하다.
 *
 * ## 플레이스홀더 경계 (동일 path additive 라우트가 플레이스홀더를 치환)
 * `/login` 화면은 s17, `/share/:token` 뷰는 s22 소유다. 프레임이 지금 렌더·리다이렉트
 * 가능하도록 각 경로에 최소 인라인 플레이스홀더만 둔다. 하위 spec 이 **동일 path** 의 게스트
 * 라우트를 `guestRoutes` 로 등록하면 해당 built-in 플레이스홀더는 그 실제 화면으로 **치환**된다
 * (플레이스홀더가 실제 화면을 가리지 않도록 path 기준으로 override). 보호 영역에도 루트 index
 * 플레이스홀더를 두어 프레임이 단독으로 렌더 가능하다.
 *
 * ## AppLayout(5.2) 경계
 * 인증 영역 공통 레이아웃 `AppLayout` 은 task 5.2 소유이며 아직 존재하지 않는다. 이 task 는
 * 보호 슬롯 element 로 `ProtectedRoute`(authenticated 분기가 `<Outlet />` 렌더)만 사용하고,
 * `AppLayout` 래핑은 5.2/7.1 조립에서 합성한다(여기서 import/생성 금지).
 *
 * Requirements: 2.1(보호/게스트 프레임·등록 지점), 2.2(returnTo 리다이렉트 — ProtectedRoute),
 * 2.4(게스트 라우트 가드 없음), 2.5(loading 유보 — ProtectedRoute), 4.3(게스트 경로 강제
 * 리다이렉트 없음).
 */

import { createBrowserRouter } from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { ProtectedRoute } from "@/app/ProtectedRoute";
import { ROUTES } from "@/app/routes";

/** `/login` 최소 플레이스홀더. 실제 로그인 화면은 s17 소유(returnTo 복귀 대상 존재 보장용). */
function LoginPlaceholder() {
  return <div>login</div>;
}

/** `/share/:token` 게스트 뷰 최소 플레이스홀더. 실제 공개 읽기 뷰는 s22 소유(가드 없음). */
function SharePlaceholder() {
  return <div>share</div>;
}

/** 보호 영역 루트 index 플레이스홀더. feature 홈 라우트가 등록되기 전 프레임 단독 렌더용. */
function RootIndexPlaceholder() {
  return <div>home</div>;
}

/** feature 라우트를 프레임 슬롯에 가산 주입하는 확장 지점(3.5 `composeRouter`/7.1 조립이 소비). */
export interface AppRouteExtensions {
  /** 보호 슬롯(`ProtectedRoute` 하위 자식)에 등록할 feature 라우트. */
  protectedRoutes?: RouteObject[];
  /** 게스트 슬롯(가드 없는 최상위)에 등록할 feature 라우트. */
  guestRoutes?: RouteObject[];
}

/**
 * 보호/게스트 프레임의 라우트 객체 배열을 구성한다. 테스트는 이를 `createMemoryRouter` 로,
 * 앱 부팅은 {@link createAppRouter} 가 `createBrowserRouter` 로 마운트한다.
 *
 * 트리 구조:
 * - `/login` (플레이스홀더, s17) · `/share/:token`(게스트, 가드 없음, s22) + `guestRoutes` 슬롯
 * - `ProtectedRoute` 레이아웃(가드): 루트 index 플레이스홀더 + `protectedRoutes` 슬롯
 *
 * 하위 spec 이 동일 path 의 게스트 라우트를 등록하면 그 built-in 플레이스홀더를 대체(치환)한다.
 * 플레이스홀더가 먼저 등록되어 실제 화면을 가리는(shadow) 것을 막기 위해 path 로 override 한다.
 */
export function createAppRoutes(ext: AppRouteExtensions = {}): RouteObject[] {
  const { protectedRoutes = [], guestRoutes = [] } = ext;

  // 하위 spec 이 동일 path 의 게스트 라우트를 등록하면 그 built-in 플레이스홀더를 대체(치환)한다.
  const overriddenGuestPaths = new Set(
    guestRoutes
      .map((route) => route.path)
      .filter((path): path is string => typeof path === "string"),
  );
  // 게스트/공개 최상위 라우트 — 인증 가드 없음(AC 2.4, 4.3). 동일 path additive 라우트가 있으면 제외.
  const builtInGuest: RouteObject[] = [
    { path: ROUTES.login, element: <LoginPlaceholder /> },
    { path: ROUTES.share, element: <SharePlaceholder /> },
  ].filter((route) => typeof route.path !== "string" || !overriddenGuestPaths.has(route.path));

  return [
    ...builtInGuest,
    ...guestRoutes,
    // 보호 영역 — 세션 가드 레이아웃. 자식은 `<Outlet />` 로 렌더된다(AppLayout 래핑은 5.2/7.1).
    {
      element: <ProtectedRoute />,
      children: [{ index: true, element: <RootIndexPlaceholder /> }, ...protectedRoutes],
    },
  ];
}

/**
 * 앱 부팅용 브라우저 라우터를 생성한다. `createBrowserRouter` 는 앱/빌드에서만 실행되며
 * (테스트는 `createMemoryRouter` + {@link createAppRoutes} 사용) 7.1 조립에서 feature
 * `RouteModule[]` 을 scope 별로 분류해 {@link AppRouteExtensions} 로 전달하면 된다.
 */
export function createAppRouter(ext: AppRouteExtensions = {}): ReturnType<typeof createBrowserRouter> {
  return createBrowserRouter(createAppRoutes(ext));
}
