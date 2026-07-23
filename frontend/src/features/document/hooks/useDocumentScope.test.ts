import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook } from "@testing-library/react";

import { useDocumentScope } from "./useDocumentScope";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useSession } from "@/app/session/useSession";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { SessionContextValue } from "@/app/session/SessionProvider";
import { Role } from "@/shared/auth/roles";

/**
 * useDocumentScope 는 s16 앰비언트 계약(useCurrentWorkspace 최상위 접근자 + useSession.is_admin)을
 * 얇게 선택만 한다. 협력자를 모킹해 status/workspaceId/role 통과와 isAdmin 파생만 관찰한다
 * (Requirements 9.1, 9.2).
 */
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));
vi.mock("@/app/session/useSession", () => ({
  useSession: vi.fn(),
}));

const useCurrentWorkspaceMock = useCurrentWorkspace as unknown as Mock;
const useSessionMock = useSession as unknown as Mock;

function workspaceValue(
  overrides: Partial<CurrentWorkspaceContextValue> = {},
): CurrentWorkspaceContextValue {
  return {
    status: "ready",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: "7",
    role: Role.MEMBER,
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
    ...overrides,
  };
}

function authenticatedSession(isAdmin: boolean): SessionContextValue {
  return {
    status: "authenticated",
    user: {
      id: 1,
      login_id: "user",
      name: "사용자",
      email: null,
      is_admin: isAdmin,
    },
    settings: null,
    refresh: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useDocumentScope", () => {
  it("useCurrentWorkspace 최상위 status/workspaceId/role 을 그대로 통과시킨다", () => {
    useCurrentWorkspaceMock.mockReturnValue(
      workspaceValue({ status: "ready", workspaceId: "42", role: Role.OWNER }),
    );
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.status).toBe("ready");
    expect(result.current.workspaceId).toBe("42");
    expect(result.current.role).toBe(Role.OWNER);
  });

  it("workspaceId 를 산술 없이 문자열 그대로 통과시킨다", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue({ workspaceId: "100" }));
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.workspaceId).toBe("100");
  });

  it("status=loading·empty 도 그대로 통과시키고 workspaceId=null 을 보존한다", () => {
    useCurrentWorkspaceMock.mockReturnValue(
      workspaceValue({ status: "loading", workspaceId: null, role: null }),
    );
    useSessionMock.mockReturnValue({ status: "loading", refresh: vi.fn() });

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.status).toBe("loading");
    expect(result.current.workspaceId).toBeNull();
  });

  it("비멤버 role=null 을 null 그대로 통과시킨다", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue({ role: null }));
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.role).toBeNull();
  });

  it("authenticated 이고 user.is_admin 이 true 면 isAdmin=true", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue());
    useSessionMock.mockReturnValue(authenticatedSession(true));

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.isAdmin).toBe(true);
  });

  it("authenticated 이지만 user.is_admin 이 false 면 isAdmin=false", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue());
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.isAdmin).toBe(false);
  });

  it("unauthenticated 면 isAdmin=false", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue());
    useSessionMock.mockReturnValue({ status: "unauthenticated", refresh: vi.fn() });

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.isAdmin).toBe(false);
  });

  it("loading 세션이면 isAdmin=false", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue());
    useSessionMock.mockReturnValue({ status: "loading", refresh: vi.fn() });

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.isAdmin).toBe(false);
  });

  it("useCurrentWorkspace.isShareable=true 를 가공 없이 그대로 투영한다", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue({ isShareable: true }));
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.isShareable).toBe(true);
  });

  it("useCurrentWorkspace.isShareable=false 를 그대로 투영한다", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue({ isShareable: false }));
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useDocumentScope());

    expect(result.current.isShareable).toBe(false);
  });
});
