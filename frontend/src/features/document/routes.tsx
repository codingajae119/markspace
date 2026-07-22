/**
 * 등록 결선: documentRoutes (design.md §Registration ~212-215; Req 7.1).
 *
 * 문서 메인 화면(`DocumentWorkspacePage`)을 s16 **보호 슬롯**(`scope: "protected"`)에 대응시키는
 * `RouteModule[]` 을 export 한다. s16 취합 함수(`collectRoutesByScope`/`composeRouter`)가 이를
 * 보호 슬롯(`ProtectedRoute` 하위 pathless 레이아웃 자식)에 가산 합성한다(Req 7.1).
 *
 * 휴지통은 별도 라우트가 아니다: 문서 메인 화면의 목록 패널이 모드 탭(활성 문서 ↔ 휴지통)으로
 * 휴지통을 표시하므로 전용 `/trash` 화면은 제거했다. 전용 화면은 어떤 네비게이션에서도 링크되지
 * 않는 고아 라우트였고, 같은 기능의 두 번째 구현이기도 했다.
 *
 * 경계: 프레임·가드·전역 401·Provider 마운트는 s16(`@/app/router`·`ProtectedRoute`·`main.tsx`)이
 * 단일 소유하며 여기서 재정의하지 않는다. 이 모듈은 `RouteModule[]`(경로·element)만 제공한다.
 * 툴바·휴지통 패널의 member+ 게이팅은 화면이 내부에서 self-gating 하므로 이 라우트 층은 별도
 * 게이트를 재구현하지 않는다.
 *
 * 보호 슬롯은 pathless 레이아웃 자식이라 라우트 정의에는 **상대 경로**("documents")를,
 * 네비게이션·테스트용 **절대 경로**는 이 파일의 상수(DOCUMENTS_PATH)를 쓴다
 * (하드코딩 산재 금지, s18 WORKSPACE_PATH idiom).
 *
 * Requirements:
 * - 7.1 문서 메인 화면을 s16 보호 프레임 하위 경로로 결선
 */

import { Navigate } from "react-router-dom";

import type { RouteModule } from "@/app/routeModule";

import { DocumentWorkspacePage } from "./pages/DocumentWorkspacePage";

// s19 소유 화면 경로(절대). 보호 슬롯 상대 경로("documents")와 짝을 이루며, 네비게이션·
// 테스트는 이 상수를 소비한다(단일 소스로 여기 정의; 하드코딩 산재 금지).
export const DOCUMENTS_PATH = "/documents";

/** 문서 메인 화면을 s16 보호 슬롯에 대응시키는 등록 결선 계약. */
export const documentRoutes: RouteModule[] = [
  {
    scope: "protected",
    routes: [
      // 보호 영역 홈(`/`)을 문서 메인으로 결선한다. canonical 경로는 `/documents`(editor 복귀·공유
      // 경로가 이를 전제)이며, `/`(로그인 기본 복귀·브랜드 홈)는 이 index 리다이렉트로 canonical 로
      // 수렴한다. s16 프레임의 built-in index 플레이스홀더는 이 feature index 등록으로 override 된다.
      { index: true, element: <Navigate to={DOCUMENTS_PATH} replace /> },
      { path: "documents", element: <DocumentWorkspacePage /> },
    ],
  },
];
