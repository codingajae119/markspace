/**
 * 세션 컨텍스트 소비 훅 (design.md "app / session → SessionProvider & useSession").
 *
 * {@link SessionProvider} 가 노출한 `SessionState & { refresh }` 를 반환한다. status 로
 * loading·authenticated·unauthenticated 를 구분하고(AC 5.4), authenticated 일 때 `user`
 * (is_admin 포함, AC 5.6)·`settings` 를, 항상 `refresh()`(재부트스트랩, AC 5.5)를 제공한다.
 * 하위 feature(s17~)와 권한 게이팅 유틸은 이 훅으로만 세션을 소비하고 중복 조회하지 않는다.
 *
 * Requirements: 5.4(tri-state 소비), 5.5(refresh 진입점), 5.6(is_admin override 판정 소스).
 */

import { useContext } from "react";

import { SessionContext } from "@/app/session/SessionProvider";
import type { SessionContextValue } from "@/app/session/SessionProvider";

/**
 * 세션 컨텍스트를 읽는다. `SessionProvider` 밖에서 호출되면(컨텍스트 기본값 `null`)
 * 조립 실수를 조기에 드러내도록 명확한 오류를 던진다.
 */
export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return value;
}
