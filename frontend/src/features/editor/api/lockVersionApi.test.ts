import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { lockVersionApi } from "./lockVersionApi";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";
import type {
  DocumentLockRead,
  DocumentVersionRead,
  EditableDocument,
  Page,
} from "../types";

// lockVersionApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·바디를 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const getMock = apiClient.get as unknown as Mock;
const postMock = apiClient.post as unknown as Mock;
const delMock = apiClient.del as unknown as Mock;

/** 잠금 응답 픽스처. */
function sampleLock(overrides: Partial<DocumentLockRead> = {}): DocumentLockRead {
  return {
    document_id: 11,
    lock_user_id: 2,
    lock_acquired_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** 편집용 문서 상세 픽스처. */
function sampleEditable(
  overrides: Partial<EditableDocument> = {},
): EditableDocument {
  return {
    id: 11,
    workspace_id: 3,
    title: "Doc",
    content: "# hi",
    current_version_id: 5,
    ...overrides,
  };
}

/** 버전 메타 픽스처. */
function sampleVersion(
  overrides: Partial<DocumentVersionRead> = {},
): DocumentVersionRead {
  return {
    id: 5,
    document_id: 11,
    created_by: 2,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  delMock.mockReset();
});

describe("lockVersionApi.lockDocument", () => {
  it("posts to /documents/{id}/lock (no body) and returns the DocumentLockRead", async () => {
    const lock = sampleLock();
    postMock.mockResolvedValueOnce(lock);

    const result = await lockVersionApi.lockDocument(11);

    expect(postMock).toHaveBeenCalledWith("/documents/11/lock");
    expect(result).toEqual(lock);
  });

  it("propagates an ApiError from apiClient as-is (409 conflict)", async () => {
    const err = new ApiError({
      status: 409,
      code: "conflict",
      message: "잠금 충돌",
    });
    postMock.mockRejectedValueOnce(err);

    await expect(lockVersionApi.lockDocument(11)).rejects.toBe(err);
  });
});

describe("lockVersionApi.getDocument", () => {
  it("gets /documents/{id} for the edit initial content", async () => {
    const doc = sampleEditable();
    getMock.mockResolvedValueOnce(doc);

    const result = await lockVersionApi.getDocument(11);

    expect(getMock).toHaveBeenCalledWith("/documents/11");
    expect(result).toEqual(doc);
  });
});

describe("lockVersionApi.saveDocument", () => {
  it("posts to /documents/{id}/save with the save body and returns DocumentVersionRead", async () => {
    const version = sampleVersion();
    postMock.mockResolvedValueOnce(version);

    const result = await lockVersionApi.saveDocument(11, { content: "# new" });

    expect(postMock).toHaveBeenCalledWith("/documents/11/save", {
      content: "# new",
    });
    expect(result).toEqual(version);
  });

  it("passes an empty-string content body through unchanged (empty document save)", async () => {
    const version = sampleVersion();
    postMock.mockResolvedValueOnce(version);

    await lockVersionApi.saveDocument(11, { content: "" });

    expect(postMock).toHaveBeenCalledWith("/documents/11/save", {
      content: "",
    });
  });

  it("propagates an ApiError from apiClient as-is (409 lost lock)", async () => {
    const err = new ApiError({
      status: 409,
      code: "conflict",
      message: "잠금 상실",
    });
    postMock.mockRejectedValueOnce(err);

    await expect(
      lockVersionApi.saveDocument(11, { content: "# x" }),
    ).rejects.toBe(err);
  });
});

describe("lockVersionApi.cancelEdit", () => {
  it("posts to /documents/{id}/cancel (no body) and resolves void", async () => {
    postMock.mockResolvedValueOnce(undefined);

    const result = await lockVersionApi.cancelEdit(11);

    expect(postMock).toHaveBeenCalledWith("/documents/11/cancel");
    expect(result).toBeUndefined();
  });
});

describe("lockVersionApi.forceUnlock", () => {
  it("posts to /documents/{id}/force-unlock (no body) and resolves void", async () => {
    postMock.mockResolvedValueOnce(undefined);

    const result = await lockVersionApi.forceUnlock(11);

    expect(postMock).toHaveBeenCalledWith("/documents/11/force-unlock");
    expect(result).toBeUndefined();
  });

  it("propagates an ApiError from apiClient as-is (403 forbidden)", async () => {
    const err = new ApiError({
      status: 403,
      code: "forbidden",
      message: "권한 없음",
    });
    postMock.mockRejectedValueOnce(err);

    await expect(lockVersionApi.forceUnlock(11)).rejects.toBe(err);
  });
});

describe("lockVersionApi.listVersions", () => {
  it("gets /documents/{id}/versions with limit and offset query", async () => {
    const page: Page<DocumentVersionRead> = {
      items: [sampleVersion()],
      total: 1,
    };
    getMock.mockResolvedValueOnce(page);

    const result = await lockVersionApi.listVersions(11, 50, 0);

    expect(getMock).toHaveBeenCalledWith(
      "/documents/11/versions?limit=50&offset=0",
    );
    expect(result).toEqual(page);
  });

  it("encodes non-default limit/offset into the query string", async () => {
    const page: Page<DocumentVersionRead> = { items: [], total: 3 };
    getMock.mockResolvedValueOnce(page);

    await lockVersionApi.listVersions(7, 20, 40);

    expect(getMock).toHaveBeenCalledWith(
      "/documents/7/versions?limit=20&offset=40",
    );
  });
});
