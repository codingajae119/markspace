import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";

import { DocumentTree } from "./DocumentTree";
import type { UseDocumentTreeResult } from "../hooks/useDocumentTree";
import type { DocumentNode, DocumentRead } from "../types";

// DocumentTree/DocumentTreeNode 는 useDocumentTree 결과 객체(상태+액션)를 prop 으로 소비한다.
// 훅을 직접 호출하지 않으므로 mock tree 로 펼침/접힘·선택·DnD 를 관찰한다.
// Requirements: 1.3, 1.4, 1.5, 1.6, 6.1, 6.3, 6.7

function makeDoc(partial: Partial<DocumentRead> & { id: number; title: string }): DocumentRead {
  return {
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    workspace_id: 1,
    parent_id: null,
    status: "active",
    sort_order: "1",
    current_version_id: null,
    created_by: 1,
    content: "",
    content_html: "",
    ...partial,
  };
}

function node(doc: DocumentRead, children: DocumentNode[] = []): DocumentNode {
  return { doc, children };
}

// fixture: A(1) → [ B(2) → [ D(4) ], C(3) ]
function fixtureRoots(): DocumentNode[] {
  const d = node(makeDoc({ id: 4, title: "D", parent_id: 2 }));
  const b = node(makeDoc({ id: 2, title: "B", parent_id: 1 }), [d]);
  const c = node(makeDoc({ id: 3, title: "C", parent_id: 1 }));
  const a = node(makeDoc({ id: 1, title: "A" }), [b, c]);
  return [a];
}

function makeTree(partial: Partial<UseDocumentTreeResult> = {}): UseDocumentTreeResult {
  return {
    status: "ready",
    roots: fixtureRoots(),
    nodeById: new Map<number, DocumentNode>(),
    error: null,
    selectedId: null,
    expandedIds: new Set<number>(),
    reload: vi.fn<() => Promise<void>>(async () => {}),
    select: vi.fn<(id: number | null) => void>(),
    toggleExpand: vi.fn<(id: number) => void>(),
    ancestorsOf: vi.fn<(id: number) => DocumentRead[]>(() => []),
    applyLocal: vi.fn<(patch: DocumentNode[] | null) => void>(),
    revealAncestors: vi.fn<(id: number) => void>(),
    reselectAfterRemoval: vi.fn<(candidateIdsNearestFirst: number[]) => void>(),
    ...partial,
  };
}

// jsdom 은 실제 DataTransfer 가 없으므로 문자열을 저장/반환하는 스텁으로 dragId 를 dragStart→drop 에 통과시킨다.
function makeDataTransfer(id: string): {
  setData: ReturnType<typeof vi.fn>;
  getData: ReturnType<typeof vi.fn>;
  effectAllowed: string;
  dropEffect: string;
} {
  const store: Record<string, string> = { "text/plain": id };
  return {
    setData: vi.fn((type: string, value: string) => {
      store[type] = value;
    }),
    getData: vi.fn((type: string) => store[type] ?? ""),
    effectAllowed: "",
    dropEffect: "",
  };
}

describe("DocumentTree / DocumentTreeNode", () => {
  it("다층 roots 의 제목을 렌더하고, 자식은 펼쳐졌을 때만 보인다 (Req 1.3, 1.6)", () => {
    const { rerender } = render(
      <DocumentTree tree={makeTree({ expandedIds: new Set([1]) })} canEdit={false} onMove={vi.fn()} />,
    );

    // A 펼침 → B, C 보임. B 미펼침 → D 미노출.
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
    expect(screen.queryByText("D")).toBeNull();

    // B 도 펼치면 D 노출.
    rerender(
      <DocumentTree tree={makeTree({ expandedIds: new Set([1, 2]) })} canEdit={false} onMove={vi.fn()} />,
    );
    expect(screen.getByText("D")).toBeTruthy();
  });

  it("최상위만 펼침 없이 렌더하면 자식은 숨는다 (Req 1.3)", () => {
    render(<DocumentTree tree={makeTree()} canEdit={false} onMove={vi.fn()} />);
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.queryByText("B")).toBeNull();
    expect(screen.queryByText("C")).toBeNull();
  });

  it("노드 라벨 클릭 시 select(id) 를 호출하고 선택은 aria-selected 로 반영된다 (Req 1.4)", () => {
    const tree = makeTree({ selectedId: 1, expandedIds: new Set([1]) });
    render(<DocumentTree tree={tree} canEdit={false} onMove={vi.fn()} />);

    expect(screen.getByTestId("tree-node-1").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("tree-node-2").getAttribute("aria-selected")).toBe("false");

    fireEvent.click(screen.getByText("B"));
    expect(tree.select).toHaveBeenCalledWith(2);
  });

  it("자식이 있는 노드의 펼침 토글 클릭 시 toggleExpand(id) 를 호출한다 (Req 1.3)", () => {
    const tree = makeTree({ expandedIds: new Set([1]) });
    render(<DocumentTree tree={tree} canEdit={false} onMove={vi.fn()} />);

    // A(1)·B(2) 는 자식이 있어 토글 버튼이 있고, C(3)·D(4) 는 없다.
    expect(screen.queryByTestId("tree-toggle-3")).toBeNull();

    fireEvent.click(screen.getByTestId("tree-toggle-1"));
    expect(tree.toggleExpand).toHaveBeenCalledWith(1);
  });

  it("canEdit=true 면 노드가 draggable 이고, dragStart→형제 after 존 drop 이 onMove(after) 를 호출한다 (Req 6.1, 6.3)", () => {
    const onMove = vi.fn();
    const tree = makeTree({ expandedIds: new Set([1]) });
    render(<DocumentTree tree={tree} canEdit={true} onMove={onMove} />);

    expect(screen.getByTestId("tree-node-2").getAttribute("draggable")).toBe("true");

    const dt = makeDataTransfer("2");
    fireEvent.dragStart(screen.getByTestId("tree-node-2"), { dataTransfer: dt });
    fireEvent.drop(screen.getByTestId("tree-drop-after-3"), { dataTransfer: dt });

    expect(onMove).toHaveBeenCalledWith(2, { kind: "after", targetId: 3 });
  });

  it("inside 존 drop 은 onMove(inside), before 존 drop 은 onMove(before) 를 호출한다 (Req 6.1, 6.3)", () => {
    const onMove = vi.fn();
    const tree = makeTree({ expandedIds: new Set([1]) });
    render(<DocumentTree tree={tree} canEdit={true} onMove={onMove} />);

    const inside = makeDataTransfer("2");
    fireEvent.dragStart(screen.getByTestId("tree-node-2"), { dataTransfer: inside });
    fireEvent.drop(screen.getByTestId("tree-drop-inside-3"), { dataTransfer: inside });
    expect(onMove).toHaveBeenCalledWith(2, { kind: "inside", targetId: 3 });

    const before = makeDataTransfer("2");
    fireEvent.dragStart(screen.getByTestId("tree-node-2"), { dataTransfer: before });
    fireEvent.drop(screen.getByTestId("tree-drop-before-3"), { dataTransfer: before });
    expect(onMove).toHaveBeenCalledWith(2, { kind: "before", targetId: 3 });
  });

  it("루트 드롭 존에 drop 하면 onMove(root) 를 호출한다 (Req 6.1)", () => {
    const onMove = vi.fn();
    const tree = makeTree({ expandedIds: new Set([1]) });
    render(<DocumentTree tree={tree} canEdit={true} onMove={onMove} />);

    const dt = makeDataTransfer("2");
    fireEvent.dragStart(screen.getByTestId("tree-node-2"), { dataTransfer: dt });
    fireEvent.drop(screen.getByTestId("tree-root-drop"), { dataTransfer: dt });

    expect(onMove).toHaveBeenCalledWith(2, { kind: "root" });
  });

  it("노드를 자기 자신 위에 drop 하면 onMove 를 호출하지 않는다 (Req 6.3 가드)", () => {
    const onMove = vi.fn();
    const tree = makeTree({ expandedIds: new Set([1]) });
    render(<DocumentTree tree={tree} canEdit={true} onMove={onMove} />);

    const dt = makeDataTransfer("2");
    fireEvent.dragStart(screen.getByTestId("tree-node-2"), { dataTransfer: dt });
    fireEvent.drop(screen.getByTestId("tree-drop-inside-2"), { dataTransfer: dt });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("canEdit=false(뷰어) 면 노드는 draggable 이 아니고 drop 도 onMove 를 호출하지 않는다 (Req 6.7)", () => {
    const onMove = vi.fn();
    const tree = makeTree({ expandedIds: new Set([1]) });
    render(<DocumentTree tree={tree} canEdit={false} onMove={onMove} />);

    expect(screen.getByTestId("tree-node-2").getAttribute("draggable")).not.toBe("true");

    const dt = makeDataTransfer("2");
    fireEvent.drop(screen.getByTestId("tree-drop-after-3"), { dataTransfer: dt });
    fireEvent.drop(screen.getByTestId("tree-root-drop"), { dataTransfer: dt });

    expect(onMove).not.toHaveBeenCalled();
  });
});
