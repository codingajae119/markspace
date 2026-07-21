/**
 * RoleSelect — owner/editor/viewer 세 값(`MemberRole`)만 방출하는 role 선택 프리미티브
 * (design.md "components → RoleSelect", Req 3.4).
 *
 * 옵션 집합을 `MemberRole` 리터럴 3개로 **폐쇄**해 그 외 값을 구조적으로 방출 불가능하게 한다:
 * `onChange` 는 항상 세 값 중 하나만 전달하며 호출부는 임의 문자열을 받을 수 없다. 순수 프리미티브로
 * 정책(누가 어떤 role 을 줄 수 있는지)은 담지 않고 상위 패널(4.2)이 게이팅한다.
 *
 * s16 시각 언어(Button 등)와 정합한 Tailwind 유틸을 부여하되 새 shared 프리미티브를 추가하지 않고
 * 스타일드 `<select>` 로 국소 구현한다(design.md: RoleSelect 는 plain styled select). `className`
 * 은 기본 스타일 뒤에 병합되어 호출부 오버라이드가 가능하다.
 *
 * Requirements: 3.4(role 선택 UI 가 owner/editor/viewer 세 값만 허용·전송).
 */

import type { ReactElement } from "react";

import type { MemberRole } from "../api/types";

/** 방출 가능한 role 목록 — 이 3값으로 옵션 집합을 폐쇄한다(Req 3.4). */
const ROLE_OPTIONS: readonly { value: MemberRole; label: string }[] = [
  { value: "owner", label: "owner" },
  { value: "editor", label: "editor" },
  { value: "viewer", label: "viewer" },
];

export interface RoleSelectProps {
  /** 현재 선택된 role. */
  value: MemberRole;
  /** 선택 변경 시 새 `MemberRole`(3값 중 하나)을 전달한다. */
  onChange: (role: MemberRole) => void;
  /** select 요소 id(label 연결·외부 참조용, 선택). */
  id?: string;
  /** 연결할 라벨 텍스트(제공 시 `<label htmlFor>` 로 접근성 연결, 선택). */
  label?: string;
  /**
   * 라벨을 접근성 연결용으로만 두고 시각적으로 숨긴다(`sr-only`, 선택). 상위가 이미 대상을
   * 시각적으로 명시(예: 멤버 행의 "{id} {name}")해 라벨 텍스트가 화면상 중복될 때 사용한다.
   */
  srOnlyLabel?: boolean;
  /** 비활성 여부(진행 중·미충족 게이팅 시, 선택). */
  disabled?: boolean;
}

const SELECT_CLASSES =
  "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

/** owner/editor/viewer 3값만 방출하는 스타일드 select. `onChange` 는 항상 `MemberRole` 을 전달한다. */
export function RoleSelect({ value, onChange, id, label, srOnlyLabel, disabled }: RoleSelectProps): ReactElement {
  return (
    <>
      {label !== undefined ? (
        <label
          htmlFor={id}
          className={srOnlyLabel ? "sr-only" : "mr-2 text-sm font-medium text-slate-700"}
        >
          {label}
        </label>
      ) : null}
      <select
        id={id}
        value={value}
        disabled={disabled}
        // 옵션이 3값으로 폐쇄되어 있으므로 event.target.value 는 항상 유효한 MemberRole 이다.
        onChange={(event) => onChange(event.target.value as MemberRole)}
        className={SELECT_CLASSES}
      >
        {ROLE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </>
  );
}
