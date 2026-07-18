/**
 * Provider 합성 슬롯 (design.md "app / route + provider registration → RouteRegistry &
 * ProviderComposition").
 *
 * feature 가 자체 컨텍스트를 도입하는 Provider 를 앱 조립부(task 7.1 `main.tsx`)에 **수기 편집
 * 없이** 끼울 수 있는 명시적 합성 슬롯이다(AC 10.3). 배열 순서대로 하위 Provider 를 감싸며,
 * 앞 원소가 더 바깥(outermost)에 온다.
 *
 * ## 안정 소비 계약 (AC 10.4)
 * {@link ProviderComponent} 형태와 {@link composeProviders} 시그니처는 s17~s22 가 바인딩하는
 * 안정 계약이며, 변경 시 하위 spec **재검증 트리거**다. 라우트 등록은 `routeModule.ts` 의
 * `composeRouter`(AC 10.1/10.2)가 짝으로 소유한다.
 *
 * Requirements: 10.3(Provider 합성 슬롯), 10.4(계약 문서화).
 */

import type { ReactElement, ReactNode } from "react";

/**
 * 합성 슬롯에 등록하는 Provider 컴포넌트. `children` 을 감싸 컨텍스트를 도입한다.
 * (React 19 JSX 타입에 맞춰 `ReactElement` 반환 — `any` 미사용.)
 */
export type ProviderComponent = (props: { children: ReactNode }) => ReactElement;

/**
 * Provider 배열을 순서대로 `children` 주위에 중첩한다(AC 10.3).
 *
 * `composeProviders([A, B], children)` → `<A><B>{children}</B></A>`(A 최외곽). 오른쪽부터
 * 접어(`reduceRight`) 안쪽 Provider 가 먼저 children 을 감싸도록 한다. 빈 배열이면 합성 없이
 * `children` 을 그대로 렌더한다.
 */
export function composeProviders(providers: ProviderComponent[], children: ReactNode): ReactElement {
  return providers.reduceRight<ReactElement>(
    (acc, Provider) => <Provider>{acc}</Provider>,
    <>{children}</>,
  );
}
