/**
 * 로딩 인디케이터 프리미티브 (design.md "shared / ui → UiPrimitives", AC 7.1).
 *
 * `role="status"` 로 라이브 리전을 노출하고 시각적으로 숨겨진 라벨을 함께 제공하여
 * 스크린 리더가 로딩 상태를 읽을 수 있게 한다. 회전 애니메이션은 Tailwind `animate-spin`.
 *
 * Requirements: 7.1(로딩 인디케이터), 7.5(Tailwind 4).
 */

import type { ReactElement } from "react";

export interface SpinnerProps {
  /** 접근 가능한 로딩 라벨(기본 "로딩 중"). */
  label?: string;
  /** 추가 클래스 병합. */
  className?: string;
}

const SIZE_CLASSES =
  "inline-block h-5 w-5 animate-spin rounded-full border-2 " +
  "border-slate-300 border-t-slate-700";

/** 접근 가능한 스피너. `role="status"` + 시각적으로 숨긴 라벨. */
export function Spinner({ label = "로딩 중", className }: SpinnerProps): ReactElement {
  const classes = [SIZE_CLASSES, className].filter(Boolean).join(" ");

  return (
    <span role="status" aria-label={label} className="inline-flex items-center">
      <span className={classes} aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}
