/**
 * 로그아웃 버튼 컴포넌트 (design.md "features/auth/components & pages → LogoutButton").
 *
 * `useLogout().submit` 을 트리거하는 자족적 단일 버튼이다. 배치 위치(레이아웃/헤더)는 소비 화면이
 * 결정하므로 레이아웃 가정을 두지 않는다. 진행 중(`submitting`)에는 버튼을 비활성화하여 중복 실행을
 * 방지한다(Req 3.4). 선택적 `className` 은 하위 s16 `Button` 으로 그대로 전달한다.
 *
 * 계약 경계(모두 s16 소비): 프리미티브 `Button` 은 `@/shared/ui` 배럴에서만, 로그아웃 useCase 는 같은
 * feature 의 `useLogout` 에서만 소비한다(다른 feature import·직접 apiClient/useSession 금지).
 *
 * Requirements:
 * - 3.1 인증 영역에서 접근 가능한 로그아웃 액션(버튼) 제공
 * - 3.4 진행 중 로그아웃 컨트롤 비활성(중복 실행 방지)
 */

import type { ReactElement } from "react";

import { Button } from "@/shared/ui";
import { useLogout } from "../hooks/useLogout";

/** LogoutButton 이 받는 선택 속성(하위 Button 으로 전달할 className). */
export interface LogoutButtonProps {
  /** 하위 s16 Button 으로 전달할 클래스(선택). */
  className?: string;
}

/** useLogout().submit 을 트리거하고 진행 중 비활성화하는 자족적 로그아웃 버튼. */
export function LogoutButton({ className }: LogoutButtonProps = {}): ReactElement {
  const { submit, submitting } = useLogout();

  return (
    <Button
      type="button"
      className={className}
      disabled={submitting}
      onClick={() => void submit()}
    >
      로그아웃
    </Button>
  );
}
