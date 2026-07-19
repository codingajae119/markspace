import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useWorkspaceActions } from "./useWorkspaceActions";
import { workspaceApi } from "../api/workspaceApi";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { MembershipRoleSource } from "../context/membershipRoleSource";
import type { WorkspaceRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// useWorkspaceActions 는 s16 계약(useCurrentWorkspace.refresh/selectWorkspace)·s18
// MembershipRoleSource(recordOwner)·workspaceApi 를 조합한다. 협력자를 모킹해
// 성공 시 owner 기록·refresh·(refresh 이후)selectWorkspace 순서와 실패 롤백을 관찰한다.
const refreshMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
const selectWorkspaceMock = vi.fn<(id: string) => void>();
const recordOwnerMock = vi.fn<(workspaceId: number) => void>();
const recordSelfRoleMock = vi.fn();
const roleForMock = vi.fn();

vi.mock("../api/workspaceApi", () => ({ workspaceApi: { create: vi.fn() } }));
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));
vi.mock("../context/membershipRoleSource", () => ({
  useMembershipRoleSource: vi.fn(),
}));

const createMock = workspaceApi.create as unknown as Mock;

function workspaceRead(overrides: Partial<WorkspaceRead> = {}): WorkspaceRead {
  return {
    id: 7,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    name: "새 워크스페이스",
    is_shareable: false,
    trash_retention_days: 30,
    ...overrides,
  };
}

function contextValue(): CurrentWorkspaceContextValue {
  return {
    status: "ready",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: null,
    role: null,
    isShareable: false,
    selectWorkspace: selectWorkspaceMock,
    refresh: refreshMock,
  };
}

function roleSource(): MembershipRoleSource {
  return {
    roleFor: roleForMock,
    recordOwner: recordOwnerMock,
    recordSelfRole: recordSelfRoleMock,
  };
}

function conflict(): ApiError {
  return new ApiError({ status: 422, code: "validation_error", message: "이름이 필요합니다" });
}

beforeEach(() => {
  refreshMock.mockReset().mockResolvedValue(undefined);
  selectWorkspaceMock.mockReset();
  recordOwnerMock.mockReset();
  createMock.mockReset();
  vi.mocked(useCurrentWorkspace).mockReturnValue(contextValue());
  vi.mocked(useMembershipRoleSource).mockReturnValue(roleSource());
});

describe("useWorkspaceActions", () => {
  it("생성 성공 시 recordOwner(created.id)·refresh·selectWorkspace(String(id)) 를 호출하고 생성물을 반환한다 (Req 2.1, 2.3)", async () => {
    const created = workspaceRead({ id: 42 });
    createMock.mockResolvedValueOnce(created);

    const { result } = renderHook(() => useWorkspaceActions());

    let returned: WorkspaceRead | null = null;
    await act(async () => {
      returned = await result.current.create({ name: "새 워크스페이스" });
    });

    expect(createMock).toHaveBeenCalledWith({ name: "새 워크스페이스" });
    expect(recordOwnerMock).toHaveBeenCalledWith(42);
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(selectWorkspaceMock).toHaveBeenCalledWith("42");
    expect(returned).toBe(created);
    expect(result.current.error).toBeNull();
  });

  it("selectWorkspace 는 refresh 가 resolve 된 이후에 호출된다 (Req 2.1)", async () => {
    const created = workspaceRead({ id: 9 });
    createMock.mockResolvedValueOnce(created);

    const { result } = renderHook(() => useWorkspaceActions());

    await act(async () => {
      await result.current.create({ name: "WS" });
    });

    expect(refreshMock.mock.invocationCallOrder[0]).toBeLessThan(
      selectWorkspaceMock.mock.invocationCallOrder[0],
    );
  });

  it("생성 실패(ApiError) 시 error 를 세팅하고 refresh·recordOwner·selectWorkspace 는 호출하지 않는다 (Req 2.4, 롤백)", async () => {
    const err = conflict();
    createMock.mockRejectedValueOnce(err);

    const { result } = renderHook(() => useWorkspaceActions());

    let returned: WorkspaceRead | null = workspaceRead();
    await act(async () => {
      returned = await result.current.create({ name: "  " });
    });

    expect(result.current.error).toBe(err);
    expect(returned).toBeNull();
    expect(refreshMock).not.toHaveBeenCalled();
    expect(recordOwnerMock).not.toHaveBeenCalled();
    expect(selectWorkspaceMock).not.toHaveBeenCalled();
  });

  it("재시도 시 직전 오류를 해제한다", async () => {
    createMock.mockRejectedValueOnce(conflict());
    const { result } = renderHook(() => useWorkspaceActions());
    await act(async () => {
      await result.current.create({ name: "x" });
    });
    expect(result.current.error).not.toBeNull();

    createMock.mockResolvedValueOnce(workspaceRead({ id: 5 }));
    await act(async () => {
      await result.current.create({ name: "x" });
    });
    expect(result.current.error).toBeNull();
  });

  it("in-flight 동안 creating=true, 완료 후 false 로 돌아온다", async () => {
    let release: (v: WorkspaceRead) => void = () => {};
    createMock.mockImplementationOnce(
      () =>
        new Promise<WorkspaceRead>((resolve) => {
          release = resolve;
        }),
    );

    const { result } = renderHook(() => useWorkspaceActions());
    expect(result.current.creating).toBe(false);

    let createPromise: Promise<WorkspaceRead | null>;
    act(() => {
      createPromise = result.current.create({ name: "WS" });
    });

    await waitFor(() => expect(result.current.creating).toBe(true));

    await act(async () => {
      release(workspaceRead({ id: 1 }));
      await createPromise;
    });
    expect(result.current.creating).toBe(false);
  });
});
