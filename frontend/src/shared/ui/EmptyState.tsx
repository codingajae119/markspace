/**
 * 빈/오류 상태 표시 프리미티브 (design.md "shared / ui → UiPrimitives", AC 7.1).
 *
 * 목록이 비었거나 로드 실패 등 "표시할 것이 없는" 표면을 일관되게 렌더한다. `title` 은
 * 필수, `message` 는 선택, `children`(예: 액션 버튼) 은 선택 슬롯이다. 정책은 없고 표시만 한다.
 *
 * Requirements: 7.1(빈/오류 상태 표시), 7.5(Tailwind 4).
 */

import type { ReactElement, ReactNode } from "react";

export interface EmptyStateProps {
  /** 상태 제목(필수). */
  title: string;
  /** 부연 설명(선택). */
  message?: string;
  /** 액션 등 하위 슬롯(선택). */
  children?: ReactNode;
}

/** 중앙 정렬된 빈/오류 상태 카드. */
export function EmptyState({ title, message, children }: EmptyStateProps): ReactElement {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center text-slate-600">
      <p className="text-base font-medium text-slate-800">{title}</p>
      {message ? <p className="text-sm text-slate-500">{message}</p> : null}
      {children ? <div className="mt-2">{children}</div> : null}
    </div>
  );
}
