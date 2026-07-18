/**
 * 공용 버튼 프리미티브 (design.md "shared / ui → UiPrimitives", AC 7.1·7.5).
 *
 * 표준 `<button>` 속성을 그대로 확장하고(`React.ButtonHTMLAttributes`), 라이트 기준
 * 일관된 시각 언어를 Tailwind 4 유틸로 부여한다. 정책·동작은 담지 않는 순수 프리미티브로,
 * 호출부의 `className` 은 기본 스타일 뒤에 병합되어 개별 오버라이드가 가능하다.
 *
 * Requirements: 7.1(최소 프리미티브 세트), 7.5(Tailwind 4·일관 시각 언어).
 */

import type { ButtonHTMLAttributes, ReactElement } from "react";

/** 경량 변형 — 시각적 강조 수준만 구분한다(정책 없음). */
export type ButtonVariant = "primary" | "secondary";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 시각 강조 수준(기본 `primary`). */
  variant?: ButtonVariant;
}

const BASE_CLASSES =
  "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm " +
  "font-medium transition-colors focus:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-slate-900 text-white hover:bg-slate-700 focus-visible:ring-slate-500",
  secondary:
    "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 " +
    "focus-visible:ring-slate-400",
};

/** 표준 button 속성을 전달하는 Tailwind 스타일 버튼. `type` 기본값은 `button`. */
export function Button({
  variant = "primary",
  type = "button",
  className,
  children,
  ...rest
}: ButtonProps): ReactElement {
  const classes = [BASE_CLASSES, VARIANT_CLASSES[variant], className]
    .filter(Boolean)
    .join(" ");

  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  );
}
