import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useWorkspaceMembers } from "./useWorkspaceMembers";
import { memberApi } from "../api/memberApi";
import type { MemberRosterRow, Page } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// useWorkspaceMembers 는 memberApi.list 만 소비하는 조회 상태기계다
// (useAssignableUsers 형태 미러). api 모듈을 모킹해 마운트 fetch·null 처리·
// 실패 정규화·reload 재fetch 를 관찰한다.
vi.mock("../api/memberApi", () => ({
  memberApi: {
    add: vi.fn(),
    changeRole: vi.fn(),
    remove: vi.fn(),
    list: vi.fn(),
  },
}));

const list = memberApi.list as unknown as Mock;

const WS = 1;

function member(overrides: Partial<MemberRosterRow> = {}): MemberRosterRow {
  return {
    user_id: 10,
    name: "Alice",
    email: "alice@example.com",
    role: "editor",
    ...overrides,
  };
}

function page(
  items: MemberRosterRow[],
  total = items.length,
): Page<MemberRosterRow> {
  return { items, total };
}

function forbidden(): ApiError {
  return new ApiError({ status: 403, code: "forbidden", message: "접근 불가" });
}

beforeEach(() => {
  list.mockReset();
});

describe("useWorkspaceMembers", () => {
  it("마운트 시 첫 페이지를 조회해 status ready·members·total 을 노출한다 (Req 3.1·3.2)", async () => {
    const items = [
      member({ user_id: 10 }),
      member({ user_id: 11, name: "Bob", email: null, role: "viewer" }),
    ];
    list.mockResolvedValueOnce(page(items, 5));

    const { result } = renderHook(() => useWorkspaceMembers(WS));

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(list).toHaveBeenCalledWith(WS, { limit: 50, offset: 0 });
    expect(result.current.members).toEqual(items);
    expect(result.current.total).toBe(5);
    expect(result.current.error).toBeNull();
  });

  it("조회 실패(ApiError) 시 status error·error 를 세팅한다 (Req 3.4)", async () => {
    const err = forbidden();
    list.mockRejectedValueOnce(err);

    const { result } = renderHook(() => useWorkspaceMembers(WS));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe(err);
    expect(result.current.members).toEqual([]);
  });

  it("비-ApiError 예외도 ApiError(internal) 로 정규화한다 (Req 3.4)", async () => {
    list.mockRejectedValueOnce(new Error("boom"));

    const { result } = renderHook(() => useWorkspaceMembers(WS));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect(result.current.error?.code).toBe("internal");
  });

  it("workspaceId 가 null 이면 fetch 하지 않고 안정 상태로 정착한다 (Req 3.6, loading 고착 금지)", async () => {
    const { result } = renderHook(() => useWorkspaceMembers(null));

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(list).not.toHaveBeenCalled();
    expect(result.current.members).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("workspaceId 가 null 이면 reload() 는 no-op(호출 없음)이다 (Req 3.6)", async () => {
    const { result } = renderHook(() => useWorkspaceMembers(null));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      await result.current.reload();
    });
    expect(list).not.toHaveBeenCalled();
  });

  it("reload() 는 offset 0 으로 재조회한다 (Req 3.3)", async () => {
    list.mockResolvedValueOnce(page([member({ user_id: 10 })], 1));
    const { result } = renderHook(() => useWorkspaceMembers(WS));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(list).toHaveBeenCalledTimes(1);

    list.mockResolvedValueOnce(page([member({ user_id: 11, name: "Bob" })], 1));
    await act(async () => {
      await result.current.reload();
    });

    expect(list).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenLastCalledWith(WS, { limit: 50, offset: 0 });
    expect(result.current.members).toEqual([member({ user_id: 11, name: "Bob" })]);
  });

  it("재조회 성공 시 직전 error 를 해제한다 (Req 3.3·3.4)", async () => {
    list.mockRejectedValueOnce(forbidden());
    const { result } = renderHook(() => useWorkspaceMembers(WS));
    await waitFor(() => expect(result.current.status).toBe("error"));

    list.mockResolvedValueOnce(page([member()], 1));
    await act(async () => {
      await result.current.reload();
    });

    expect(result.current.status).toBe("ready");
    expect(result.current.error).toBeNull();
  });

  it("workspaceId 가 non-null 로 바뀌면 재조회한다 (Req 3.1)", async () => {
    list.mockResolvedValue(page([member()], 1));
    const { result, rerender } = renderHook(
      ({ id }: { id: number | null }) => useWorkspaceMembers(id),
      { initialProps: { id: null as number | null } },
    );
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(list).not.toHaveBeenCalled();

    rerender({ id: 2 });
    await waitFor(() =>
      expect(list).toHaveBeenCalledWith(2, { limit: 50, offset: 0 }),
    );
  });
});
