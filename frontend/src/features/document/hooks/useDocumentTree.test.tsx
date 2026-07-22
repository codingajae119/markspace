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
  // 마지막 선택 문서 영속(localStorage)이 테스트 간 누출되지 않도록 초기화한다.
  localStorage.clear();
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

  it("revealAncestors: 새로 생긴 하위 문서의 조상을 모두 펼친다(자기 자신은 제외)", async () => {
    // 초기 1(루트) 만 있고 접힌 상태 → 1 아래 2, 그 아래 3 을 만든 뒤 reload 한 상황.
    loadAllMock.mockResolvedValue([doc(1, null, "a")]);
    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.expandedIds.size).toBe(0);

    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, 1, "a"), doc(3, 2, "a")]);
    await act(async () => {
      await result.current.reload();
    });
    act(() => result.current.revealAncestors(3));

    // 3 을 보이게 하려면 1·2 가 펼쳐져야 한다. 3 자신은 펼칠 필요가 없다.
    expect([...result.current.expandedIds].sort()).toEqual([1, 2]);
  });

  it("revealAncestors: 루트 문서면 펼칠 조상이 없어 확장 집합이 그대로다", async () => {
    loadAllMock.mockResolvedValue([doc(1, null, "a")]);
    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => result.current.revealAncestors(1));

    expect(result.current.expandedIds.size).toBe(0);
  });

  it("reselectAfterRemoval: 선택이 삭제되면 가장 가까운 생존 조상으로 이동한다", async () => {
    // 초기 트리 1→2→3, 3 을 선택한 뒤 3 삭제(reload 는 1,2 만 반환)를 시뮬레이션한다.
    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, 1, "b"), doc(3, 2, "c")]);
    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => result.current.select(3));
    expect(result.current.selectedId).toBe(3);

    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, 1, "b")]);
    await act(async () => {
      await result.current.reload();
    });
    act(() => result.current.reselectAfterRemoval([2, 1]));

    expect(result.current.selectedId).toBe(2);
  });

  it("reselectAfterRemoval: 선택이 살아 있으면(다른 문서 삭제) 선택을 유지한다", async () => {
    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, null, "b")]);
    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => result.current.select(1));
    await act(async () => {
      await result.current.reload();
    });
    // 후보가 있어도 현재 선택(1)이 생존하므로 건드리지 않는다.
    act(() => result.current.reselectAfterRemoval([2]));

    expect(result.current.selectedId).toBe(1);
  });

  it("reselectAfterRemoval: 생존 조상이 없으면(루트 삭제·전부 삭제) null 로 비운다", async () => {
    loadAllMock.mockResolvedValue([doc(1, null, "a")]);
    const { result } = renderHook(() => useDocumentTree());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => result.current.select(1));
    loadAllMock.mockResolvedValue([]);
    await act(async () => {
      await result.current.reload();
    });
    act(() => result.current.reselectAfterRemoval([]));

    expect(result.current.selectedId).toBeNull();
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

  it("마지막 선택 문서를 재마운트 시 복원하고 조상을 펼친다", async () => {
    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, 1, "b"), doc(3, 2, "c")]);

    // 1) 첫 마운트에서 중첩 문서 3 을 선택하면 워크스페이스별로 영속된다.
    const first = renderHook(() => useDocumentTree());
    await waitFor(() => expect(first.result.current.status).toBe("ready"));
    act(() => first.result.current.select(3));
    expect(first.result.current.selectedId).toBe(3);

    // 2) 편집 화면 이동을 모사해 언마운트 후 다시 마운트하면 선택이 복원되고 조상(1·2)이 펼쳐진다.
    first.unmount();
    const second = renderHook(() => useDocumentTree());
    await waitFor(() => expect(second.result.current.selectedId).toBe(3));
    expect(second.result.current.expandedIds.has(1)).toBe(true);
    expect(second.result.current.expandedIds.has(2)).toBe(true);
    // 선택 노드 자신은 펼치지 않는다(자식 없음).
    expect(second.result.current.expandedIds.has(3)).toBe(false);
  });

  it("영속된 마지막 문서가 현재 트리에 없으면 복원하지 않는다", async () => {
    // 워크스페이스 7 에서 문서 42 를 선택해 영속한다(트리에는 42 가 없다).
    loadAllMock.mockResolvedValue([]);
    const first = renderHook(() => useDocumentTree());
    await waitFor(() => expect(first.result.current.status).toBe("ready"));
    act(() => first.result.current.select(42));
    first.unmount();

    // 재마운트 시 트리에는 1·2 만 있으므로 유령 42 는 복원되지 않는다.
    loadAllMock.mockResolvedValue([doc(1, null, "a"), doc(2, 1, "b")]);
    const second = renderHook(() => useDocumentTree());
    await waitFor(() => expect(second.result.current.status).toBe("ready"));
    expect(second.result.current.selectedId).toBeNull();
  });
});
