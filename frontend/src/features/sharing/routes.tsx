/**
 * 등록 결선: sharingRoutes (design.md §Registration; Req 6.1, 8.3).
 *
 * 게스트 공개 문서 페이지(`SharePage`)를 s16 **게스트 슬롯**(`scope: "guest"`)에 대응시키는
 * `RouteModule[]` 을 export 한다. s16 취합 함수(`collectRoutesByScope`/`composeRouter`)가
 * 이를 가드 없는 최상위 게스트 슬롯에 가산 합성한다(Req 8.3).
 *
 * 경계: 프레임·가드 부재(no-auth)·전역 401 예외·게스트 규약은 s16(`@/app/router`)이 단일
 * 소유하며 여기서 재정의하지 않는다. 이 모듈은 `RouteModule[]`(경로·element)만 제공한다.
 * 게스트 라우트는 pathless 레이아웃 자식이 아닌 **최상위**라 절대 경로(`ROUTES.share`)로
 * 등록한다(보호 슬롯의 상대 경로와 다름). 동일 path(`/share/:token`)를 등록하면 s16 의
 * built-in `/share/:token` 플레이스홀더를 치환한다(`createAppRoutes` path override).
 *
 * Requirements:
 * - 6.1 공개 문서 뷰를 게스트 경로로 결선
 * - 8.3 게스트 라우트를 s16 RouteModule 계약(게스트 슬롯·no-auth)에 결선(프레임 재구현 금지)
 */

import type { RouteModule } from "@/app/routeModule";
import { ROUTES } from "@/app/routes";

import { SharePage } from "./pages/SharePage";

/** 공개 문서 뷰를 s16 게스트 슬롯에 대응시키는 등록 결선 계약. */
export const sharingRoutes: RouteModule[] = [
  { scope: "guest", routes: [{ path: ROUTES.share, element: <SharePage /> }] },
];
