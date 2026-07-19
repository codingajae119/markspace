/**
 * 버전 이력 로드 훅 (design.md "features/editor/hooks → useVersionHistory").
 *
 * 마운트 시 `listVersions(id, limit, offset=0)` 로 `Page<DocumentVersionRead>` 를 로드하고
 * (status=ready·versions·total), `loadMore` 로 offset=누적 length 를 이어받아 **append**
 * 하며(replace 아님, 페이지네이션 continuation), `reload` 로 offset 0 부터 재로드한다.
 * `currentVersionId`(문서 상세 `DocumentRead.current_version_id`)는 상위에서 주입받아 그대로
 * 노출만 하며(현재 버전 구분은 소비 UI 담당), 이 훅은 문서 상세를 스스로 조회하지 않는다.
 *
 * 계약 제약(Req 6):
 * - `DocumentVersionRead` 에는 본문(content) 필드가 없고 과거 버전 **본문** 조회·rollback
 *   엔드포인트가 존재하지 않으므로, 이 훅은 오직 `listVersions` 만 소비한다(content/rollback
 *   호출 금지). 저장자·저장 시각 메타데이터 목록만 읽기 전용으로 파생한다.
 * - 로딩/오류/빈 상태를 노출한다. 조회 실패(403/404)는 정규화된 {@link ApiError} 로 표면화한다.
 *
 * 누적 length(offset 소스)·in-flight 가드·total 은 **ref** 로 보관한다 — `loadMore` 는
 * 최신 누적 값을 읽어야 하고 stale 클로저에 의존하면 중복 append·잘못된 offset 을 유발할 수
 * 있기 때문이다. 언마운트 후에는 상태 갱신을 억제한다(mountedRef 가드).
 *
 * Requirements: 6.1, 6.2, 6.5, 6.6.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { lockVersionApi } from "../api/lockVersionApi";
import type { DocumentVersionRead } from "../types";
import { ApiError } from "@/shared/api/errors";

/** 페이지 크기(백엔드 기본 50, min 1). 이력 뷰어는 한 페이지에 넉넉히 받는다. */
const PAGE_LIMIT = 50;

/** 버전 이력 상태(design 계약). `currentVersionId` 는 상위 주입값(현재 버전 구분용). */
export interface VersionHistoryState {
  status: "loading" | "ready" | "error";
  versions: DocumentVersionRead[];
  total: number;
  currentVersionId: number | null;
  error: ApiError | null;
}

/** {@link VersionHistoryState} 에 재로드·이어받기 조작을 더한 반환 계약. */
export type UseVersionHistory = VersionHistoryState & {
  /** offset 0 부터 처음부터 재로드(누적 초기화). */
  reload(): Promise<void>;
  /** 누적 length 를 offset 으로 다음 페이지를 이어받아 append(모두 로드했으면 no-op). */
  loadMore(): Promise<void>;
};

/** throw 된 원인을 `ApiError` 로 정규화(계약상 apiClient 는 ApiError 를 throw 한다). */
function toApiError(cause: unknown): ApiError {
  if (cause instanceof ApiError) {
    return cause;
  }
  return new ApiError({
    status: 0,
    code: "internal",
    message: "예기치 못한 오류가 발생했습니다.",
  });
}

export function useVersionHistory(
  documentId: number,
  currentVersionId: number | null,
): UseVersionHistory {
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [versions, setVersions] = useState<DocumentVersionRead[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);

  const mountedRef = useRef(true);
  const loadingRef = useRef(false); // in-flight 가드(중복 append·동시 로드 방지)
  const versionsRef = useRef<DocumentVersionRead[]>([]); // 누적(offset 소스)
  const totalRef = useRef(0); // loadMore 의 최신 total(stale 클로저 방지)

  /**
   * 단일 페이지 로드. `offset===0` 이면 처음부터(로딩 표시·누적 초기화),
   * 그 외면 이어받아 append. mount·reload·loadMore 공용.
   */
  const load = useCallback(
    async (offset: number): Promise<void> => {
      if (loadingRef.current) {
        return; // 이미 로드 중 — 중복 호출 무시(멱등 안전)
      }
      loadingRef.current = true;

      if (offset === 0) {
        versionsRef.current = [];
        setStatus("loading");
        setError(null);
      }

      try {
        const pageResult = await lockVersionApi.listVersions(
          documentId,
          PAGE_LIMIT,
          offset,
        );
        if (!mountedRef.current) {
          return;
        }
        const next =
          offset === 0
            ? pageResult.items
            : [...versionsRef.current, ...pageResult.items];
        versionsRef.current = next;
        totalRef.current = pageResult.total;
        setVersions(next);
        setTotal(pageResult.total);
        setStatus("ready");
      } catch (cause) {
        if (!mountedRef.current) {
          return;
        }
        setError(toApiError(cause));
        setStatus("error");
      } finally {
        loadingRef.current = false;
      }
    },
    [documentId],
  );

  const reload = useCallback(async (): Promise<void> => {
    await load(0);
  }, [load]);

  const loadMore = useCallback(async (): Promise<void> => {
    // 이미 total 만큼 로드했으면 이어받을 페이지가 없다(no-op).
    if (versionsRef.current.length >= totalRef.current) {
      return;
    }
    await load(versionsRef.current.length);
  }, [load]);

  useEffect(() => {
    mountedRef.current = true;
    void load(0);
    return () => {
      mountedRef.current = false;
    };
  }, [load]);

  return {
    status,
    versions,
    total,
    currentVersionId,
    error,
    reload,
    loadMore,
  };
}
