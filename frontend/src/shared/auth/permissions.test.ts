import { describe, it, expect } from "vitest";

import { Role } from "@/shared/auth/roles";
import { hasWorkspaceRole } from "@/shared/auth/permissions";

describe("hasWorkspaceRole — workspace role gating + admin override (INV-1·2·3)", () => {
  it("denies viewer for editor-requiring UI (INV-2: viewer < editor)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.VIEWER, isAdmin: false, minimum: Role.EDITOR }),
    ).toBe(false);
  });

  it("passes owner for editor-requiring UI (owner ≥ editor)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.OWNER, isAdmin: false, minimum: Role.EDITOR }),
    ).toBe(true);
  });

  it("passes when currentRole equals minimum (editor meets editor)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.EDITOR, isAdmin: false, minimum: Role.EDITOR }),
    ).toBe(true);
  });

  it("denies when currentRole is null and not admin (no role = denied, INV-2)", () => {
    expect(
      hasWorkspaceRole({ currentRole: null, isAdmin: false, minimum: Role.VIEWER }),
    ).toBe(false);
  });

  it("passes admin regardless of role/membership — even null role, highest minimum (INV-3)", () => {
    expect(
      hasWorkspaceRole({ currentRole: null, isAdmin: true, minimum: Role.OWNER }),
    ).toBe(true);
  });

  it("admin override is checked first, independent of currentRole (INV-3)", () => {
    // viewer role but admin → still passes an owner-requiring gate.
    expect(
      hasWorkspaceRole({ currentRole: Role.VIEWER, isAdmin: true, minimum: Role.OWNER }),
    ).toBe(true);
  });

  it("passes viewer for viewer-requiring UI (viewer meets viewer)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.VIEWER, isAdmin: false, minimum: Role.VIEWER }),
    ).toBe(true);
  });

  it("denies editor for owner-requiring UI (editor < owner, INV-2)", () => {
    expect(
      hasWorkspaceRole({ currentRole: Role.EDITOR, isAdmin: false, minimum: Role.OWNER }),
    ).toBe(false);
  });
});
