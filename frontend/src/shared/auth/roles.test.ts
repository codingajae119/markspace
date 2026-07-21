import { describe, it, expect } from "vitest";

import { Role, memberRoleToRole } from "@/shared/auth/roles";
import type { WorkspaceRole } from "@/shared/auth/roles";
import { memberRoleToRole as shimMemberRoleToRole } from "@/features/workspace/context/membershipRoleSource";

describe("Role hierarchy (MEMBER < OWNER — backend Role mirror)", () => {
  it("assigns numeric values so owner ≥ member holds (BE 미러 MEMBER=1<OWNER=2)", () => {
    expect(Role.MEMBER).toBe(1);
    expect(Role.OWNER).toBe(2);
  });

  it("orders numerically OWNER > MEMBER (INV-1 hierarchy)", () => {
    expect(Role.OWNER).toBeGreaterThan(Role.MEMBER);
  });
});

// memberRoleToRole 은 백엔드 role 문자열("owner"|"member")을 s16 Role enum 으로 번역하는
// 단일 소스다(Role enum 과 co-locate). 이 번역 로직은 shared 에만 존재해야 한다.
describe("memberRoleToRole (WorkspaceRole → Role translation, single source)", () => {
  it("translates WorkspaceRole strings to the co-located Role enum", () => {
    expect(memberRoleToRole("owner")).toBe(Role.OWNER);
    expect(memberRoleToRole("member")).toBe(Role.MEMBER);
  });

  it("accepts the WorkspaceRole union values", () => {
    const roles: WorkspaceRole[] = ["owner", "member"];
    expect(roles.map(memberRoleToRole)).toEqual([Role.OWNER, Role.MEMBER]);
  });

  it("features/workspace 재-export shim 이 shared 와 동일 함수를 가리킨다(후방 호환)", () => {
    expect(shimMemberRoleToRole).toBe(memberRoleToRole);
  });
});
