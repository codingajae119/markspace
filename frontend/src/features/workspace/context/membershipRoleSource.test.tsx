import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  MembershipRoleProvider,
  useMembershipRoleSource,
  memberRoleToRole,
} from "./membershipRoleSource";
import { Role } from "@/shared/auth/roles";
import type { WorkspaceRole } from "@/shared/auth/roles";
import { CurrentWorkspaceContext } from "@/app/workspace-context/CurrentWorkspaceProvider";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { WorkspaceRead } from "@/shared/types/workspace";

// MembershipRoleSource 는 현재 사용자의 WS별 확인된 role 을 축적하는 s18 단일 소스다.
// role 파생/번역 로직은 이 모듈에만 존재하므로(단일 소스 규칙) 여기서 그 동작을 관찰한다.
describe("MembershipRoleSource", () => {
  it("recordOwner(wsId) 후 roleFor(wsId) === Role.OWNER (생성 응답 owner 기록)", () => {
    const { result } = renderHook(() => useMembershipRoleSource(), {
      wrapper: MembershipRoleProvider,
    });

    act(() => {
      result.current.recordOwner(7);
    });

    expect(result.current.roleFor(7)).toBe(Role.OWNER);
  });

  it("recordSelfRole(wsId, role) 은 저장된 role 을 덮어쓴다(자기 role 에코)", () => {
    const { result } = renderHook(() => useMembershipRoleSource(), {
      wrapper: MembershipRoleProvider,
    });

    act(() => {
      result.current.recordOwner(7);
    });
    expect(result.current.roleFor(7)).toBe(Role.OWNER);

    act(() => {
      result.current.recordSelfRole(7, Role.MEMBER);
    });
    expect(result.current.roleFor(7)).toBe(Role.MEMBER);
  });

  it("신호가 기록되지 않은 wsId 는 roleFor → null (부재 시 null, best-effort)", () => {
    const { result } = renderHook(() => useMembershipRoleSource(), {
      wrapper: MembershipRoleProvider,
    });

    expect(result.current.roleFor(99)).toBeNull();
  });

  it("record 는 소비자 재렌더를 트리거해 최신 role 이 노출된다", () => {
    const { result } = renderHook(() => useMembershipRoleSource(), {
      wrapper: MembershipRoleProvider,
    });

    expect(result.current.roleFor(3)).toBeNull();

    act(() => {
      result.current.recordSelfRole(3, Role.MEMBER);
    });

    expect(result.current.roleFor(3)).toBe(Role.MEMBER);
  });

  it("memberRoleToRole 은 MemberRole 문자열을 s16 Role enum 으로 번역한다", () => {
    expect(memberRoleToRole("owner")).toBe(Role.OWNER);
    expect(memberRoleToRole("member")).toBe(Role.MEMBER);
  });

  it("useMembershipRoleSource() 를 provider 밖에서 호출하면 오류를 던진다", () => {
    expect(() => renderHook(() => useMembershipRoleSource())).toThrow(
      /MembershipRoleProvider/,
    );
  });
});

// ── 로드-시드 ⊕ in-session 병합 (s24) ─────────────────────────────────────────
// MembershipRoleProvider 가 상위 CurrentWorkspaceContext 를 옵셔널로 읽어 로드된 workspaces
// 중 role≠null 항목을 서버 권위값으로 시드한다. standalone(컨텍스트 null) 마운트는 시드하지
// 않고 기존 in-session 전용 동작을 보존한다(Req 2.1·2.4·3.2·4.2·5.1·5.2·5.3·5.4).
describe("MembershipRoleSource 로드-시드", () => {
  function ws(id: number, role: WorkspaceRole | null): WorkspaceRead {
    return {
      id,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: null,
      name: `ws-${id}`,
      is_shareable: false,
      trash_retention_days: 30,
      role,
    };
  }

  function makeCtx(workspaces: WorkspaceRead[]): CurrentWorkspaceContextValue {
    return {
      status: "ready",
      workspaces,
      currentWorkspace: null,
      workspaceId: null,
      role: null,
      isShareable: false,
      selectWorkspace: () => {},
      refresh: async () => {},
    };
  }

  it("마운트 시 서버 role 로 시드한다 (role=null 은 미시드)", () => {
    const seeded = [ws(1, "owner"), ws(2, "member"), ws(3, null)];
    const wrapper = ({ children }: { children: ReactNode }) => (
      <CurrentWorkspaceContext.Provider value={makeCtx(seeded)}>
        <MembershipRoleProvider>{children}</MembershipRoleProvider>
      </CurrentWorkspaceContext.Provider>
    );

    const { result } = renderHook(() => useMembershipRoleSource(), { wrapper });

    expect(result.current.roleFor(1)).toBe(Role.OWNER);
    expect(result.current.roleFor(2)).toBe(Role.MEMBER);
    // role=null 항목은 시드되지 않는다(Req 2.4/5.4).
    expect(result.current.roleFor(3)).toBeNull();
  });

  it("서버 권위 우선: in-session 기록을 재-시드가 덮어쓴다 (Req 5.2)", () => {
    let workspaces: WorkspaceRead[] = [ws(1, "owner")];
    const wrapper = ({ children }: { children: ReactNode }) => (
      <CurrentWorkspaceContext.Provider value={makeCtx(workspaces)}>
        <MembershipRoleProvider>{children}</MembershipRoleProvider>
      </CurrentWorkspaceContext.Provider>
    );

    const { result, rerender } = renderHook(() => useMembershipRoleSource(), {
      wrapper,
    });

    expect(result.current.roleFor(1)).toBe(Role.OWNER);

    // in-session 기록으로 값을 낮춘 뒤,
    act(() => {
      result.current.recordSelfRole(1, Role.MEMBER);
    });
    expect(result.current.roleFor(1)).toBe(Role.MEMBER);

    // 목록 재조회(새 workspaces 배열 참조) → 서버 role 이 덮어쓴다.
    workspaces = [ws(1, "owner")];
    act(() => {
      rerender();
    });
    expect(result.current.roleFor(1)).toBe(Role.OWNER);
  });

  it("비목록 WS 의 in-session 기록은 시드가 건드리지 않는다 (Req 5.3)", () => {
    let workspaces: WorkspaceRead[] = [ws(1, "owner")];
    const wrapper = ({ children }: { children: ReactNode }) => (
      <CurrentWorkspaceContext.Provider value={makeCtx(workspaces)}>
        <MembershipRoleProvider>{children}</MembershipRoleProvider>
      </CurrentWorkspaceContext.Provider>
    );

    const { result, rerender } = renderHook(() => useMembershipRoleSource(), {
      wrapper,
    });

    // 목록에 없는 WS 99 를 in-session 으로 기록.
    act(() => {
      result.current.recordOwner(99);
    });
    expect(result.current.roleFor(99)).toBe(Role.OWNER);

    // 99 를 포함하지 않는 새 목록으로 재-시드해도 99 는 보존된다.
    workspaces = [ws(1, "owner"), ws(2, "member")];
    act(() => {
      rerender();
    });
    expect(result.current.roleFor(99)).toBe(Role.OWNER);
    expect(result.current.roleFor(1)).toBe(Role.OWNER);
    expect(result.current.roleFor(2)).toBe(Role.MEMBER);
  });

  it("시드 후 비목록 WS 에 대한 in-session 기록은 보존된다 (단일 값 공존)", () => {
    const seeded = [ws(1, "owner")];
    const wrapper = ({ children }: { children: ReactNode }) => (
      <CurrentWorkspaceContext.Provider value={makeCtx(seeded)}>
        <MembershipRoleProvider>{children}</MembershipRoleProvider>
      </CurrentWorkspaceContext.Provider>
    );

    const { result } = renderHook(() => useMembershipRoleSource(), { wrapper });

    expect(result.current.roleFor(1)).toBe(Role.OWNER);

    // 방금 생성되어 목록 재조회 이전인 WS 를 in-session 으로 채운다(Req 5.3).
    act(() => {
      result.current.recordOwner(42);
    });
    expect(result.current.roleFor(42)).toBe(Role.OWNER);
    // 시드된 WS 는 여전히 단일 서버값을 노출한다.
    expect(result.current.roleFor(1)).toBe(Role.OWNER);
  });

  it("standalone(컨텍스트 null) 마운트는 시드하지 않고 in-session 전용 동작을 보존한다 (Req 5.1)", () => {
    // CurrentWorkspaceContext.Provider 없이 마운트 → wsContext === null → 시드 없음.
    const { result } = renderHook(() => useMembershipRoleSource(), {
      wrapper: MembershipRoleProvider,
    });

    expect(result.current.roleFor(1)).toBeNull();

    act(() => {
      result.current.recordOwner(1);
    });
    expect(result.current.roleFor(1)).toBe(Role.OWNER);
  });
});
