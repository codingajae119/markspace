/**
 * 등록 결선: editorRoutes (design.md §Registration ~236-239; Req 7.1, 7.6).
 *
 * 편집 화면(`DocumentEditPage`)을 s16 **보호 슬롯**(`scope: "protected"`)에 대응시키는
 * `RouteModule[]` 을 export 한다. s16 취합 함수(`collectRoutesByScope`/`composeRouter`)가
 * 이를 보호 슬롯(`ProtectedRoute` 하위 pathless 레이아웃 자식)에 가산 합성한다(Req 7.6).
 *
 * 경계: 프레임·가드·전역 401·Provider 마운트는 s16(`@/app/router`·`ProtectedRoute`·`main.tsx`)이
 * 단일 소유하며 여기서 재정의하지 않는다. 이 모듈은 `RouteModule[]`(경로·element)만 제공한다.
 * 편집 진입점 게이팅(viewer 미노출)은 s19 뷰어가, 최종 권한 경계는 서버(403)가 소유하므로 이
 * 라우트 층은 별도 role 게이트를 재구현하지 않는다(Req 1.5·7.2·7.8).
 *
 * 보호 슬롯은 pathless 레이아웃 자식이라 라우트 정의에는 **상대 경로**("documents/:id/edit")를,
 * 네비게이션·테스트용 **절대 경로**는 이 파일의 상수(DOCUMENT_EDIT_PATH)를 쓴다(하드코딩 산재
 * 금지, s18 WORKSPACE_PATH / s19 DOCUMENTS_PATH idiom). 진입 경로 규약을 이 상수로 노출해
 * s19 진입점이 도달하게 한다(cross-spec 정합; 두 feature 는 서로 직접 import 하지 않는다).
 *
 * Requirements:
 * - 7.1 편집 화면을 s16 보호 프레임 하위 경로로 결선
 * - 7.6 편집 라우트를 s16 RouteModule 계약(보호 슬롯)에 결선(프레임·가드 재구현 금지)
 */

import type { RouteModule } from "@/app/routeModule";

import { DocumentEditPage } from "./pages/DocumentEditPage";

// s20 소유 편집 화면 경로(절대). 보호 슬롯 상대 경로("documents/:id/edit")와 짝을 이루며,
// 네비게이션·테스트는 이 상수를 소비한다(단일 소스로 여기 정의; 하드코딩 산재 금지).
export const DOCUMENT_EDIT_PATH = "/documents/:id/edit";

/** 편집 화면을 s16 보호 슬롯에 대응시키는 등록 결선 계약. */
export const editorRoutes: RouteModule[] = [
  {
    scope: "protected",
    routes: [{ path: "documents/:id/edit", element: <DocumentEditPage /> }],
  },
];
