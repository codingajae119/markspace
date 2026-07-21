import { describe, it, expect } from "vitest";

import { Role } from "@/shared/auth/roles";
import { hasWorkspaceRole } from "@/shared/auth/permissions";

describe("hasWorkspaceRole — workspace role gating + admin override (INV-1·2·3)", () => {
  it("passes owner for member-requiring UI (owner ≥ member)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.OWNER, isAdmin: false, minimum: Role.MEMBER }),
    ).toBe(true);
  });

  it("passes when currentRole equals minimum (member meets member)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.MEMBER, isAdmin: false, minimum: Role.MEMBER }),
    ).toBe(true);
  });

  it("denies when currentRole is null and not admin (no role = denied, INV-2)", () => {
    expect(
      hasWorkspaceRole({ currentRole: null, isAdmin: false, minimum: Role.MEMBER }),
    ).toBe(false);
  });

  it("passes admin regardless of role/membership — even null role, highest minimum (INV-3)", () => {
    expect(
      hasWorkspaceRole({ currentRole: null, isAdmin: true, minimum: Role.OWNER }),
    ).toBe(true);
  });

  it("admin override is checked first, independent of currentRole (INV-3)", () => {
    // member role but admin → still passes an owner-requiring gate.
    expect(
      hasWorkspaceRole({ currentRole: Role.MEMBER, isAdmin: true, minimum: Role.OWNER }),
    ).toBe(true);
  });

  it("denies member for owner-requiring UI (member < owner, INV-2)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.MEMBER, isAdmin: false, minimum: Role.OWNER }),
    ).toBe(false);
  });
});
