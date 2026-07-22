/**
 * PanelModeTabs — 문서 목록 패널 상단의 모드 세그먼트 컨트롤(활성 문서 ↔ 휴지통).
 *
 * 2-모드 전환을 단일 토글 버튼으로 만들면 라벨이 *현재 상태*인지 *누르면 갈 곳*인지 모호해진다
 * (툴바의 "문서 목록 숨기기/보기" 처럼 상태 전환 라벨로 푸는 방식은 개폐에는 맞지만 모드 전환에는
 * 부적합하다). 두 선택지를 나란히 두고 `aria-selected` 로 현재 모드를 표시하면 라벨 해석 없이
 * 상태가 보인다. 그래서 tablist 시맨틱을 쓴다.
 *
 * 또한 이 탭 라벨("휴지통")은 패널 배경색(회색)과 **중복된** 모드 신호다. 색상 단독 신호는
 * 색각 이상·고대비 모드에서 소실되므로(WCAG 1.4.1) 텍스트 신호를 반드시 함께 둔다.
 *
 * 노출 게이팅은 상위가 소유한다: 휴지통은 member+ 전용(서버 권한과 동일 기준)이라 뷰어에게는
 * 이 컴포넌트 자체를 렌더하지 않는다 — 여기서 role 을 다시 비교하지 않는다.
 */

import type { ReactElement } from "react";

/** 문서 목록 패널이 표시하는 대상. */
export type PanelMode = "active" | "trash";

export interface PanelModeTabsProps {
  /** 현재 모드. */
  mode: PanelMode;
  /** 모드 변경 seam. */
  onChange(mode: PanelMode): void;
  /** 휴지통 묶음 개수(있으면 탭에 배지로 표시). */
  trashCount?: number | null;
}

const TAB_BASE =
  "flex-1 rounded px-2 py-1 text-sm font-medium transition-colors " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400";

/** 활성 문서/휴지통 모드를 전환하는 세그먼트 컨트롤. */
export function PanelModeTabs({
  mode,
  onChange,
  trashCount,
}: PanelModeTabsProps): ReactElement {
  const tabClass = (target: PanelMode): string =>
    mode === target
      ? `${TAB_BASE} bg-white text-slate-900 shadow-sm`
      : `${TAB_BASE} text-slate-600 hover:text-slate-900`;

  return (
    <div
      role="tablist"
      aria-label="문서 목록 표시 대상"
      className="mb-2 flex gap-1 rounded-md bg-slate-200 p-1"
    >
      <button
        type="button"
        role="tab"
        aria-selected={mode === "active"}
        aria-controls="document-tree-panel"
        onClick={() => onChange("active")}
        className={tabClass("active")}
      >
        활성 문서
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === "trash"}
        aria-controls="document-tree-panel"
        onClick={() => onChange("trash")}
        className={tabClass("trash")}
      >
        휴지통
        {typeof trashCount === "number" && trashCount > 0 ? (
          <span className="ml-1 text-xs text-slate-500">{trashCount}</span>
        ) : null}
      </button>
    </div>
  );
}
