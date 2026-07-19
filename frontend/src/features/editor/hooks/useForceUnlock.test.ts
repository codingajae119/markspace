import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useForceUnlock } from "./useForceUnlock";
import { lockVersionApi } from "../api/lockVersionApi";
import { ApiError } from "@/shared/api/errors";
import { Role } from "@/shared/auth/roles";

/**
 * useForceUnlock 은 (a) `canForceUnlock` 노출 판정을 오직 s16 `hasWorkspaceRole`
 * ({minimum: OWNER}, admin bypass 포함) 단일 경로로 파생하고(컴포넌트 역할 비교 금지),
 * (b) `forceUnlock()` 로 `lockVersionApi.forceUnlock`(204) 을 호출해 성공 시 true,
 * 실패(403/404) 시 false + state.error 표면화, pending 토글을 관리한다.
 * 협력자(lockVersionApi)만 모킹하고 실 hasWorkspaceRole 을 사용해 파생·동작만 관찰한다
 * (Requirements 5.1, 5.2, 5.4, 5.5).
 */
vi.mock("../api/lockVersionApi", () => ({
  lockVersionApi: {
    lockDocument: vi.fn(),
    getDocument: vi.fn(),
    saveDocument: vi.fn(),
    cancelEdit: vi.fn(),
    forceUnlock: vi.fn(),
    listVersions: vi.fn(),
  },
}));

const forceUnlockMock = lockVersionApi.forceUnlock as unknown as Mock;

const DOC_ID = 42;

function apiError(status: number, code = "forbidden"): ApiError {
  return new ApiError({ status, code, message: `err-${status}` });
}

beforeEach(() => {
  vi.clearAllMocks();
  forceUnlockMock.mockResolvedValue(undefined);
});

describe("useForceUnlock — canForceUnlock 파생 (5.1, 5.5)", () => {
  it("OWNER(non-admin) → canForceUnlock true", () => {
    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.OWNER, false),
    );
    expect(result.current.canForceUnlock).toBe(true);
  });

  it("admin bypass(currentRole=null, isAdmin=true) → true", () => {
    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, null, true),
    );
    expect(result.current.canForceUnlock).toBe(true);
  });

  it("admin bypass(currentRole=VIEWER, isAdmin=true) → true", () => {
    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.VIEWER, true),
    );
    expect(result.current.canForceUnlock).toBe(true);
  });

  it("EDITOR(non-admin) → false", () => {
    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.EDITOR, false),
    );
    expect(result.current.canForceUnlock).toBe(false);
  });

  it("VIEWER(non-admin) → false", () => {
    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.VIEWER, false),
    );
    expect(result.current.canForceUnlock).toBe(false);
  });

  it("currentRole=null(non-admin) → false", () => {
    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, null, false),
    );
    expect(result.current.canForceUnlock).toBe(false);
  });
});

describe("useForceUnlock — forceUnlock() 동작 (5.2, 5.4)", () => {
  it("204 성공 시 true 를 반환하고 error 없이 pending 이 정리된다 (5.2)", async () => {
    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.OWNER, false),
    );

    let resolved: boolean | undefined;
    await act(async () => {
      resolved = await result.current.forceUnlock();
    });

    expect(resolved).toBe(true);
    expect(forceUnlockMock).toHaveBeenCalledTimes(1);
    expect(forceUnlockMock).toHaveBeenCalledWith(DOC_ID);
    expect(result.current.state.pending).toBe(false);
    expect(result.current.state.error).toBeNull();
  });

  it("403 ApiError 시 false 를 반환하고 state.error 를 표면화하며 pending 이 정리된다 (5.4)", async () => {
    forceUnlockMock.mockRejectedValue(apiError(403, "forbidden"));

    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.OWNER, false),
    );

    let resolved: boolean | undefined;
    await act(async () => {
      resolved = await result.current.forceUnlock();
    });

    expect(resolved).toBe(false);
    expect(result.current.state.error?.status).toBe(403);
    expect(result.current.state.pending).toBe(false);
  });

  it("404 ApiError 시 false 반환·error 표면화 (5.4)", async () => {
    forceUnlockMock.mockRejectedValue(apiError(404, "not_found"));

    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.OWNER, false),
    );

    let resolved: boolean | undefined;
    await act(async () => {
      resolved = await result.current.forceUnlock();
    });

    expect(resolved).toBe(false);
    expect(result.current.state.error?.status).toBe(404);
  });

  it("성공 재시도는 직전 error 를 초기화한다 (5.4)", async () => {
    forceUnlockMock.mockRejectedValueOnce(apiError(403, "forbidden"));
    forceUnlockMock.mockResolvedValueOnce(undefined);

    const { result } = renderHook(() =>
      useForceUnlock(DOC_ID, Role.OWNER, false),
    );

    await act(async () => {
      await result.current.forceUnlock();
    });
    expect(result.current.state.error?.status).toBe(403);

    await act(async () => {
      await result.current.forceUnlock();
    });
    expect(result.current.state.error).toBeNull();
  });
});
