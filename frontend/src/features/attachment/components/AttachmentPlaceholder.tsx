/**
 * 안전 placeholder 컴포넌트 (design.md "features/attachment — AttachmentPlaceholder"
 * ~505-506·520, Requirements 2.1·5.2).
 *
 * 첨부의 업로드 진행·로드 실패·서빙 불가 상태를 깨진 이미지/죽은 링크가 아니라 안전한
 * 자리표시자로 표현한다.
 * - `uploading`: 공용 {@link Spinner}(role=status) 재사용으로 진행 상태를 노출한다(AC 2.1).
 * - `error`: 일시적 로드 실패를 일반적(generic) 문구로 안내한다(깨진 img/링크 없음).
 * - `unavailable`: 서빙 불가(404/403 관측 결과)를 일반적 문구로 안내하며, 상태 코드·경로·
 *   내부 원인 등 세부정보를 과다 노출하지 않는다(AC 5.2). 프론트는 첨부 상태를 재판정하지
 *   않고 관측 결과만 안전하게 표현한다.
 *
 * 비로딩 변형은 `role="img"` + `aria-label` 로 접근 가능한 시각 상태를 노출한다.
 */

import type { ReactElement } from "react";

import { Spinner } from "@/shared/ui";

export interface AttachmentPlaceholderProps {
  /** 표현할 상태 변형. */
  variant: "uploading" | "error" | "unavailable";
  /** 기본 문구/라벨을 덮어쓰는 선택 라벨. */
  label?: string;
}

/** 변형별 기본 문구. 내부 세부정보를 노출하지 않는 일반적 안내만 사용한다. */
const DEFAULT_LABELS: Record<AttachmentPlaceholderProps["variant"], string> = {
  uploading: "업로드 중",
  error: "첨부를 불러오지 못했습니다",
  unavailable: "이 첨부를 표시할 수 없습니다",
};

const BOX_CLASSES =
  "inline-flex items-center gap-2 rounded-md border border-slate-200 " +
  "bg-slate-50 px-3 py-2 text-sm text-slate-500";

/** 첨부 상태(업로드/오류/표시 불가)를 안전하게 표현하는 자리표시자. */
export function AttachmentPlaceholder({
  variant,
  label,
}: AttachmentPlaceholderProps): ReactElement {
  const text = label ?? DEFAULT_LABELS[variant];

  if (variant === "uploading") {
    return (
      <span className={BOX_CLASSES}>
        <Spinner label={text} />
        <span aria-hidden="true">{text}</span>
      </span>
    );
  }

  return (
    <span role="img" aria-label={text} className={BOX_CLASSES}>
      <span aria-hidden="true">{text}</span>
    </span>
  );
}
