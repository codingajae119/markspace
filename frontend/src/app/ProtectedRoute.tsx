/**
 * 보호 라우트 가드 (design.md "app / router → Router & ProtectedRoute").
 *
 * 세션 부트스트랩 상태(`useSession().status`)에 따라 보호 영역 진입을 판정한다.
 * - `loading`  → 판정 유보. 로딩 인디케이터만 렌더하고 리다이렉트하지 않는다(AC 2.5).
 *   부트스트랩이 끝나기 전 잘못된 로그인 리다이렉트가 발생하지 않게 하는 핵심 규약이다.
 * - `unauthenticated` → 진입하려던 현재 경로(`pathname + search`)를 `returnTo` 로 보존한
 *   로그인 경로로 `replace` 리다이렉트한다(AC 2.2). `buildLoginPath`(`app/routes.ts`)가
 *   returnTo 인코딩 규약의 단일 소스다.
 * - `authenticated` → 인증 영역 공통 레이아웃(`AppLayout`) 안에 보호 자식 슬롯(`<Outlet />`)을
 *   렌더한다(AC 2.1, 7.2).
 *
 * 인증 영역 공통 레이아웃(`AppLayout`, task 5.2)은 task 7.1 조립에서 authenticated 분기에
 * 결선된다. 3.3 은 `AppLayout` 부재로 `<Outlet />` 만 노출하는 seam 을 남겼고, 7.1 이 그 분기를
 * `AppLayout` 로 감싸 자식이 공통 프레임 안에 렌더되게 완성한다(design: authenticated → AppLayout + children).
 *
 * Requirements: 2.1(보호 영역 자식 렌더), 2.2(returnTo 보존 리다이렉트), 2.5(loading 판정 유보).
 */

import { Navigate, Outlet, useLocation } from "react-router-dom";

import { AppLayout } from "@/app/AppLayout";
import { buildLoginPath } from "@/app/routes";
import { useSession } from "@/app/session/useSession";

/**
 * loading 상태 자립 폴백. task 5.1 의 공용 `Spinner` 는 별도이며, 이 task 가 독립적으로
 * 테스트 가능하도록 최소 인라인 로딩 인디케이터를 둔다. `role="status"` 로 접근성 표면을 노출한다.
 */
function LoadingIndicator() {
  return (
    <div role="status" aria-live="polite">
      Loading…
    </div>
  );
}

/**
 * 세션 가드 레이아웃 라우트 엘리먼트. `router.tsx` 의 보호 슬롯 element 로 사용되며 자식은
 * `<Outlet />` 로 렌더된다. 상태별 판정만 담당하고 화면 내용은 소유하지 않는다.
 */
export function ProtectedRoute() {
  const session = useSession();
  const location = useLocation();

  if (session.status === "loading") {
    return <LoadingIndicator />;
  }

  if (session.status === "unauthenticated") {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to={buildLoginPath(returnTo)} replace />;
  }

  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}
