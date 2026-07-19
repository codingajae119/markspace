import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { attachmentApi } from "./attachmentApi";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type { AttachmentRead } from "../types";

// attachmentApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·바디·옵션을 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const getMock = apiClient.get as unknown as Mock;
const postMock = apiClient.post as unknown as Mock;

/** 응답으로 반환할 AttachmentRead 픽스처. */
function sampleAttachment(overrides: Partial<AttachmentRead> = {}): AttachmentRead {
  return {
    id: 7,
    workspace_id: 3,
    document_id: 11,
    kind: "image",
    original_name: "photo.png",
    is_archived: false,
    created_at: "2026-01-01T00:00:00Z",
    url: "/attachments/7",
    ...overrides,
  };
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

describe("attachmentApi.uploadAttachment", () => {
  it("posts multipart FormData to /documents/{documentId}/attachments with file + fileName + kind", async () => {
    const att = sampleAttachment();
    postMock.mockResolvedValueOnce(att);
    const file = new File(["binary"], "ignored.png", { type: "image/png" });

    const result = await attachmentApi.uploadAttachment(11, file, "photo.png", "image");

    expect(postMock).toHaveBeenCalledTimes(1);
    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/documents/11/attachments");
    expect(body).toBeInstanceOf(FormData);
    const form = body as FormData;
    const sentFile = form.get("file");
    expect(sentFile).toBeInstanceOf(File);
    expect((sentFile as File).name).toBe("photo.png");
    expect(form.get("kind")).toBe("image");
    expect(result).toEqual(att);
  });

  it("omits the kind field when kind is not provided", async () => {
    const att = sampleAttachment({ kind: "file", original_name: "doc.pdf" });
    postMock.mockResolvedValueOnce(att);
    const file = new File(["binary"], "ignored.pdf", { type: "application/pdf" });

    const result = await attachmentApi.uploadAttachment(11, file, "doc.pdf");

    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/documents/11/attachments");
    const form = body as FormData;
    expect((form.get("file") as File).name).toBe("doc.pdf");
    expect(form.get("kind")).toBeNull();
    expect(result).toEqual(att);
  });

  it("propagates ApiError from apiClient without swallowing", async () => {
    const apiError = new ApiError({
      status: 422,
      code: "unprocessable",
      message: "too large",
    });
    postMock.mockRejectedValueOnce(apiError);
    const file = new File(["binary"], "x.png", { type: "image/png" });

    await expect(
      attachmentApi.uploadAttachment(11, file, "x.png", "image"),
    ).rejects.toBe(apiError);
  });
});

describe("attachmentApi.fetchAttachmentBlob", () => {
  it("gets /attachments/{id} with blob response type", async () => {
    const blob = new Blob(["binary"], { type: "image/png" });
    getMock.mockResolvedValueOnce(blob);

    const result = await attachmentApi.fetchAttachmentBlob(7);

    expect(getMock).toHaveBeenCalledWith("/attachments/7", {
      responseType: "blob",
    });
    expect(result).toBe(blob);
  });

  it("propagates ApiError from apiClient without swallowing", async () => {
    const apiError = new ApiError({
      status: 404,
      code: "not_found",
      message: "gone",
    });
    getMock.mockRejectedValueOnce(apiError);

    await expect(attachmentApi.fetchAttachmentBlob(7)).rejects.toBe(apiError);
  });
});
