import { describe, it, expect } from "vitest";

import { Role } from "@/shared/auth/roles";

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
