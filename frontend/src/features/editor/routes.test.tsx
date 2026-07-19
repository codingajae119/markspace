import { describe, it, expect } from "vitest";
import type { ReactElement } from "react";

import { editorRoutes, DOCUMENT_EDIT_PATH } from "./routes";
import { DocumentEditPage } from "./pages/DocumentEditPage";

/**
 * s20 등록 결선(구조) 테스트: editorRoutes(보호 슬롯 RouteModule[])가 s16 계약 형태(scope +
 * routes 배열)를 만족하고, 편집 화면 상대 경로("documents/:id/edit")를 DocumentEditPage
 * element 로 노출하며, 네비게이션용 절대 경로 상수(DOCUMENT_EDIT_PATH)를 단일 소스로 조달함을
 * 관측한다. 프레임·가드·전역 401 은 s16 소유이므로 여기서 검증하지 않는다(Req 7.6).
 */
describe("editorRoutes 등록 결선 (보호 슬롯 편집 화면)", () => {
  it("editorRoutes 는 보호 슬롯 RouteModule[] 이며 편집 화면 상대 경로를 노출한다 (Req 7.1, 7.6)", () => {
    // 모든 모듈은 유효한 RouteModule 형태(scope + routes 배열)여야 한다.
    for (const module of editorRoutes) {
      expect(["protected", "guest"]).toContain(module.scope);
      expect(Array.isArray(module.routes)).toBe(true);
    }

    const guarded = editorRoutes.find((module) => module.scope === "protected");
    expect(guarded).toBeDefined();

    const paths = guarded?.routes.map((route) => route.path) ?? [];
    // 보호 슬롯은 pathless 레이아웃 자식이라 상대 경로로 등록된다(절대 경로는 상수로 노출).
    expect(paths).toContain("documents/:id/edit");

    // 게스트 슬롯은 도입하지 않는다(편집 화면은 보호 대상).
    expect(editorRoutes.find((module) => module.scope === "guest")).toBeUndefined();
  });

  it("절대 경로 상수는 단일 소스로 노출된다 (Req 7.1, 7.6)", () => {
    expect(DOCUMENT_EDIT_PATH).toBe("/documents/:id/edit");
  });

  it("documents/:id/edit 라우트 element 는 DocumentEditPage 다 (Req 7.1, 7.6)", () => {
    const guarded = editorRoutes.find((module) => module.scope === "protected");

    const editRoute = guarded?.routes.find(
      (route) => route.path === "documents/:id/edit",
    );
    expect(editRoute).toBeDefined();
    expect(editRoute?.element).not.toBeNull();
    expect((editRoute?.element as ReactElement).type).toBe(DocumentEditPage);
  });
});
