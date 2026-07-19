import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";

import { Breadcrumb } from "./Breadcrumb";
import type { useDocumentTree } from "../hooks/useDocumentTree";
import type { DocumentNode, DocumentRead } from "../types";

// Breadcrumb 은 useDocumentTree 결과 객체를 prop 으로 소비하며 조상 경로를
// tree.ancestorsOf(tree.selectedId) 로 파생한다(별도 API 호출 없음). 훅을 직접
// 호출하지 않으므로 mock tree 로 렌더·선택 전환을 관찰한다.
// Requirements: 2.1, 2.2, 2.3

type Tree = ReturnType<typeof useDocumentTree>;

function sampleDoc(
  partial: Partial<DocumentRead> & { id: number; title: string },
): DocumentRead {
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

function makeTree(partial: Partial<Tree> = {}): Tree {
  return {
    status: "ready",
    roots: [],
    nodeById: new Map<number, DocumentNode>(),
    error: null,
    selectedId: null,
    expandedIds: new Set<number>(),
    reload: vi.fn<() => Promise<void>>(async () => {}),
    select: vi.fn<(id: number | null) => void>(),
    toggleExpand: vi.fn<(id: number) => void>(),
    ancestorsOf: vi.fn<(id: number) => DocumentRead[]>(() => []),
    applyLocal: vi.fn<(patch: DocumentNode[] | null) => void>(),
    ...partial,
  };
}

describe("Breadcrumb", () => {
  it("깊은 경로의 조상 제목을 root→current 순서로 렌더한다 (Req 2.1)", () => {
    // A(1) → B(2) → D(4) 경로, D 선택.
    const path = [
      sampleDoc({ id: 1, title: "A" }),
      sampleDoc({ id: 2, title: "B", parent_id: 1 }),
      sampleDoc({ id: 4, title: "D", parent_id: 2 }),
    ];
    const ancestorsOf = vi.fn<(id: number) => DocumentRead[]>(() => path);
    const tree = makeTree({ selectedId: 4, ancestorsOf });

    render(<Breadcrumb tree={tree} />);

    // 선택 id 로 조상 파생을 위임한다(별도 조회 없음, Req 2.4).
    expect(ancestorsOf).toHaveBeenCalledWith(4);

    // 각 항목의 라벨 요소(버튼 또는 현재 표시)만 읽어 구분자("/")를 제외한 제목 순서를 검증한다.
    const items = screen.getAllByRole("listitem");
    const labels = items.map(
      (li) => li.querySelector("button, [aria-current]")?.textContent,
    );
    expect(labels).toEqual(["A", "B", "D"]);
  });

  it("중간 조상 항목 클릭 시 select(ancestorId) 를 호출한다 (Req 2.2)", () => {
    const path = [
      sampleDoc({ id: 1, title: "A" }),
      sampleDoc({ id: 2, title: "B", parent_id: 1 }),
      sampleDoc({ id: 4, title: "D", parent_id: 2 }),
    ];
    const select = vi.fn<(id: number | null) => void>();
    const tree = makeTree({
      selectedId: 4,
      select,
      ancestorsOf: vi.fn<(id: number) => DocumentRead[]>(() => path),
    });

    render(<Breadcrumb tree={tree} />);

    fireEvent.click(screen.getByText("B"));
    expect(select).toHaveBeenCalledWith(2);
  });

  it("루트 문서(단일 조상)면 항목을 정확히 하나만 렌더한다 (Req 2.3)", () => {
    const path = [sampleDoc({ id: 1, title: "A" })];
    const tree = makeTree({
      selectedId: 1,
      ancestorsOf: vi.fn<(id: number) => DocumentRead[]>(() => path),
    });

    render(<Breadcrumb tree={tree} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]!.textContent).toBe("A");
  });

  it("selectedId 가 null 이면 아무 항목도 렌더하지 않는다", () => {
    const ancestorsOf = vi.fn<(id: number) => DocumentRead[]>(() => []);
    const tree = makeTree({ selectedId: null, ancestorsOf });

    render(<Breadcrumb tree={tree} />);

    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    // 선택이 없으면 파생 호출도 하지 않는다.
    expect(ancestorsOf).not.toHaveBeenCalled();
  });
});
