import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { documentApi } from "./documentApi";
import { apiClient } from "@/shared/api/client";
import type { DocumentRead, Page, TrashBundleRead } from "../types";

// documentApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·바디를 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const getMock = apiClient.get as unknown as Mock;
const postMock = apiClient.post as unknown as Mock;
const patchMock = apiClient.patch as unknown as Mock;
const delMock = apiClient.del as unknown as Mock;

/** 응답으로 반환할 DocumentRead 픽스처. */
function sampleDocument(overrides: Partial<DocumentRead> = {}): DocumentRead {
  return {
    id: 11,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    workspace_id: 3,
    parent_id: null,
    title: "Doc",
    status: "active",
    sort_order: "1000",
    current_version_id: 5,
    created_by: 2,
    content: "# hi",
    content_html: "<h1>hi</h1>",
    ...overrides,
  };
}

/** 문서 목록 응답 Page 픽스처. */
function samplePage(
  items: DocumentRead[],
  total: number,
): Page<DocumentRead> {
  return { items, total };
}

/** 휴지통 묶음 응답 픽스처. */
function sampleTrashBundle(): TrashBundleRead {
  return {
    bundle_id: 42,
    root_document_id: 42,
    root_title: "Trashed Root",
    workspace_id: 3,
    trashed_at: "2026-01-02T00:00:00Z",
    expires_at: "2026-02-01T00:00:00Z",
    member_count: 1,
    members: [{ id: 42, parent_id: null, title: "Trashed Root" }],
  };
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  delMock.mockReset();
});

describe("documentApi.listDocuments", () => {
  it("gets /workspaces/{workspaceId}/documents with limit and offset query", async () => {
    const page = samplePage([sampleDocument()], 1);
    getMock.mockResolvedValueOnce(page);

    const result = await documentApi.listDocuments("ws-1", 20, 40);

    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/ws-1/documents?limit=20&offset=40",
    );
    expect(result).toEqual(page);
  });
});

describe("documentApi.loadAllActiveDocuments", () => {
  it("makes exactly one call when the first page already holds every item", async () => {
    const page = samplePage([sampleDocument({ id: 1 })], 1);
    getMock.mockResolvedValueOnce(page);

    const result = await documentApi.loadAllActiveDocuments("ws-1");

    expect(getMock).toHaveBeenCalledTimes(1);
    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/ws-1/documents?limit=100&offset=0",
    );
    expect(result).toEqual([sampleDocument({ id: 1 })]);
  });

  it("merges multiple pages and advances offset by accumulated item count", async () => {
    const first = samplePage(
      [sampleDocument({ id: 1 }), sampleDocument({ id: 2 })],
      3,
    );
    const second = samplePage([sampleDocument({ id: 3 })], 3);
    getMock.mockResolvedValueOnce(first).mockResolvedValueOnce(second);

    const result = await documentApi.loadAllActiveDocuments("ws-1");

    expect(getMock).toHaveBeenCalledTimes(2);
    expect(getMock).toHaveBeenNthCalledWith(
      1,
      "/workspaces/ws-1/documents?limit=100&offset=0",
    );
    expect(getMock).toHaveBeenNthCalledWith(
      2,
      "/workspaces/ws-1/documents?limit=100&offset=2",
    );
    expect(result.map((d) => d.id)).toEqual([1, 2, 3]);
  });

  it("stops (no infinite loop) when a page returns zero items before total is reached", async () => {
    const empty = samplePage([], 5);
    getMock.mockResolvedValueOnce(empty);

    const result = await documentApi.loadAllActiveDocuments("ws-1");

    expect(getMock).toHaveBeenCalledTimes(1);
    expect(result).toEqual([]);
  });
});

describe("documentApi.getDocument", () => {
  it("gets /documents/{id}", async () => {
    const doc = sampleDocument();
    getMock.mockResolvedValueOnce(doc);

    const result = await documentApi.getDocument(11);

    expect(getMock).toHaveBeenCalledWith("/documents/11");
    expect(result).toEqual(doc);
  });
});

describe("documentApi.createDocument", () => {
  it("posts to /workspaces/{workspaceId}/documents with the create body", async () => {
    const doc = sampleDocument();
    postMock.mockResolvedValueOnce(doc);

    const result = await documentApi.createDocument("ws-1", {
      title: "New",
      parent_id: null,
    });

    expect(postMock).toHaveBeenCalledWith("/workspaces/ws-1/documents", {
      title: "New",
      parent_id: null,
    });
    expect(result).toEqual(doc);
  });
});

describe("documentApi.updateDocument", () => {
  it("patches /documents/{id} with the update body", async () => {
    const doc = sampleDocument();
    patchMock.mockResolvedValueOnce(doc);

    const result = await documentApi.updateDocument(11, { title: "Renamed" });

    expect(patchMock).toHaveBeenCalledWith("/documents/11", {
      title: "Renamed",
    });
    expect(result).toEqual(doc);
  });
});

describe("documentApi.moveDocument", () => {
  it("posts to /documents/{id}/move with the move body", async () => {
    const doc = sampleDocument();
    postMock.mockResolvedValueOnce(doc);

    const result = await documentApi.moveDocument(11, {
      new_parent_id: 7,
      after_sibling_id: 4,
    });

    expect(postMock).toHaveBeenCalledWith("/documents/11/move", {
      new_parent_id: 7,
      after_sibling_id: 4,
    });
    expect(result).toEqual(doc);
  });
});

describe("documentApi.deleteDocument", () => {
  it("deletes /documents/{id} and resolves void", async () => {
    delMock.mockResolvedValueOnce(undefined);

    const result = await documentApi.deleteDocument(11);

    expect(delMock).toHaveBeenCalledWith("/documents/11");
    expect(result).toBeUndefined();
  });
});

describe("documentApi.listTrash", () => {
  it("gets /workspaces/{workspaceId}/trash with limit and offset query", async () => {
    const page: Page<TrashBundleRead> = {
      items: [sampleTrashBundle()],
      total: 1,
    };
    getMock.mockResolvedValueOnce(page);

    const result = await documentApi.listTrash("ws-1", 10, 0);

    expect(getMock).toHaveBeenCalledWith(
      "/workspaces/ws-1/trash?limit=10&offset=0",
    );
    expect(result).toEqual(page);
  });
});

describe("documentApi.restoreBundle", () => {
  it("posts to /trash/{bundleId}/restore and resolves void", async () => {
    postMock.mockResolvedValueOnce(undefined);

    const result = await documentApi.restoreBundle(42);

    expect(postMock).toHaveBeenCalledWith("/trash/42/restore");
    expect(result).toBeUndefined();
  });
});

describe("documentApi.purgeBundle", () => {
  it("deletes /trash/{bundleId} and resolves void", async () => {
    delMock.mockResolvedValueOnce(undefined);

    const result = await documentApi.purgeBundle(42);

    expect(delMock).toHaveBeenCalledWith("/trash/42");
    expect(result).toBeUndefined();
  });
});
