import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useDocumentTree } from "./useDocumentTree";
import { documentApi } from "../api/documentApi";
import { useDocumentScope } from "./useDocumentScope";
import type { DocumentRead, DocumentNode } from "../types";
import { ApiError } from "@/shared/api/errors";
import { Role } from "@/shared/auth/roles";

/**
 * useDocumentTree 는 s16 스코프(useDocumentScope.workspaceId)에서 전체 활성 문서를 로드하고
 * buildTree/resolveAncestors 로 트리·조상을 파생하며 선택/확장/낙관적 반영 seam 을 노출한다.
 * 협력자(documentApi·useDocumentScope)를 모킹해 로드 상태전이·선택·확장·조상·reload·낙관 반영만
 * 관찰한다 (Requirements 1.1~1.7, 2.1~2.4, 7.1).
 */
vi.mock("../api/documentApi", () => ({
  documentApi: {
    loadAllActiveDocuments: vi.fn(),
  },
}));
vi.mock("./useDocumentScope", () => ({
  useDocumentScope: vi.fn(),
}));

const loadAllMock = documentApi.loadAllActiveDocuments as unknown as Mock;
const useDocumentScopeMock = useDocumentScope as unknown as Mock;

function doc(
  id: number,
  parentId: number | null,
  sortOrder: string,
  title = `doc-${id}`,
): DocumentRead {
  return {
    id,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    workspace_id: 7,
    parent_id: parentId,
    title,
    status: "active",
    sort_order: sortOrder,
    current_version_id: null,
    created_by: 1,
    content: "",
    content_html: "",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentScopeMock.mockReturnValue({
    status: "ready",
    workspaceId: "7",
    role: Role.MEMBER,
    isAdmin: false,
  });
  loadAllMock.mockResolvedValue([]);
});

describe("useDocumentTree", () => {
  it("성공 로드 시 status=ready, roots·nodeById 가 mocked docs 로 조립된다", async () => {
    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, 1, "b")]);

    const { result } = renderHook(() => useDocumentTree());

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(loadAllMock).toHaveBeenCalledWith("7");
    expect(result.current.roots).toHaveLength(1);
    expect(result.current.roots[0].doc.id).toBe(1);
    expect(result.current.roots[0].children[0].doc.id).toBe(2);
    expect(result.current.nodeById.get(1)?.doc.id).toBe(1);
    expect(result.current.nodeById.get(2)?.doc.id).toBe(2);
    expect(result.current.error).toBeNull();
  });

  it("로드 실패(ApiError) 시 status=error, error 에 그 ApiError 를 보존한다", async () => {
    const apiError = new ApiError({
      status: 500,
      code: "internal",
      message: "boom",
    });
    loadAllMock.mockRejectedValue(apiError);

    const { result } = renderHook(() => useDocumentTree());

    await waitFor(() => expect(result.current.status).toBe("error"));

    expect(result.current.error).toBe(apiError);
    expect(result.current.roots).toEqual([]);
  });

  it("빈 워크스페이스(빈 배열 로드) 시 status=ready, roots=[]", async () => {
    loadAllMock.mockResolvedValue([]);

    const { result } = renderHook(() => useDocumentTree());

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.roots).toEqual([]);
    expect(result.current.nodeById.size).toBe(0);
  });

  it("select/toggleExpand 이 selectedId·expandedIds 를 갱신한다", async () => {
    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => result.current.select(42));
    expect(result.current.selectedId).toBe(42);

    act(() => result.current.select(null));
    expect(result.current.selectedId).toBeNull();

    act(() => result.current.toggleExpand(5));
    expect(result.current.expandedIds.has(5)).toBe(true);

    act(() => result.current.toggleExpand(5));
    expect(result.current.expandedIds.has(5)).toBe(false);
  });

  it("ancestorsOf 가 중첩 노드의 root→current 경로를 반환한다", async () => {
    loadAllMock.mockResolvedValue([
      doc(1, null, "a"),
      doc(2, 1, "b"),
      doc(3, 2, "c"),
    ]);

    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    const path = result.current.ancestorsOf(3);
    expect(path.map((d) => d.id)).toEqual([1, 2, 3]);
  });

  it("reload 가 loadAllActiveDocuments 를 재호출한다", async () => {
    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(loadAllMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.reload();
    });

    expect(loadAllMock).toHaveBeenCalledTimes(2);
  });

  it("workspaceId 가 null 이면 API 를 호출하지 않고 status=ready, roots=[]", async () => {
    useDocumentScopeMock.mockReturnValue({
      status: "empty",
      workspaceId: null,
      role: null,
      isAdmin: false,
    });

    const { result } = renderHook(() => useDocumentTree());

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(loadAllMock).not.toHaveBeenCalled();
    expect(result.current.roots).toEqual([]);
    expect(result.current.nodeById.size).toBe(0);
  });

  it("applyLocal(patch) 가 roots 를 낙관적으로 대체하고 applyLocal(null) 이 로드 스냅샷으로 복원한다", async () => {
    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, 1, "b")]);

    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.roots[0].doc.id).toBe(1);

    const patchNode: DocumentNode = {
      doc: doc(99, null, "z", "optimistic"),
      children: [{ doc: doc(100, 99, "z1"), children: [] }],
    };

    act(() => result.current.applyLocal([patchNode]));

    expect(result.current.roots).toHaveLength(1);
    expect(result.current.roots[0].doc.id).toBe(99);
    expect(result.current.nodeById.get(99)?.doc.id).toBe(99);
    expect(result.current.nodeById.get(100)?.doc.id).toBe(100);
    // 낙관 반영 중 조상 파생도 새 맵으로 일관되어야 한다.
    expect(result.current.ancestorsOf(100).map((d) => d.id)).toEqual([99, 100]);

    act(() => result.current.applyLocal(null));

    expect(result.current.roots[0].doc.id).toBe(1);
    expect(result.current.nodeById.get(99)).toBeUndefined();
    expect(result.current.nodeById.get(1)?.doc.id).toBe(1);
  });
});
