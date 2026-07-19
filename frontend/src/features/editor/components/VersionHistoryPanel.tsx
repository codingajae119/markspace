/**
 * 버전 이력 패널 (design.md "features/editor → 화면 컴포넌트 → VersionHistoryPanel").
 *
 * `useVersionHistory(documentId, currentVersionId)` 가 노출하는 버전 메타데이터를 **읽기 전용**
 * 목록으로 렌더한다. 각 행은 저장자(`created_by`)·저장 시각(`created_at`)만 표시하며, 백엔드가
 * 최신 저장 순으로 반환한 순서를 그대로 유지한다(Req 6.1). `current_version_id` 와 일치하는 행은
 * "현재" 배지로 구분 표시한다(Req 6.5). 아직 로드하지 않은 페이지가 남아 있으면(누적 length <
 * total) "더 보기" 로 `loadMore` 를 호출해 이어받는다(Req 6.2).
 *
 * 계약 제약(Req 6.3·6.4): `DocumentVersionRead` 에는 본문(content) 필드가 없고 과거 버전 **본문**
 * 조회·rollback 엔드포인트가 존재하지 않으므로, 이 패널은 본문을 표시하지 않으며 rollback·복원·
 * 되돌리기 등 상태 변경 UI 를 일절 렌더하지 않는다(읽기 전용 메타 목록만).
 *
 * 상태: loading → {@link Spinner}, ready+0건 → {@link EmptyState}, error → {@link ErrorMessage}
 * (정규화된 `ApiError` 그대로 표면화, Req 6.6).
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6.
 */

import type { ReactElement } from "react";
import { useCallback } from "react";

import { Spinner, EmptyState, ErrorMessage, Button } from "@/shared/ui";
import { useVersionHistory } from "../hooks/useVersionHistory";
import type { DocumentVersionRead } from "../types";

export interface VersionHistoryPanelProps {
  /** 이력을 조회할 문서 id. */
  documentId: number;
  /** 현재 버전 식별자(문서 상세 `DocumentRead.current_version_id`). 구분 표시용, 없으면 null. */
  currentVersionId: number | null;
}

/** 저장 시각 ISO 를 사람이 읽을 수 있는 로컬 문자열로 포맷한다(dateTime 은 원본 ISO 유지). */
function formatCreatedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString();
}

/** 단일 버전 행(읽기 전용 메타). 현재 버전이면 "현재" 배지를 붙인다(Req 6.5). */
function VersionRow({
  version,
  isCurrent,
}: {
  version: DocumentVersionRead;
  isCurrent: boolean;
}): ReactElement {
  return (
    <li
      data-testid={`version-row-${version.id}`}
      className="flex items-center justify-between gap-3 px-4 py-3 text-sm"
    >
      <div className="flex flex-col">
        <span className="text-slate-700">
          저장자{" "}
          <span data-testid="version-created-by" className="font-medium">
            #{version.created_by}
          </span>
        </span>
        <time
          data-testid="version-created-at"
          dateTime={version.created_at}
          className="text-xs text-slate-500"
        >
          {formatCreatedAt(version.created_at)}
        </time>
      </div>
      {isCurrent ? (
        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
          현재
        </span>
      ) : null}
    </li>
  );
}

/** 버전 이력을 읽기 전용 메타 목록으로 표시하고, 남은 페이지가 있으면 "더 보기" 로 이어받는다. */
export function VersionHistoryPanel({
  documentId,
  currentVersionId,
}: VersionHistoryPanelProps): ReactElement {
  const { status, versions, total, error, loadMore } = useVersionHistory(
    documentId,
    currentVersionId,
  );

  const handleLoadMore = useCallback(() => {
    void loadMore();
  }, [loadMore]);

  if (status === "loading") {
    return (
      <section aria-label="버전 이력" className="flex justify-center py-8">
        <Spinner label="버전 이력을 불러오는 중" />
      </section>
    );
  }

  if (status === "error") {
    return (
      <section aria-label="버전 이력">
        <ErrorMessage error={error} />
      </section>
    );
  }

  // status === "ready"
  if (versions.length === 0) {
    return (
      <section aria-label="버전 이력">
        <EmptyState title="저장된 버전이 없습니다" />
      </section>
    );
  }

  const hasMore = versions.length < total;

  return (
    <section aria-label="버전 이력" className="space-y-3">
      <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
        {versions.map((version) => (
          <VersionRow
            key={version.id}
            version={version}
            isCurrent={
              currentVersionId !== null && version.id === currentVersionId
            }
          />
        ))}
      </ul>
      {hasMore ? (
        <Button type="button" variant="secondary" onClick={handleLoadMore}>
          더 보기
        </Button>
      ) : null}
    </section>
  );
}
