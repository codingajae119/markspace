/**
 * 401 인터셉터 → 실제 라우터 결선 헬퍼 (task 7.1 조립부).
 *
 * `shared/` 레이어의 전역 401 인터셉터는 라우팅(`src/app/*`)을 정적으로 import 하지 않고
 * NavSeam(`shared/api/navigation.ts`, task 2.2)의 런타임 주입 지점만 안다. 앱 부팅 시점에
 * 라우터가 준비되면 이 헬퍼가 그 seam 을 채워 401 리다이렉트가 실제 라우팅으로 이어지게 한다:
 *
 * - {@link setNavigator} ← 라우터의 `navigate` — 401 시 seam 이 요청하는 이동을 데이터 라우터가
 *   실제로 수행한다(AC 4.1/4.2). NavSeam `Navigate` 시그니처(`(to, options?: {replace?}) => void`)
 *   로 감싸 라우터 navigate 를 어댑트한다(반환 Promise 는 무시 — seam 은 void 계약).
 * - {@link setLoginPathBuilder} ← 정규 {@link buildLoginPath}(`app/routes.ts`) — 로그인 경로·returnTo
 *   규약을 런타임 단일 소스로 수렴시켜 seam 의 자립 기본 빌더를 대체한다(3.1 canonical, AC 10.1).
 *
 * `main.tsx` 조립부가 라우터 생성 직후 이 헬퍼를 1회 호출한다. 데이터 라우터를 full-render 하지
 * 않고도 결선을 단위 검증할 수 있도록 라우터를 최소 표면({@link NavigableRouter})으로만 받는다
 * (jsdom/undici AbortSignal realm 비호환 회피 — router.tsx 주석 참조).
 *
 * Requirements: 4.1(현재 경로 returnTo 보존 후 로그인 리다이렉트), 4.2(401 처리 단일 지점 결선),
 * 10.1(로그인 경로 규약 단일 소스 수렴).
 */

import { buildLoginPath } from "@/app/routes";
import { setLoginPathBuilder, setNavigator } from "@/shared/api/navigation";
import type { Navigate } from "@/shared/api/navigation";

/**
 * 결선에 필요한 라우터의 최소 표면. `createBrowserRouter`(=`composeRouter`) 결과의 `navigate` 가
 * 이 형태에 부합하므로, 실제 데이터 라우터와 테스트용 MOCK 라우터를 동일하게 수용한다.
 */
export interface NavigableRouter {
  navigate: Navigate;
}

/**
 * NavSeam 에 라우터 네비게이션과 정규 로그인 경로 빌더를 주입한다(앱 부팅 시 1회).
 * 호출 이후 전역 401 인터셉터의 {@link redirectToLogin} 이 no-op 대신 실제 라우터 이동을 수행한다.
 */
export function installNavigation(router: NavigableRouter): void {
  setNavigator((to, options) => {
    router.navigate(to, options);
  });
  setLoginPathBuilder(buildLoginPath);
}
