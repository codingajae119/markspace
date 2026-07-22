import { describe, it, expect } from "vitest";
import type { ReactElement } from "react";
import { Navigate } from "react-router-dom";

import { documentRoutes, DOCUMENTS_PATH, TRASH_PATH } from "./routes";
import { DocumentWorkspacePage } from "./pages/DocumentWorkspacePage";
import { TrashPage } from "./pages/TrashPage";

// s19 등록 결선(구조) 테스트: documentRoutes(보호 슬롯 RouteModule[])가 s16 계약 형태(scope +
// routes 배열)를 만족하고, 문서 메인·휴지통 상대 경로("documents"/"trash")를 해당 페이지
// element 로 노출하며, 네비게이션용 절대 경로 상수(DOCUMENTS_PATH/TRASH_PATH)를 단일 소스로
// 조달함을 관찰한다. 프레임·가드·전역 401 은 s16 소유이므로 여기서 검증하지 않는다.
describe("documentRoutes 등록 결선 (보호 슬롯 문서 메인 + 휴지통)", () => {
  it("documentRoutes 는 보호 슬롯 RouteModule[] 이며 문서·휴지통 상대 경로를 노출한다 (Req 7.1, 8.1)", () => {
    // 모든 모듈은 유효한 RouteModule 형태(scope + routes 배열)여야 한다.
    for (const module of documentRoutes) {
      expect(["protected", "guest"]).toContain(module.scope);
      expect(Array.isArray(module.routes)).toBe(true);
    }

    const guarded = documentRoutes.find((module) => module.scope === "protected");
    expect(guarded).toBeDefined();

    const paths = guarded?.routes.map((route) => route.path) ?? [];
    // 보호 슬롯은 pathless 레이아웃 자식이라 상대 경로로 등록된다(절대 경로는 상수로 노출).
    expect(paths).toContain("documents");
    expect(paths).toContain("trash");

    // 게스트 슬롯은 도입하지 않는다(문서·휴지통 모두 보호 대상).
    expect(documentRoutes.find((module) => module.scope === "guest")).toBeUndefined();
  });

  it("절대 경로 상수는 단일 소스로 노출된다 (Req 7.1, 8.1)", () => {
    expect(DOCUMENTS_PATH).toBe("/documents");
    expect(TRASH_PATH).toBe("/trash");
  });

  it("documents 라우트 element 는 DocumentWorkspacePage, trash 라우트 element 는 TrashPage 다 (Req 7.1, 8.1)", () => {
    const guarded = documentRoutes.find((module) => module.scope === "protected");

    const docRoute = guarded?.routes.find((route) => route.path === "documents");
    expect(docRoute).toBeDefined();
    expect((docRoute?.element as ReactElement).type).toBe(DocumentWorkspacePage);

    const trashRoute = guarded?.routes.find((route) => route.path === "trash");
    expect(trashRoute).toBeDefined();
    expect((trashRoute?.element as ReactElement).type).toBe(TrashPage);
  });

  it("보호 영역 index(홈, `/`) 라우트는 canonical `/documents` 로 리다이렉트한다", () => {
    const guarded = documentRoutes.find((module) => module.scope === "protected");

    const indexRoute = guarded?.routes.find((route) => route.index === true);
    expect(indexRoute).toBeDefined();

    const element = indexRoute?.element as ReactElement;
    expect(element.type).toBe(Navigate);
    expect((element.props as { to: string; replace?: boolean }).to).toBe(DOCUMENTS_PATH);
    expect((element.props as { to: string; replace?: boolean }).replace).toBe(true);
  });
});
