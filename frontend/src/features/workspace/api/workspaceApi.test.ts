import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { workspaceApi } from "./workspaceApi";
import { apiClient } from "@/shared/api/client";
import type { WorkspaceRead, Page } from "./types";

// workspaceApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·바디를 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const getMock = apiClient.get as unknown as Mock;
const postMock = apiClient.post as unknown as Mock;
const patchMock = apiClient.patch as unknown as Mock;
const delMock = apiClient.del as unknown as Mock;

/** 응답으로 반환할 WorkspaceRead 픽스처. */
function sampleWorkspace(): WorkspaceRead {
  return {
    id: 7,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    name: "WS",
    is_shareable: false,
    trash_retention_days: 30,
  };
}

/** 목록 응답 Page 픽스처. */
function samplePage(): Page<WorkspaceRead> {
  return { items: [sampleWorkspace()], total: 1 };
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  delMock.mockReset();
});

describe("workspaceApi.list", () => {
  it("gets a clean /workspaces path when no limit/offset are provided", async () => {
    const page = samplePage();
    getMock.mockResolvedValueOnce(page);

    const result = await workspaceApi.list();

    expect(getMock).toHaveBeenCalledWith("/workspaces");
    expect(result).toEqual(page);
  });

  it("appends limit and offset as query params when both are provided", async () => {
    getMock.mockResolvedValueOnce(samplePage());

    await workspaceApi.list(20, 40);

    expect(getMock).toHaveBeenCalledWith("/workspaces?limit=20&offset=40");
  });

  it("appends only limit when offset is omitted", async () => {
    getMock.mockResolvedValueOnce(samplePage());

    await workspaceApi.list(20);

    expect(getMock).toHaveBeenCalledWith("/workspaces?limit=20");
  });

  it("appends only offset when limit is omitted", async () => {
    getMock.mockResolvedValueOnce(samplePage());

    await workspaceApi.list(undefined, 40);

    expect(getMock).toHaveBeenCalledWith("/workspaces?offset=40");
  });
});

describe("workspaceApi.create", () => {
  it("posts to /workspaces with the create body and returns the created workspace", async () => {
    const ws = sampleWorkspace();
    postMock.mockResolvedValueOnce(ws);

    const result = await workspaceApi.create({ name: "New WS" });

    expect(postMock).toHaveBeenCalledWith("/workspaces", { name: "New WS" });
    expect(result).toEqual(ws);
  });
});

describe("workspaceApi.get", () => {
  it("gets /workspaces/{id}", async () => {
    const ws = sampleWorkspace();
    getMock.mockResolvedValueOnce(ws);

    const result = await workspaceApi.get(7);

    expect(getMock).toHaveBeenCalledWith("/workspaces/7");
    expect(result).toEqual(ws);
  });
});

describe("workspaceApi.update", () => {
  it("patches /workspaces/{id} with the update body", async () => {
    const ws = sampleWorkspace();
    patchMock.mockResolvedValueOnce(ws);

    const result = await workspaceApi.update(7, { name: "Renamed", is_shareable: true });

    expect(patchMock).toHaveBeenCalledWith("/workspaces/7", {
      name: "Renamed",
      is_shareable: true,
    });
    expect(result).toEqual(ws);
  });
});

describe("workspaceApi.remove", () => {
  it("deletes /workspaces/{id} and resolves void", async () => {
    delMock.mockResolvedValueOnce(undefined);

    const result = await workspaceApi.remove(7);

    expect(delMock).toHaveBeenCalledWith("/workspaces/7");
    expect(result).toBeUndefined();
  });
});
