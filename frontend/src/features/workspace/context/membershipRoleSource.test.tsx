import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";

import {
  MembershipRoleProvider,
  useMembershipRoleSource,
  memberRoleToRole,
} from "./membershipRoleSource";
import { Role } from "@/shared/auth/roles";

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
      result.current.recordSelfRole(7, Role.EDITOR);
    });
    expect(result.current.roleFor(7)).toBe(Role.EDITOR);
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
      result.current.recordSelfRole(3, Role.VIEWER);
    });

    expect(result.current.roleFor(3)).toBe(Role.VIEWER);
  });

  it("memberRoleToRole 은 MemberRole 문자열을 s16 Role enum 으로 번역한다", () => {
    expect(memberRoleToRole("owner")).toBe(Role.OWNER);
    expect(memberRoleToRole("editor")).toBe(Role.EDITOR);
    expect(memberRoleToRole("viewer")).toBe(Role.VIEWER);
  });

  it("useMembershipRoleSource() 를 provider 밖에서 호출하면 오류를 던진다", () => {
    expect(() => renderHook(() => useMembershipRoleSource())).toThrow(
      /MembershipRoleProvider/,
    );
  });
});
