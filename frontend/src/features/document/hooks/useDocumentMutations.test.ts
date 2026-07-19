import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useDocumentMutations } from "./useDocumentMutations";
import type { useDocumentTree } from "./useDocumentTree";
import { documentApi } from "../api/documentApi";
import { buildTree } from "../lib/buildTree";
import type { DocumentRead, DocumentNode, DropPosition } from "../types";
import { ApiError } from "@/shared/api/errors";

/**
 * useDocumentMutations 는 생성·이름변경·삭제·이동을 낙관 반영→확정/복원으로 오케스트레이션하고
 * 실패 시 raw ApiError 를 그대로 표면화한다. tree 는 파라미터로 주입되므로 vi.fn() 스파이
 * (reload·select·applyLocal)와 실제 nodeById/roots 픽스처를 가진 mock tree 를 넘겨 관찰한다.
 * documentApi 는 모킹한다 (Requirements 3.3~3.5, 4.2~4.4, 5.2·5.4·5.5, 6.3~6.5, 9.4).
 */
vi.mock("../api/documentApi", () => ({
  documentApi: {
    createDocument: vi.fn(),
    updateDocument: vi.fn(),
    deleteDocument: vi.fn(),
    moveDocument: vi.fn(),
  },
}));

const createMock = documentApi.createDocument as unknown as Mock;
const updateMock = documentApi.updateDocument as unknown as Mock;
const deleteMock = documentApi.deleteDocument as unknown as Mock;
const moveMock = documentApi.moveDocument as unknown as Mock;

type Tree = ReturnType<typeof useDocumentTree>;
type MockTree = Tree & { reload: Mock; select: Mock; applyLocal: Mock };

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

/** ReturnType<typeof useDocumentTree> 형태를 만족하는 mock tree(스파이 + 실제 트리 파생). */
function makeTree(docs: DocumentRead[]): MockTree {
  const { roots, nodeById } = buildTree(docs);
  const tree: Tree = {
    status: "ready",
    roots,
    nodeById,
    error: null,
    selectedId: null,
    expandedIds: new Set<number>(),
    reload: vi.fn().mockResolvedValue(undefined),
    select: vi.fn(),
    toggleExpand: vi.fn(),
    ancestorsOf: vi.fn().mockReturnValue([]),
    applyLocal: vi.fn(),
  };
  return tree as MockTree;
}

/** roots 트리에서 id 로 노드를 깊이 우선 탐색한다(낙관 반영 검증용). */
function findNode(roots: DocumentNode[], id: number): DocumentNode | null {
  const stack = [...roots];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === undefined) {
      break;
    }
    if (node.doc.id === id) {
      return node;
    }
    stack.push(...node.children);
  }
  return null;
}

/** 외부에서 resolve/reject 를 제어하는 지연 프라미스. */
function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useDocumentMutations", () => {
  it("create 성공 → createDocument({title,parent_id}) 호출·reload·select(newId)·DocumentRead 반환", async () => {
    const tree = makeTree([doc(1, null, "a")]);
    const created = doc(10, null, "b", "새 문서");
    createMock.mockResolvedValue(created);

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned: DocumentRead | null = null;
    await act(async () => {
      returned = await result.current.create({ title: "새 문서", parentId: null });
    });

    expect(createMock).toHaveBeenCalledWith("7", { title: "새 문서", parent_id: null });
    expect(tree.reload).toHaveBeenCalledTimes(1);
    expect(tree.select).toHaveBeenCalledWith(10);
    expect(returned).toBe(created);
    expect(result.current.state.error).toBeNull();
  });

  it("create 오류(ApiError) → state.error 에 그 ApiError, null 반환, reload 미호출", async () => {
    const tree = makeTree([doc(1, null, "a")]);
    const apiError = new ApiError({ status: 422, code: "validation_error", message: "bad" });
    createMock.mockRejectedValue(apiError);

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned: DocumentRead | null = doc(0, null, "x");
    await act(async () => {
      returned = await result.current.create({ title: "", parentId: null });
    });

    expect(returned).toBeNull();
    expect(result.current.state.error).toBe(apiError);
    expect(tree.reload).not.toHaveBeenCalled();
    expect(tree.select).not.toHaveBeenCalled();
  });

  it("rename 낙관 반영 → applyLocal 에 새 title 클론 전달, 성공 시 유지·DocumentRead 반환", async () => {
    const tree = makeTree([doc(1, null, "a", "old")]);
    const updated = doc(1, null, "a", "new");
    updateMock.mockResolvedValue(updated);

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned: DocumentRead | null = null;
    await act(async () => {
      returned = await result.current.rename(1, "new");
    });

    expect(updateMock).toHaveBeenCalledWith(1, { title: "new" });
    const optimistic = tree.applyLocal.mock.calls[0][0] as DocumentNode[] | null;
    expect(optimistic).not.toBeNull();
    expect(findNode(optimistic as DocumentNode[], 1)?.doc.title).toBe("new");
    // 성공 시 복원(null)하지 않는다.
    expect(tree.applyLocal).toHaveBeenCalledTimes(1);
    expect(returned).toBe(updated);
    expect(result.current.state.error).toBeNull();
  });

  it("rename 오류(ApiError) → applyLocal(null) 복원 + state.error, null 반환", async () => {
    const tree = makeTree([doc(1, null, "a", "old")]);
    const apiError = new ApiError({ status: 404, code: "not_found", message: "gone" });
    updateMock.mockRejectedValue(apiError);

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned: DocumentRead | null = doc(0, null, "x");
    await act(async () => {
      returned = await result.current.rename(1, "new");
    });

    expect(tree.applyLocal).toHaveBeenNthCalledWith(1, expect.any(Array));
    expect(tree.applyLocal).toHaveBeenNthCalledWith(2, null);
    expect(returned).toBeNull();
    expect(result.current.state.error).toBe(apiError);
  });

  it("remove 성공(204) → deleteDocument 호출·reload·true 반환", async () => {
    const tree = makeTree([doc(1, null, "a")]);
    deleteMock.mockResolvedValue(undefined);

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned = false;
    await act(async () => {
      returned = await result.current.remove(1);
    });

    expect(deleteMock).toHaveBeenCalledWith(1);
    expect(tree.reload).toHaveBeenCalledTimes(1);
    expect(returned).toBe(true);
    expect(result.current.state.error).toBeNull();
  });

  it("remove 오류(409 ApiError) → state.error 설정, false 반환, reload 미호출", async () => {
    const tree = makeTree([doc(1, null, "a")]);
    const apiError = new ApiError({ status: 409, code: "conflict", message: "not active" });
    deleteMock.mockRejectedValue(apiError);

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned = true;
    await act(async () => {
      returned = await result.current.remove(1);
    });

    expect(returned).toBe(false);
    expect(result.current.state.error).toBe(apiError);
    expect(tree.reload).not.toHaveBeenCalled();
  });

  it("move 성공 → computeMoveTarget 본문으로 moveDocument, 낙관 applyLocal→reload, DocumentRead 반환", async () => {
    const tree = makeTree([doc(1, null, "a"), doc(2, null, "b"), doc(3, 1, "c")]);
    const moved = doc(3, 2, "c");
    moveMock.mockResolvedValue(moved);
    const drop: DropPosition = { kind: "inside", targetId: 2 };

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned: DocumentRead | null = null;
    await act(async () => {
      returned = await result.current.move(3, drop);
    });

    expect(moveMock).toHaveBeenCalledWith(3, { new_parent_id: 2 });
    // 낙관 반영: node 3 이 새 부모 2 아래로 재배치된 클론이 전달된다.
    const optimistic = tree.applyLocal.mock.calls[0][0] as DocumentNode[] | null;
    expect(optimistic).not.toBeNull();
    expect(findNode(optimistic as DocumentNode[], 2)?.children.some((c) => c.doc.id === 3)).toBe(true);
    expect(tree.reload).toHaveBeenCalledTimes(1);
    expect(returned).toBe(moved);
    expect(result.current.state.error).toBeNull();
  });

  it("move 오류(409/422 ApiError) → applyLocal(null) 복원 + state.error, null 반환", async () => {
    const tree = makeTree([doc(1, null, "a"), doc(2, null, "b"), doc(3, 1, "c")]);
    const apiError = new ApiError({ status: 409, code: "conflict", message: "cycle" });
    moveMock.mockRejectedValue(apiError);
    const drop: DropPosition = { kind: "inside", targetId: 3 };

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    let returned: DocumentRead | null = doc(0, null, "x");
    await act(async () => {
      returned = await result.current.move(3, drop);
    });

    expect(tree.applyLocal).toHaveBeenNthCalledWith(1, expect.any(Array));
    expect(tree.applyLocal).toHaveBeenNthCalledWith(2, null);
    expect(tree.reload).not.toHaveBeenCalled();
    expect(returned).toBeNull();
    expect(result.current.state.error).toBe(apiError);
  });

  it("state.pending 은 변이 진행 중 true, 완료 후 false 로 토글된다", async () => {
    const tree = makeTree([doc(1, null, "a")]);
    const gate = deferred<DocumentRead>();
    createMock.mockReturnValue(gate.promise);

    const { result } = renderHook(() => useDocumentMutations(tree, "7"));

    expect(result.current.state.pending).toBe(false);

    let pendingCall!: Promise<DocumentRead | null>;
    act(() => {
      pendingCall = result.current.create({ title: "x", parentId: null });
    });
    // 진행 중.
    expect(result.current.state.pending).toBe(true);

    await act(async () => {
      gate.resolve(doc(10, null, "b"));
      await pendingCall;
    });
    // 완료 후.
    expect(result.current.state.pending).toBe(false);
  });
});
