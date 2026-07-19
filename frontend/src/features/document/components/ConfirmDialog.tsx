/**
 * ConfirmDialog — 파괴적 조작 확인 모달 (design.md "features/document → ConfirmDialog",
 * design §화면 컴포넌트 ~600-601).
 *
 * 삭제(→휴지통)와 비가역 완전삭제(purge)를 확인받는 재사용 다이얼로그다. `open` 이
 * false 면 아무것도 렌더하지 않고(null), true 면 제목·본문·확인/취소 버튼을 접근 가능한
 * 모달(dialog / alertdialog, aria-modal)로 렌더한다. `irreversible` 이 true 면
 * "되돌릴 수 없습니다" 경고를 별도 요소로 강조 표시하는데, 이는 백엔드 OpenAPI 의 완전삭제
 * 비가역 계약(purge 는 복구 불가)과 정합을 이룬다. 확인은 `onConfirm`, 취소는 `onCancel`
 * 콜백으로 위임하며(정책은 호출부 소유), s16 공용 `Button` 프리미티브를 재사용한다.
 *
 * Requirements: 5.1(삭제 확인), 8.4(비가역 완전삭제 확인·비가역 계약 정합).
 */

import { useId } from "react";
import type { ReactElement } from "react";

import { Button } from "@/shared/ui";

export interface ConfirmDialogProps {
  /** true 일 때만 모달을 렌더한다(false → null). */
  open: boolean;
  /** 다이얼로그 제목(접근 이름으로 사용). */
  title: string;
  /** 조작 설명 본문. */
  message: string;
  /** 확인 버튼 라벨(기본 "확인"). */
  confirmLabel?: string;
  /** 취소 버튼 라벨(기본 "취소"). */
  cancelLabel?: string;
  /** true 면 "되돌릴 수 없습니다" 비가역 경고를 강조 표시(완전삭제 변형). */
  irreversible?: boolean;
  /** 확인 콜백(파괴적 조작 실행은 호출부가 소유). */
  onConfirm(): void;
  /** 취소 콜백(모달 닫기 등은 호출부가 소유). */
  onCancel(): void;
}

/** 파괴적 조작 확인 모달. irreversible 변형은 비가역 경고를 추가로 표시한다. */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "확인",
  cancelLabel = "취소",
  irreversible = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): ReactElement | null {
  const titleId = useId();

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          onCancel();
        }
      }}
    >
      <div
        role={irreversible ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
      >
        <h2 id={titleId} className="text-lg font-semibold text-slate-900">
          {title}
        </h2>

        <p className="mt-2 text-sm text-slate-600">{message}</p>

        {irreversible && (
          <p
            data-testid="irreversible-warning"
            role="alert"
            className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm font-medium text-red-700"
          >
            완전삭제는 되돌릴 수 없습니다.
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            className={
              irreversible
                ? "bg-red-600 hover:bg-red-500 focus-visible:ring-red-400"
                : undefined
            }
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
