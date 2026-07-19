/**
 * 등록 결선: documentRoutes (design.md §Registration ~212-215; Req 7.1, 8.1).
 *
 * 문서 메인 화면(`DocumentWorkspacePage`)과 휴지통 화면(`TrashPage`)을 s16 **보호 슬롯**
 * (`scope: "protected"`)에 대응시키는 `RouteModule[]` 을 export 한다. s16 취합 함수
 * (`collectRoutesByScope`/`composeRouter`)가 이를 보호 슬롯(`ProtectedRoute` 하위 pathless
 * 레이아웃 자식)에 가산 합성한다(Req 7.1·8.1).
 *
 * 경계: 프레임·가드·전역 401·Provider 마운트는 s16(`@/app/router`·`ProtectedRoute`·`main.tsx`)이
 * 단일 소유하며 여기서 재정의하지 않는다. 이 모듈은 `RouteModule[]`(경로·element)만 제공한다.
 * 툴바·휴지통의 editor+ 게이팅은 각 화면(DocumentToolbar/TrashList)이 내부 RequireRole 로
 * self-gating 하므로 이 라우트 층은 별도 게이트를 재구현하지 않는다.
 *
 * 보호 슬롯은 pathless 레이아웃 자식이라 라우트 정의에는 **상대 경로**("documents"/"trash")를,
 * 네비게이션·테스트용 **절대 경로**는 이 파일의 상수(DOCUMENTS_PATH/TRASH_PATH)를 쓴다
 * (하드코딩 산재 금지, s18 WORKSPACE_PATH idiom).
 *
 * Requirements:
 * - 7.1 문서 메인 화면을 s16 보호 프레임 하위 경로로 결선
 * - 8.1 휴지통 화면을 s16 RouteModule 계약(보호 슬롯)에 결선
 */

import type { RouteModule } from "@/app/routeModule";

import { DocumentWorkspacePage } from "./pages/DocumentWorkspacePage";
import { TrashPage } from "./pages/TrashPage";

// s19 소유 화면 경로(절대). 보호 슬롯 상대 경로("documents"/"trash")와 짝을 이루며, 네비게이션·
// 테스트는 이 상수를 소비한다(단일 소스로 여기 정의; 하드코딩 산재 금지).
export const DOCUMENTS_PATH = "/documents";
export const TRASH_PATH = "/trash";

/** 문서 메인 화면·휴지통 화면을 s16 보호 슬롯에 대응시키는 등록 결선 계약. */
export const documentRoutes: RouteModule[] = [
  {
    scope: "protected",
    routes: [
      { path: "documents", element: <DocumentWorkspacePage /> },
      { path: "trash", element: <TrashPage /> },
    ],
  },
];
