import { describe, it, expect } from "vitest";

import { Role, memberRoleToRole } from "@/shared/auth/roles";
import type { WorkspaceRole } from "@/shared/auth/roles";
import { memberRoleToRole as shimMemberRoleToRole } from "@/features/workspace/context/membershipRoleSource";

describe("Role hierarchy (VIEWER < EDITOR < OWNER — backend Role mirror)", () => {
  it("assigns ascending numeric values so owner ≥ editor ≥ viewer holds", () => {
    expect(Role.VIEWER).toBe(1);
    expect(Role.EDITOR).toBe(2);
    expect(Role.OWNER).toBe(3);
  });

  it("orders numerically OWNER > EDITOR > VIEWER (INV-1 hierarchy)", () => {
    expect(Role.OWNER).toBeGreaterThan(Role.EDITOR);
    expect(Role.EDITOR).toBeGreaterThan(Role.VIEWER);
  });
});

// memberRoleToRole 은 백엔드 role 문자열("owner"|"editor"|"viewer")을 s16 Role enum 으로
// 번역하는 단일 소스다(Role enum 과 co-locate). 이 번역 로직은 shared 에만 존재해야 한다.
describe("memberRoleToRole (WorkspaceRole → Role translation, single source)", () => {
  it("translates WorkspaceRole strings to the co-located Role enum", () => {
    expect(memberRoleToRole("owner")).toBe(Role.OWNER);
    expect(memberRoleToRole("editor")).toBe(Role.EDITOR);
    expect(memberRoleToRole("viewer")).toBe(Role.VIEWER);
  });

  it("accepts the WorkspaceRole union values", () => {
    const roles: WorkspaceRole[] = ["owner", "editor", "viewer"];
    expect(roles.map(memberRoleToRole)).toEqual([Role.OWNER, Role.EDITOR, Role.VIEWER]);
  });

  it("features/workspace 재-export shim 이 shared 와 동일 함수를 가리킨다(후방 호환)", () => {
    expect(shimMemberRoleToRole).toBe(memberRoleToRole);
  });
});
