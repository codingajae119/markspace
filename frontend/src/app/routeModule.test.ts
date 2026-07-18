import { describe, it, expect } from "vitest";
import type { RouteObject } from "react-router-dom";

import { collectRoutesByScope, composeRouter } from "@/app/routeModule";
import type { RouteModule } from "@/app/routeModule";

// 순수 취합 헬퍼(collectRoutesByScope)로 슬롯 배치를 결정적으로 검증한다(AC 10.1/10.2).
// composeRouter 는 브라우저 라우터를 만들지만 jsdom 에서 내비게이트할 수 없으므로(데이터 라우터
// AbortSignal realm 비호환) 생성만 확인하고, 배치 검증은 순수 헬퍼로 수행한다.

const protA: RouteObject = { path: "docs/:id", element: null };
const protB: RouteObject = { path: "trash", element: null };
const guestA: RouteObject = { path: "public/:slug", element: null };

describe("collectRoutesByScope — 보호/게스트 슬롯 분류 (AC 10.1, 10.2)", () => {
  it("scope 별로 라우트를 각 슬롯에 배치한다", () => {
    const modules: RouteModule[] = [
      { scope: "protected", routes: [protA] },
      { scope: "guest", routes: [guestA] },
    ];

    const { protectedRoutes, guestRoutes } = collectRoutesByScope(modules);

    expect(protectedRoutes).toContain(protA);
    expect(protectedRoutes).not.toContain(guestA);
    expect(guestRoutes).toContain(guestA);
    expect(guestRoutes).not.toContain(protA);
  });

  it("같은 scope 의 여러 모듈을 순서대로 병합한다", () => {
    const modules: RouteModule[] = [
      { scope: "protected", routes: [protA] },
      { scope: "guest", routes: [guestA] },
      { scope: "protected", routes: [protB] },
    ];

    const { protectedRoutes, guestRoutes } = collectRoutesByScope(modules);

    expect(protectedRoutes).toEqual([protA, protB]);
    expect(guestRoutes).toEqual([guestA]);
  });

  it("빈 모듈 목록이면 두 슬롯 모두 빈 배열이다", () => {
    const { protectedRoutes, guestRoutes } = collectRoutesByScope([]);

    expect(protectedRoutes).toEqual([]);
    expect(guestRoutes).toEqual([]);
  });
});

describe("composeRouter — 단일 취합 → 브라우저 라우터 (AC 10.1, 10.2)", () => {
  it("RouteModule[] 을 취합해 라우터를 생성한다(내비게이트하지 않음)", () => {
    const router = composeRouter([
      { scope: "protected", routes: [protA] },
      { scope: "guest", routes: [guestA] },
    ]);

    expect(router).toBeDefined();
    expect(Array.isArray(router.routes)).toBe(true);
    expect(router.routes.length).toBeGreaterThan(0);
  });

  it("빈 모듈 목록으로도 프레임(게스트 /share/:token 포함)만으로 라우터를 생성한다", () => {
    const router = composeRouter([]);

    expect(router).toBeDefined();
    // 프레임 자체 라우트(/login, /share/:token, 보호 레이아웃)가 존재한다.
    const paths = router.routes.map((r) => r.path);
    expect(paths).toContain("/share/:token");
  });
});
