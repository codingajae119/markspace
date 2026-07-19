/**
 * TrashBundleItem — 휴지통 묶음 한 행(루트 요약·구성원 목록·복구·완전삭제)
 * (design.md §화면 컴포넌트 TrashList/BundleItem ~602-603).
 *
 * 서버가 내려준 `TrashBundleRead` 하나를 표시한다. 루트 요약(root_title·member_count·
 * expires_at=보관 만료 예정, 참고로 trashed_at)과 묶음 구성원 목록(members: id·parent_id·
 * title)을 렌더해 사용자가 묶음 계층을 파악하도록 돕는다(Req 8.2). "복구" 버튼은
 * `onRestore(bundle_id)`, "완전삭제" 버튼은 비가역 `ConfirmDialog`(irreversible=true,
 * 되돌릴 수 없음)를 연 뒤 확인 시에만 `onPurge(bundle_id)` 를 발화하고 취소 시에는 닫기만
 * 한다 — 이 비가역-확인 게이트는 백엔드 완전삭제 계약(purge 복구 불가)과 정합을 이룬다(Req 8.4).
 *
 * 이 컴포넌트는 복구 위치·묶음·보존 규칙을 판단하지 않는다(그 정책은 훅 소유, Req 8.7).
 * 오직 서버 데이터 표시 + 콜백 발화만 담당한다. 형제 feature 는 import 하지 않는다.
 *
 * Requirements: 8.2(묶음 계층 표시), 8.4(비가역 완전삭제 ConfirmDialog 확인).
 */

import { useState } from "react";
import type { ReactElement } from "react";

import { Button } from "@/shared/ui";

import type { TrashBundleRead } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";

export interface TrashBundleItemProps {
  /** 표시할 휴지통 묶음(서버 응답). */
  bundle: TrashBundleRead;
  /** 복구 콜백(정책·위치 판단은 호출부/훅 소유). */
  onRestore(bundleId: number): void;
  /** 완전삭제 콜백(비가역 확인 이후에만 호출). */
  onPurge(bundleId: number): void;
}

/** ISO 문자열을 사람이 읽을 수 있는 로컬 시각으로 방어적 변환(빈 문자열/파싱 실패 시 원문). */
function formatDateTime(iso: string): string {
  if (!iso) {
    return "";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString();
}

/** 휴지통 묶음 한 행. 루트 요약·구성원 목록을 표시하고 복구/완전삭제 콜백을 발화한다. */
export function TrashBundleItem({
  bundle,
  onRestore,
  onPurge,
}: TrashBundleItemProps): ReactElement {
  const [purgeOpen, setPurgeOpen] = useState(false);

  const expiresLabel = formatDateTime(bundle.expires_at);
  const trashedLabel = formatDateTime(bundle.trashed_at);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-slate-900">
            {bundle.root_title}
          </h3>
          <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
            <div className="flex gap-1">
              <dt>구성원</dt>
              <dd className="font-medium text-slate-800">
                {bundle.member_count}개
              </dd>
            </div>
            <div className="flex gap-1">
              <dt>보관 만료 예정</dt>
              <dd className="font-medium text-slate-800">{expiresLabel}</dd>
            </div>
            {trashedLabel && (
              <div className="flex gap-1">
                <dt>삭제 일시</dt>
                <dd className="text-slate-800">{trashedLabel}</dd>
              </div>
            )}
          </dl>
        </div>

        <div className="flex shrink-0 gap-2">
          <Button
            variant="secondary"
            onClick={() => onRestore(bundle.bundle_id)}
          >
            복구
          </Button>
          <Button variant="secondary" onClick={() => setPurgeOpen(true)}>
            완전삭제
          </Button>
        </div>
      </div>

      <ul className="mt-3 space-y-1 text-sm text-slate-700">
        {bundle.members.map((member) => (
          <li
            key={member.id}
            className={member.parent_id === null ? "font-medium" : "pl-4"}
          >
            {member.parent_id !== null && (
              <span aria-hidden="true" className="text-slate-400">
                └{" "}
              </span>
            )}
            <span>{member.title}</span>
          </li>
        ))}
      </ul>

      <ConfirmDialog
        open={purgeOpen}
        irreversible
        title="완전삭제"
        message={`"${bundle.root_title}" 묶음을 완전히 삭제합니다.`}
        confirmLabel="완전삭제"
        cancelLabel="취소"
        onConfirm={() => {
          onPurge(bundle.bundle_id);
          setPurgeOpen(false);
        }}
        onCancel={() => setPurgeOpen(false)}
      />
    </div>
  );
}
