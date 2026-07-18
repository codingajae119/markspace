/**
 * 라우트 등록 메커니즘: `RouteModule[]` 단일 취합 (design.md "app / route + provider
 * registration → RouteRegistry & ProviderComposition").
 *
 * 각 feature(s17~s22)는 `router.tsx`/`main.tsx` 를 **수기 편집하지 않고** 자기 라우트 정의를
 * `RouteModule[]` 로 export 하기만 하면, s16 의 이 취합 지점이 scope 별로 보호/게스트 슬롯에
 * 분류해 라우터 트리를 구성한다(가산 등록, AC 10.1). 프레임(보호/게스트 슬롯 + `ProtectedRoute`
 * 래핑)은 여전히 `@/app/router`(task 3.3)가 단일 소유하며, 이 모듈은 그 프레임의 확장 파라미터
 * ({@link AppRouteExtensions})로 라우트를 주입만 한다(프레임을 재정의하지 않음).
 *
 * ## 안정 소비 계약 (AC 10.4)
 * 아래 형태는 s17~s22 가 바인딩하는 **안정 계약**이다. 변경 시 하위 spec **재검증 트리거**다:
 * - {@link RouteModule} 필드(`scope: "protected" | "guest"`, `routes: RouteObject[]`)
 * - {@link composeRouter} 시그니처(`RouteModule[]` → `createBrowserRouter` 결과)
 * - {@link collectRoutesByScope} 시그니처(순수 분류 헬퍼)
 * - Provider 합성은 `providers.ts` 의 `composeProviders`(AC 10.3)가 짝으로 소유.
 *
 * Requirements: 10.1(단일 취합·가산 등록), 10.2(보호/게스트 슬롯 명시 구분), 10.4(계약 문서화).
 */

import type { RouteObject, createBrowserRouter } from "react-router-dom";

import { createAppRouter } from "@/app/router";

/**
 * feature 라우트 등록 단위. feature 는 이 형태의 배열을 export 하기만 하면 취합된다.
 *
 * - `scope`: 등록 슬롯 선택 — `"protected"`(세션 가드 `ProtectedRoute` 하위) 또는
 *   `"guest"`(가드 없는 최상위, 예: `/share/:token` 계열).
 * - `routes`: react-router 라우트 정의. 엘리먼트(화면 내용)는 feature 소유다.
 */
export interface RouteModule {
  scope: "protected" | "guest";
  routes: RouteObject[];
}

/**
 * 모듈들을 scope 별로 분류한 순수 헬퍼. 같은 scope 의 여러 모듈은 등장 순서대로 병합된다.
 *
 * {@link composeRouter} 가 내부적으로 사용하며, 브라우저 라우터를 내비게이트하지 않고도
 * 슬롯 배치(AC 10.1/10.2)를 결정적으로 검증할 수 있게 별도 export 한다(jsdom 데이터 라우터
 * 내비게이션 비호환 회피 — `router.tsx` 주석 참조).
 */
export function collectRoutesByScope(modules: RouteModule[]): {
  protectedRoutes: RouteObject[];
  guestRoutes: RouteObject[];
} {
  const protectedRoutes: RouteObject[] = [];
  const guestRoutes: RouteObject[] = [];

  for (const module of modules) {
    if (module.scope === "protected") {
      protectedRoutes.push(...module.routes);
    } else {
      guestRoutes.push(...module.routes);
    }
  }

  return { protectedRoutes, guestRoutes };
}

/**
 * feature `RouteModule[]` 을 단일 취합해 앱 부팅용 브라우저 라우터를 만든다(AC 10.1).
 *
 * scope 로 분류({@link collectRoutesByScope})한 뒤 프레임의 확장 파라미터로 전달하며, 프레임
 * 구성·`ProtectedRoute` 래핑은 `@/app/router` 의 {@link createAppRouter} 가 단일 소유한다
 * (여기서 프레임을 재정의하지 않음). 반환값은 `createBrowserRouter` 결과다.
 */
export function composeRouter(modules: RouteModule[]): ReturnType<typeof createBrowserRouter> {
  const { protectedRoutes, guestRoutes } = collectRoutesByScope(modules);
  return createAppRouter({ protectedRoutes, guestRoutes });
}
