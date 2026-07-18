import { describe, it, expect, expectTypeOf } from "vitest";

import type { Page } from "@/shared/types/page";
import type { WorkspaceRead } from "@/shared/types/workspace";

describe("Page<T> envelope type", () => {
  it("has EXACTLY items and total (no limit/offset) — backend base.py mirror", () => {
    expectTypeOf<Page<number>>().toEqualTypeOf<{ items: number[]; total: number }>();
    expectTypeOf<Page<number>>().not.toHaveProperty("limit");
    expectTypeOf<Page<number>>().not.toHaveProperty("offset");
  });

  it("is generic — items is T[]", () => {
    expectTypeOf<Page<WorkspaceRead>>().toHaveProperty("items").toEqualTypeOf<WorkspaceRead[]>();
    expectTypeOf<Page<WorkspaceRead>>().toHaveProperty("total").toEqualTypeOf<number>();
  });
});

describe("WorkspaceRead type", () => {
  it("mirrors the backend WorkspaceRead schema field-for-field", () => {
    expectTypeOf<WorkspaceRead>().toEqualTypeOf<{
      id: number;
      created_at: string;
      updated_at: string | null;
      name: string;
      is_shareable: boolean;
      trash_retention_days: number;
    }>();
  });

  it("has each field with the correct type and nullability", () => {
    expectTypeOf<WorkspaceRead>().toHaveProperty("id").toEqualTypeOf<number>();
    expectTypeOf<WorkspaceRead>().toHaveProperty("created_at").toEqualTypeOf<string>();
    expectTypeOf<WorkspaceRead>().toHaveProperty("updated_at").toEqualTypeOf<string | null>();
    expectTypeOf<WorkspaceRead>().toHaveProperty("name").toEqualTypeOf<string>();
    expectTypeOf<WorkspaceRead>().toHaveProperty("is_shareable").toEqualTypeOf<boolean>();
    expectTypeOf<WorkspaceRead>().toHaveProperty("trash_retention_days").toEqualTypeOf<number>();
  });
});

describe("Page<WorkspaceRead> runtime usability", () => {
  it("constructs a usable page literal", () => {
    const page: Page<WorkspaceRead> = {
      items: [
        {
          id: 1,
          created_at: "2026-07-18T00:00:00Z",
          updated_at: null,
          name: "My Workspace",
          is_shareable: false,
          trash_retention_days: 30,
        },
      ],
      total: 1,
    };

    expect(page.total).toBe(1);
    expect(page.items.length).toBe(1);
    expect(page.items[0].name).toBe("My Workspace");
  });
});
