/**
 * 휴지통 상태 훅 (design.md "features/document → useTrash").
 *
 * 현재 워크스페이스의 휴지통 묶음 첫 페이지를 로드(`documentApi.listTrash`)하고
 * `bundles`(= page.items)·`total`(= page.total)·`status`·`error` 를 노출하며, 재로드
 * (`reload`)·복원(`restore`)·영구삭제(`purge`)·페이지 이동(`loadPage`)을 제공한다. 복원
 * 위치·묶음 원자성·보존기간 판정은 전혀 하지 않고 오직 백엔드 결과만 반영한다(Req 8.7).
 *
 * 로드는 `documentApi.listTrash(workspaceId, limit, offset)` → `Page<TrashBundleRead>`
 * 를 사용한다. 진행 중 status="loading", 성공 시 "ready", 실패 시 "error" 로 수렴하고
 * 실패한 raw `ApiError` 를 `error` 에 보존한다(Req 8.1). `workspaceId` 가 빈 문자열이면
 * API 를 호출하지 않고 빈 목록으로 ready 수렴한다(방어적 — 화면이 접근을 게이트).
 *
 * `restore(bundleId)`: `restoreBundle` 204 성공 시 `reload()` 후 true. 실패 시 raw
 * `ApiError` 를 `error` 에 설정한 뒤 `reload()`(오류 표면화 + 재목록, Req 8.5) 하고 false.
 * `purge(bundleId)`: `purgeBundle` 204 성공 시 `reload()` 후 true. 실패 시 error 설정 +
 * reload 후 false(되돌릴 수 없음 경고는 UI 책임). `error` 는 각 로드/변이 시작 시 초기화한다.
 *
 * 동시성: 언마운트 후 setState 방지 + 최신 실행만 반영(latest-wins)을 위해
 * `useDocumentTree` / `CurrentWorkspaceProvider` 와 동일한 `mountedRef`/`runIdRef` idiom
 * 을 사용한다.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/shared/api/errors";
import type { TrashBundleRead } from "../types";
import { documentApi } from "../api/documentApi";

/** 휴지통 로드/목록 상태 표면 (design.md §useTrash). */
export interface TrashState {
  /** 로드 상태: 진행 중(loading)·성공(ready, 빈 목록 포함)·실패(error). */
  status: "loading" | "ready" | "error";
  /** 현재 페이지의 휴지통 묶음(= page.items). */
  bundles: TrashBundleRead[];
  /** 전체 묶음 개수(= page.total). */
  total: number;
  /** 로드/변이 실패 시 보존한 raw ApiError, 그 외 null. */
  error: ApiError | null;
}

/** 상태 표면 + 재로드/복원/영구삭제/페이지 이동 seam. */
export type UseTrashResult = TrashState & {
  /** 현재 페이지 재조회. */
  reload(): Promise<void>;
  /** 묶음 복원(204 성공 true, 실패 시 error 설정+재목록 후 false). */
  restore(bundleId: number): Promise<boolean>;
  /** 묶음 영구삭제(204 성공 true, 실패 시 error 설정+재목록 후 false). */
  purge(bundleId: number): Promise<boolean>;
  /** 특정 페이지 로드(limit/offset). */
  loadPage(limit: number, offset: number): Promise<void>;
};

/** 기본 페이지 크기. 첫 로드/재로드가 사용하는 항목 수. */
const DEFAULT_PAGE_SIZE = 50;

/** 알 수 없는 throw 를 안정적 ApiError 로 정규화(내부 세부정보 미노출). */
function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) {
    return err;
  }
  return new ApiError({
    status: 0,
    code: "internal",
    message: "예기치 못한 오류가 발생했습니다.",
  });
}

/**
 * 현재 워크스페이스의 휴지통 묶음을 로드하고 복원·영구삭제를 노출하는 훅.
 */
export function useTrash(workspaceId: string): UseTrashResult {
  const [status, setStatus] = useState<TrashState["status"]>("loading");
  const [bundles, setBundles] = useState<TrashBundleRead[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);

  // 언마운트 후 setState 방지 + 최신 실행만 반영(경합 시 latest-wins).
  const mountedRef = useRef(true);
  const runIdRef = useRef(0);
  // reload 가 재조회할 현재 페이지(limit/offset). loadPage 가 갱신한다.
  const pageRef = useRef<{ limit: number; offset: number }>({
    limit: DEFAULT_PAGE_SIZE,
    offset: 0,
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(
    async (limit: number, offset: number): Promise<void> => {
      const runId = runIdRef.current + 1;
      runIdRef.current = runId;
      pageRef.current = { limit, offset };

      // 빈 workspaceId: API 호출 없이 빈 목록으로 ready 수렴(방어적).
      if (workspaceId === "") {
        if (mountedRef.current && runIdRef.current === runId) {
          setBundles([]);
          setTotal(0);
          setError(null);
          setStatus("ready");
        }
        return;
      }

      setStatus("loading");
      setError(null);
      try {
        const pageResult = await documentApi.listTrash(workspaceId, limit, offset);
        if (mountedRef.current && runIdRef.current === runId) {
          setBundles(pageResult.items);
          setTotal(pageResult.total);
          setError(null);
          setStatus("ready");
        }
      } catch (err) {
        if (mountedRef.current && runIdRef.current === runId) {
          setError(toApiError(err));
          setStatus("error");
        }
      }
    },
    [workspaceId],
  );

  // 마운트 및 workspaceId 변경 시 첫 페이지 로드.
  useEffect(() => {
    void load(DEFAULT_PAGE_SIZE, 0);
  }, [load]);

  const reload = useCallback((): Promise<void> => {
    const { limit, offset } = pageRef.current;
    return load(limit, offset);
  }, [load]);

  const loadPage = useCallback(
    (limit: number, offset: number): Promise<void> => load(limit, offset),
    [load],
  );

  // 변이(복원/영구삭제) 공통: 204 성공 시 reload 후 true. 실패 시 목록 재조회 후 raw error 표면화 false.
  const mutate = useCallback(
    async (call: () => Promise<void>): Promise<boolean> => {
      setError(null);
      let mutationError: ApiError | null = null;
      try {
        await call();
      } catch (err) {
        mutationError = toApiError(err);
      }
      // 성공/실패 모두 목록을 재조회한다(Req 8.5 오류 표면화 + 재목록).
      // reload 는 load 시작 시 error 를 초기화하므로, 실패 오류는 reload 이후에 다시 설정해
      // 목록 갱신과 오류 표면화가 함께 관측되게 한다.
      await reload();
      if (mutationError !== null) {
        if (mountedRef.current) {
          setError(mutationError);
        }
        return false;
      }
      return true;
    },
    [reload],
  );

  const restore = useCallback(
    (bundleId: number): Promise<boolean> =>
      mutate(() => documentApi.restoreBundle(bundleId)),
    [mutate],
  );

  const purge = useCallback(
    (bundleId: number): Promise<boolean> =>
      mutate(() => documentApi.purgeBundle(bundleId)),
    [mutate],
  );

  return {
    status,
    bundles,
    total,
    error,
    reload,
    restore,
    purge,
    loadPage,
  };
}
