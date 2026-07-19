import { describe, it, expect } from "vitest";
import type { ReactElement } from "react";

import { ROUTES } from "@/app/routes";

import { sharingRoutes } from "./routes";
import { SharePage } from "./pages/SharePage";

/**
 * s22 등록 결선(구조) 테스트: sharingRoutes(게스트 슬롯 RouteModule[])가 s16 계약 형태
 * (scope + routes 배열)를 만족하고, `/share/:token`(ROUTES.share, 절대 경로) 게스트 라우트를
 * SharePage element 로 노출하며, 보호 슬롯 모듈은 도입하지 않음을 관측한다. 프레임·가드·no-auth
 * 규약은 s16 소유이므로 여기서 검증하지 않으며, 동일 path 등록이 s16 플레이스홀더를 치환한다.
 */
describe("sharingRoutes 등록 결선 (게스트 슬롯 공개 뷰)", () => {
  it("sharingRoutes 는 게스트 슬롯 RouteModule[] 이며 /share/:token 을 노출한다 (Req 6.1, 8.3)", () => {
    for (const module of sharingRoutes) {
      expect(["protected", "guest"]).toContain(module.scope);
      expect(Array.isArray(module.routes)).toBe(true);
    }

    const guest = sharingRoutes.find((module) => module.scope === "guest");
    expect(guest).toBeDefined();

    const paths = guest?.routes.map((route) => route.path) ?? [];
    // 게스트 라우트는 최상위(절대 경로)로 등록된다 — 하드코딩 금지, ROUTES.share 단일 소스.
    expect(paths).toContain(ROUTES.share);
    expect(ROUTES.share).toBe("/share/:token");

    // 보호 슬롯 모듈은 도입하지 않는다(공개 게스트 전용).
    expect(sharingRoutes.find((module) => module.scope === "protected")).toBeUndefined();
  });

  it("/share/:token 라우트 element 는 SharePage 다 (Req 6.1, 8.3)", () => {
    const guest = sharingRoutes.find((module) => module.scope === "guest");

    const shareRoute = guest?.routes.find((route) => route.path === ROUTES.share);
    expect(shareRoute).toBeDefined();
    expect(shareRoute?.element).not.toBeNull();
    expect((shareRoute?.element as ReactElement).type).toBe(SharePage);
  });
});
