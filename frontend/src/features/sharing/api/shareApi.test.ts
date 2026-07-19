import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { shareApi } from "./shareApi";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type { ShareLinkRead } from "./types";

// shareApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·메서드·바디를 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const postMock = apiClient.post as unknown as Mock;
const patchMock = apiClient.patch as unknown as Mock;

/** 응답으로 반환할 ShareLinkRead 픽스처. */
function sampleShareLink(overrides: Partial<ShareLinkRead> = {}): ShareLinkRead {
  return {
    id: 42,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    document_id: 11,
    token: "tok_abc",
    is_enabled: true,
    share_url: "/public/tok_abc",
    ...overrides,
  };
}

beforeEach(() => {
  postMock.mockReset();
  patchMock.mockReset();
});

describe("shareApi.issueLink", () => {
  it("posts to /documents/{documentId}/share with no request body", async () => {
    const link = sampleShareLink();
    postMock.mockResolvedValueOnce(link);

    const result = await shareApi.issueLink(11);

    expect(postMock).toHaveBeenCalledTimes(1);
    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/documents/11/share");
    // issueLink 는 요청 본문을 보내지 않는다(POST no-body).
    expect(body).toBeUndefined();
    expect(patchMock).not.toHaveBeenCalled();
    expect(result).toEqual(link);
  });

  it("propagates ApiError from apiClient without swallowing", async () => {
    const apiError = new ApiError({
      status: 409,
      code: "conflict",
      message: "already shared",
    });
    postMock.mockRejectedValueOnce(apiError);

    await expect(shareApi.issueLink(11)).rejects.toBe(apiError);
  });
});

describe("shareApi.toggleLink", () => {
  it("patches /documents/{documentId}/share with the ShareLinkUpdate body", async () => {
    const link = sampleShareLink({ is_enabled: false });
    patchMock.mockResolvedValueOnce(link);

    const result = await shareApi.toggleLink(11, { is_enabled: false });

    expect(patchMock).toHaveBeenCalledTimes(1);
    const [path, body] = patchMock.mock.calls[0];
    expect(path).toBe("/documents/11/share");
    expect(body).toEqual({ is_enabled: false });
    expect(postMock).not.toHaveBeenCalled();
    expect(result).toEqual(link);
  });

  it("propagates ApiError from apiClient without swallowing", async () => {
    const apiError = new ApiError({
      status: 404,
      code: "not_found",
      message: "no document",
    });
    patchMock.mockRejectedValueOnce(apiError);

    await expect(
      shareApi.toggleLink(11, { is_enabled: true }),
    ).rejects.toBe(apiError);
  });
});
