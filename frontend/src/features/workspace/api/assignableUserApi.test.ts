import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { assignableUserApi } from "./assignableUserApi";
import { apiClient } from "@/shared/api/client";
import type { Page } from "@/shared/types/page";
import type { AssignableUser } from "./types";

// assignableUserApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로를 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const getMock = apiClient.get as unknown as Mock;

/** 응답으로 반환할 Page<AssignableUser> 픽스처(narrow 스키마: id/name/email). */
function samplePage(): Page<AssignableUser> {
  return {
    items: [
      { id: 11, name: "Alice", email: "alice@example.com" },
      { id: 12, name: "Bob", email: null },
    ],
    total: 2,
  };
}

beforeEach(() => {
  getMock.mockReset();
});

describe("assignableUserApi.listAssignable", () => {
  it("gets /workspaces/{id}/assignable-users with explicit limit/offset and returns the page", async () => {
    const page = samplePage();
    getMock.mockResolvedValueOnce(page);

    const result = await assignableUserApi.listAssignable(1, {
      limit: 50,
      offset: 0,
    });

    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/1/assignable-users?limit=50&offset=0",
    );
    expect(result).toEqual(page);
  });

  it("defaults to limit=50&offset=0 when no params are given", async () => {
    const page = samplePage();
    getMock.mockResolvedValueOnce(page);

    await assignableUserApi.listAssignable(7);

    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/7/assignable-users?limit=50&offset=0",
    );
  });

  it("builds the query from custom limit/offset", async () => {
    getMock.mockResolvedValueOnce(samplePage());

    await assignableUserApi.listAssignable(3, { limit: 10, offset: 20 });

    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/3/assignable-users?limit=10&offset=20",
    );
  });
});
