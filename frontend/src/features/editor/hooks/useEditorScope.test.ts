import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook } from "@testing-library/react";

import { useEditorScope } from "./useEditorScope";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useSession } from "@/app/session/useSession";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { SessionContextValue } from "@/app/session/SessionProvider";
import { Role } from "@/shared/auth/roles";

/**
 * useEditorScope 는 s16 앰비언트 계약(useCurrentWorkspace 최상위 workspaceId·role +
 * useSession 의 is_admin·user.id)을 편집용으로 얇게 결합만 한다. 협력자를 모킹해
 * workspaceId/role 통과와 isAdmin·currentUserId 파생만 관찰한다(Requirements 7.1, 7.2).
 * 동명 s16 훅을 재정의하지 않으며, role 을 스스로 발명하지 않고 통과만 함을 확인한다.
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
    role: Role.EDITOR,
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
    ...overrides,
  };
}

function authenticatedSession(isAdmin: boolean, id = 1): SessionContextValue {
  return {
    status: "authenticated",
    user: {
      id,
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

describe("useEditorScope", () => {
  it("authenticated 비관리자면 workspaceId/role 을 그대로 통과시키고 isAdmin=false·currentUserId=user.id", () => {
    useCurrentWorkspaceMock.mockReturnValue(
      workspaceValue({ workspaceId: "42", role: Role.OWNER }),
    );
    useSessionMock.mockReturnValue(authenticatedSession(false, 9));

    const { result } = renderHook(() => useEditorScope());

    expect(result.current.workspaceId).toBe("42");
    expect(result.current.role).toBe(Role.OWNER);
    expect(result.current.isAdmin).toBe(false);
    expect(result.current.currentUserId).toBe(9);
  });

  it("workspaceId 를 산술 없이 문자열 그대로 통과시킨다", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue({ workspaceId: "100" }));
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useEditorScope());

    expect(result.current.workspaceId).toBe("100");
  });

  it("authenticated 이고 user.is_admin 이 true 면 isAdmin=true", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue());
    useSessionMock.mockReturnValue(authenticatedSession(true, 3));

    const { result } = renderHook(() => useEditorScope());

    expect(result.current.isAdmin).toBe(true);
    expect(result.current.currentUserId).toBe(3);
  });

  it("unauthenticated 면 isAdmin=false·currentUserId=null", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue());
    useSessionMock.mockReturnValue({ status: "unauthenticated", refresh: vi.fn() });

    const { result } = renderHook(() => useEditorScope());

    expect(result.current.isAdmin).toBe(false);
    expect(result.current.currentUserId).toBeNull();
  });

  it("loading 세션이면 isAdmin=false·currentUserId=null", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue());
    useSessionMock.mockReturnValue({ status: "loading", refresh: vi.fn() });

    const { result } = renderHook(() => useEditorScope());

    expect(result.current.isAdmin).toBe(false);
    expect(result.current.currentUserId).toBeNull();
  });

  it("workspaceId=null·role=null 을 발명 없이 그대로 통과시킨다", () => {
    useCurrentWorkspaceMock.mockReturnValue(
      workspaceValue({ status: "loading", workspaceId: null, role: null }),
    );
    useSessionMock.mockReturnValue(authenticatedSession(false));

    const { result } = renderHook(() => useEditorScope());

    expect(result.current.workspaceId).toBeNull();
    expect(result.current.role).toBeNull();
  });

  it("비멤버 role=null 을 null 그대로 통과시킨다(스스로 role 을 발명하지 않는다)", () => {
    useCurrentWorkspaceMock.mockReturnValue(workspaceValue({ role: null }));
    useSessionMock.mockReturnValue(authenticatedSession(true));

    const { result } = renderHook(() => useEditorScope());

    expect(result.current.role).toBeNull();
  });
});
