import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { memberApi } from "./memberApi";
import { apiClient } from "@/shared/api/client";
import type { Page } from "@/shared/types/page";
import type { MemberRead, MemberRosterRow } from "./types";

// memberApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·바디를 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const getMock = apiClient.get as unknown as Mock;
const postMock = apiClient.post as unknown as Mock;
const patchMock = apiClient.patch as unknown as Mock;
const delMock = apiClient.del as unknown as Mock;

/** 응답으로 반환할 MemberRead 픽스처(백엔드 스키마는 타임스탬프 미노출). */
function sampleMember(): MemberRead {
  return {
    id: 3,
    workspace_id: 7,
    user_id: 42,
    role: "member",
  };
}

/** 응답으로 반환할 Page<MemberRosterRow> 픽스처(로스터 스키마: user_id/name/email/role). */
function sampleRosterPage(): Page<MemberRosterRow> {
  return {
    items: [
      { user_id: 42, name: "Alice", email: "alice@example.com", role: "owner" },
      { user_id: 43, name: "Bob", email: null, role: "member" },
    ],
    total: 2,
  };
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  delMock.mockReset();
});

describe("memberApi.add", () => {
  it("posts to /workspaces/{id}/members with the create body and returns the created member", async () => {
    const member = sampleMember();
    postMock.mockResolvedValueOnce(member);

    const result = await memberApi.add(7, { user_id: 42, role: "member" });

    expect(postMock).toHaveBeenCalledWith("/workspaces/7/members", {
      user_id: 42,
      role: "member",
    });
    expect(result).toEqual(member);
  });
});

describe("memberApi.changeRole", () => {
  it("patches /workspaces/{id}/members/{uid} with the update body and returns the updated member", async () => {
    const member = sampleMember();
    patchMock.mockResolvedValueOnce(member);

    const result = await memberApi.changeRole(7, 42, { role: "member" });

    expect(patchMock).toHaveBeenCalledWith("/workspaces/7/members/42", {
      role: "member",
    });
    expect(result).toEqual(member);
  });
});

describe("memberApi.remove", () => {
  it("deletes /workspaces/{id}/members/{uid} and resolves void", async () => {
    delMock.mockResolvedValueOnce(undefined);

    const result = await memberApi.remove(7, 42);

    expect(delMock).toHaveBeenCalledWith("/workspaces/7/members/42");
    expect(result).toBeUndefined();
  });
});

describe("memberApi.list", () => {
  it("defaults to limit=50&offset=0 when no params are given and returns the page", async () => {
    const page = sampleRosterPage();
    getMock.mockResolvedValueOnce(page);

    const result = await memberApi.list(7);

    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/7/members?limit=50&offset=0",
    );
    expect(result).toEqual(page);
  });

  it("builds the query from custom limit/offset", async () => {
    getMock.mockResolvedValueOnce(sampleRosterPage());

    await memberApi.list(3, { limit: 10, offset: 20 });

    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/3/members?limit=10&offset=20",
    );
  });
});
