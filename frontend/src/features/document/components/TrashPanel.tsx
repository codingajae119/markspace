/**
 * TrashPanel — 문서 목록 패널의 "휴지통" 모드 본문(좁은 사이드 패널용 compact 목록).
 *
 * 문서 트리와 같은 자리(288px `<aside>`)에 들어가는 축약 표현이다 — 휴지통은 전용 화면이 아니라
 * 문서 목록 패널의 한 모드이므로, 좁은 폭에서 읽히도록 카드가 아닌 조밀한 목록으로 그린다.
 * 이 컴포넌트는 `useTrash` 를 직접 호출하지 않고 상위 페이지가 주입한 `trash` 결과 객체만 소비한다
 * (선택·복구·완전삭제 seam 을 툴바와 함께 상위에서 배선해야 하므로).
 *
 * **묶음 단위 선택 모델(2단 선택)**: 휴지통의 복원 단위는 문서가 아니라 묶음(bundle)이다
 * (`restoreBundle(bundleId)`). 반면 오른쪽 뷰어는 "지금 클릭한 그 문서"의 본문을 보여줘야 한다.
 * 두 요구를 동시에 만족시키기 위해 행 클릭은 `onSelect(bundleId, docId)` 로 **둘 다** 올린다:
 * - `docId` → 뷰어가 표시할 문서(백엔드 `GET /documents/{id}` 는 상태로 필터하지 않아 삭제 문서도 조회된다)
 * - `bundleId` → 툴바의 복구·완전삭제 대상
 * 하위 문서를 클릭해도 **묶음 전체가 함께 강조**되므로, 복구가 묶음 단위라는 사실이 버튼 위치가
 * 아니라 선택 피드백으로 전달된다. 그래서 행에는 복구 버튼을 두지 않는다(좁은 폭 보호 + 오해 방지).
 *
 * 복원 위치·묶음 구성·보존 규칙은 전혀 판단하지 않는다(그 정책은 훅·백엔드 소유). 만료 표시는
 * 서버가 내려준 `expires_at` 을 좁은 폭에 맞춰 잔여 일수(D-n)로 축약할 뿐이다.
 */

import type { ReactElement } from "react";

import { ErrorMessage, Spinner } from "@/shared/ui";

import type { UseTrashResult } from "../hooks/useTrash";

export interface TrashPanelProps {
  /** 휴지통 상태+액션(= useTrash() 반환; 상위 페이지가 호출·주입). */
  trash: UseTrashResult;
  /** 현재 선택된 묶음 id(묶음 전체 강조 대상). 없으면 null. */
  selectedBundleId: number | null;
  /** 현재 선택된 문서 id(뷰어 표시 대상, 행 단독 강조). 없으면 null. */
  selectedDocId: number | null;
  /** 행 선택 seam — 묶음 id 와 문서 id 를 함께 올린다. */
  onSelect(bundleId: number, docId: number): void;
}

/**
 * 보존 만료까지의 잔여 일수를 좁은 폭용으로 축약한다("D-14"/"오늘 만료"/"만료됨").
 * 파싱 실패 시 빈 문자열을 반환해 메타 줄에서 조용히 생략된다(방어적).
 */
function formatExpiry(iso: string): string {
  if (!iso) {
    return "";
  }
  const expires = new Date(iso);
  if (Number.isNaN(expires.getTime())) {
    return "";
  }
  const remainingMs = expires.getTime() - Date.now();
  const days = Math.ceil(remainingMs / (24 * 60 * 60 * 1000));
  if (days < 0) {
    return "만료됨";
  }
  if (days === 0) {
    return "오늘 만료";
  }
  return `D-${days}`;
}

/** 휴지통 묶음 목록(compact). 행 클릭 시 묶음+문서를 함께 선택한다. */
export function TrashPanel({
  trash,
  selectedBundleId,
  selectedDocId,
  onSelect,
}: TrashPanelProps): ReactElement {
  if (trash.status === "loading") {
    return (
      <div className="py-4">
        <Spinner label="휴지통 불러오는 중" />
      </div>
    );
  }

  if (trash.status === "error") {
    return <ErrorMessage error={trash.error} />;
  }

  if (trash.bundles.length === 0) {
    // 좁은 패널용 축약 빈 상태(전체 폭 기준 EmptyState 대신).
    return (
      <p className="px-2 py-6 text-center text-sm text-slate-500">
        휴지통이 비어 있습니다.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* 변이 후 남은 오류(예: 404)는 목록과 함께 표면화한다. */}
      <ErrorMessage error={trash.error} />

      <ul className="flex flex-col gap-2">
        {trash.bundles.map((bundle) => {
          const bundleSelected = bundle.bundle_id === selectedBundleId;
          const expiryLabel = formatExpiry(bundle.expires_at);
          return (
            <li
              key={bundle.bundle_id}
              // 묶음 전체 강조: 하위 문서를 골라도 묶음이 통째로 복구된다는 사실을 시각화한다.
              className={
                "rounded-md border bg-white p-2 " +
                (bundleSelected
                  ? "border-slate-900 ring-2 ring-slate-900"
                  : "border-slate-200")
              }
            >
              <p className="flex items-center justify-between gap-2 px-1 text-xs text-slate-500">
                <span>{bundle.member_count}개 문서</span>
                {expiryLabel ? (
                  <span title={`보관 만료 예정: ${bundle.expires_at}`}>
                    {expiryLabel}
                  </span>
                ) : null}
              </p>

              <ul className="mt-1 flex flex-col">
                {bundle.members.map((member) => {
                  const isRoot = member.parent_id === null;
                  const docSelected = member.id === selectedDocId;
                  return (
                    <li key={member.id}>
                      <button
                        type="button"
                        aria-pressed={docSelected}
                        onClick={() => onSelect(bundle.bundle_id, member.id)}
                        className={
                          "flex w-full items-center gap-1 truncate rounded px-1 py-1 text-left text-sm " +
                          "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
                          (isRoot ? "font-medium text-slate-900 " : "pl-4 text-slate-700 ") +
                          (docSelected ? "bg-slate-200" : "hover:bg-slate-100")
                        }
                      >
                        {!isRoot && (
                          <span aria-hidden="true" className="text-slate-400">
                            └
                          </span>
                        )}
                        <span className="truncate">{member.title}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
