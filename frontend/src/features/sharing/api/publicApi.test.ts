import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { publicApi } from "./publicApi";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type { PublicDocumentRead } from "./types";

// publicApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·옵션을 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

// buildAttachmentUrl 이 base URL 을 재구성하는지 관찰하기 위해 설정 단일 지점을 모킹한다.
vi.mock("@/config", () => ({
  apiConfig: { baseUrl: "http://localhost:8000" },
}));

const getMock = apiClient.get as unknown as Mock;

/** 응답으로 반환할 PublicDocumentRead 픽스처. */
function samplePublicDocument(): PublicDocumentRead {
  return {
    root: {
      id: 1,
      title: "공유 문서",
      content_html: "<p>본문</p>",
      children: [],
    },
  };
}

beforeEach(() => {
  getMock.mockReset();
});

describe("publicApi.getPublicDocument", () => {
  it("gets /public/{token} with skipAuthRedirect and returns PublicDocumentRead", async () => {
    const doc = samplePublicDocument();
    getMock.mockResolvedValueOnce(doc);

    const result = await publicApi.getPublicDocument("tok");

    expect(getMock).toHaveBeenCalledTimes(1);
    const [path, options] = getMock.mock.calls[0];
    expect(path).toBe("/public/tok");
    expect(options).toMatchObject({ skipAuthRedirect: true });
    expect(result).toBe(doc);
  });

  it("propagates ApiError from apiClient without swallowing (404 gone)", async () => {
    const apiError = new ApiError({
      status: 404,
      code: "not_found",
      message: "gone",
    });
    getMock.mockRejectedValueOnce(apiError);

    await expect(publicApi.getPublicDocument("tok")).rejects.toBe(apiError);
  });
});

describe("publicApi.buildAttachmentUrl", () => {
  it("builds an absolute public-serving URL from apiConfig.baseUrl", () => {
    expect(publicApi.buildAttachmentUrl("tok", 5)).toBe(
      "http://localhost:8000/public/tok/attachments/5",
    );
  });

  it("strips a trailing slash on baseUrl so it never emits //public", async () => {
    // 후행 슬래시가 있는 base URL 설정으로 모듈을 격리 재모킹해 이중 슬래시 부재를 관찰한다.
    vi.resetModules();
    vi.doMock("@/config", () => ({
      apiConfig: { baseUrl: "http://localhost:8000/" },
    }));
    vi.doMock("@/shared/api/client", () => ({
      apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
    }));
    try {
      const { publicApi: freshApi } = await import("./publicApi");
      const url = freshApi.buildAttachmentUrl("tok", 5);
      expect(url).toBe("http://localhost:8000/public/tok/attachments/5");
      expect(url).not.toContain("//public");
    } finally {
      vi.doUnmock("@/config");
      vi.doUnmock("@/shared/api/client");
      vi.resetModules();
    }
  });
});
