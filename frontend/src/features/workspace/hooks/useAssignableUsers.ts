/**
 * 배정 가능 사용자 조회 훅 (design.md "features/workspace/hooks → useAssignableUsers").
 *
 * 마운트 시 `workspaceId !== null` 이면 `assignableUserApi.listAssignable(id, {limit:50, offset:0})`
 * 로 첫 페이지를 조회해 (status=ready·users·total) 노출하고, `reload()` 로 offset 0 부터 재조회한다.
 * `useVersionHistory` 형태를 미러하되 페이지네이션(`loadMore`)·`currentVersionId` 없이 **첫 페이지
 * 전용** 으로 단순화한다(추가 페이지는 이 spec 밖 — 인터페이스에 노출하지 않음).
 *
 * 계약 제약(Req 3.1·3.4·3.6·4.1):
 * - `workspaceId === null` 이면 fetch 하지 않고 안정 non-loading 상태(status=ready·빈 목록·total 0·
 *   error null)로 정착한다(로딩 고착 금지). null 인 동안 `reload()` 는 no-op.
 * - `workspaceId` 가 non-null 로 바뀌면 재조회한다(effect 의존성).
 * - 조회 실패는 정규화된 {@link ApiError}(`toApiError`)로 표면화한다(status→"error").
 *
 * in-flight 가드(`loadingRef`)로 동시 중복 로드를 막고, 언마운트 후에는 상태 갱신을 억제한다
 * (`mountedRef` 가드).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { assignableUserApi } from "../api/assignableUserApi";
import type { AssignableUser } from "../api/types";
import { ApiError } from "@/shared/api/errors";

/** 페이지 크기(백엔드 기본 50, min 1). 배정 가능 목록은 한 페이지에 넉넉히 받는다. */
const PAGE_LIMIT = 50;

/** 배정 가능 사용자 조회 상태(design 계약). */
export interface AssignableUsersState {
  status: "loading" | "ready" | "error";
  users: AssignableUser[];
  total: number;
  error: ApiError | null;
}

/** {@link AssignableUsersState} 에 재조회 조작을 더한 반환 계약. */
export type UseAssignableUsers = AssignableUsersState & {
  /** offset 0 부터 첫 페이지를 재조회(workspaceId 가 null 이면 no-op). */
  reload(): Promise<void>;
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

export function useAssignableUsers(
  workspaceId: number | null,
): UseAssignableUsers {
  // workspaceId 가 null 이면 조회 없이 안정 ready 로 정착(로딩 고착 금지).
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    workspaceId === null ? "ready" : "loading",
  );
  const [users, setUsers] = useState<AssignableUser[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);

  const mountedRef = useRef(true);
  const loadingRef = useRef(false); // in-flight 가드(동시 중복 로드 방지)

  /** 첫 페이지 로드. workspaceId 가 null 이면 no-op. mount·reload·workspaceId 변경 공용. */
  const load = useCallback(async (): Promise<void> => {
    if (workspaceId === null) {
      return; // 조회 대상 없음 — 안정 상태 유지(no-op)
    }
    if (loadingRef.current) {
      return; // 이미 로드 중 — 중복 호출 무시(멱등 안전)
    }
    loadingRef.current = true;

    setStatus("loading");
    setError(null);

    try {
      const pageResult = await assignableUserApi.listAssignable(workspaceId, {
        limit: PAGE_LIMIT,
        offset: 0,
      });
      if (!mountedRef.current) {
        return;
      }
      setUsers(pageResult.items);
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
  }, [workspaceId]);

  const reload = useCallback(async (): Promise<void> => {
    await load();
  }, [load]);

  useEffect(() => {
    mountedRef.current = true;
    void load();
    return () => {
      mountedRef.current = false;
    };
  }, [load]);

  return {
    status,
    users,
    total,
    error,
    reload,
  };
}
