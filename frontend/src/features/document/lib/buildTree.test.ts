import { describe, it, expect } from "vitest";

import { buildTree } from "./buildTree";
import type { DocumentRead } from "../types";

/**
 * buildTree 는 평면 DocumentRead[] 를 parent_id 로 연결한 트리로 조립하는 순수 함수다.
 * 형제(루트 포함)는 sort_order(불투명 문자열 키) 오름차순으로 정렬하며, 값을 숫자로 파싱하거나
 * 재계산하지 않는다. 고아(부모 미로딩)는 루트로 승격하지 않고 방어적으로 누락한다
 * (Requirements 1.1, 1.7).
 */
function sampleDoc(partial: Partial<DocumentRead> = {}): DocumentRead {
  return {
    id: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    workspace_id: 1,
    parent_id: null,
    title: "doc",
    status: "active",
    sort_order: "1",
    current_version_id: null,
    created_by: 1,
    content: "",
    content_html: "",
    ...partial,
  };
}

describe("buildTree", () => {
  it("다단계 계층을 올바른 루트 배열과 중첩 children 으로 조립한다", () => {
    const root = sampleDoc({ id: 1, parent_id: null, sort_order: "a" });
    const child = sampleDoc({ id: 2, parent_id: 1, sort_order: "a" });
    const grandchild = sampleDoc({ id: 3, parent_id: 2, sort_order: "a" });

    const { roots, nodeById } = buildTree([grandchild, child, root]);

    expect(roots).toHaveLength(1);
    expect(roots[0].doc.id).toBe(1);
    expect(roots[0].children).toHaveLength(1);
    expect(roots[0].children[0].doc.id).toBe(2);
    expect(roots[0].children[0].children).toHaveLength(1);
    expect(roots[0].children[0].children[0].doc.id).toBe(3);
    // 같은 노드 인스턴스가 nodeById 와 트리에서 공유된다.
    expect(nodeById.get(2)).toBe(roots[0].children[0]);
  });

  it("형제를 sort_order 문자열 비교 오름차순으로 정렬한다(불투명 키)", () => {
    const parent = sampleDoc({ id: 1, parent_id: null });
    // 의도된 오름차순: "a" < "b" < "c" (문자열 비교). 입력은 일부러 뒤섞는다.
    const cChild = sampleDoc({ id: 20, parent_id: 1, sort_order: "c" });
    const aChild = sampleDoc({ id: 21, parent_id: 1, sort_order: "a" });
    const bChild = sampleDoc({ id: 22, parent_id: 1, sort_order: "b" });

    const { nodeById } = buildTree([cChild, aChild, bChild, parent]);

    const children = nodeById.get(1)!.children.map((n) => n.doc.sort_order);
    expect(children).toEqual(["a", "b", "c"]);
  });

  it("빈 입력이면 빈 roots·빈 map 을 반환한다", () => {
    const { roots, nodeById } = buildTree([]);

    expect(roots).toEqual([]);
    expect(nodeById.size).toBe(0);
  });

  it("여러 루트를 sort_order 로 정렬한다", () => {
    // 숫자처럼 보이지만 문자열 비교: "10" < "2" 여야 한다(문자열 정렬 확인).
    const r1 = sampleDoc({ id: 1, parent_id: null, sort_order: "2" });
    const r2 = sampleDoc({ id: 2, parent_id: null, sort_order: "10" });
    const r3 = sampleDoc({ id: 3, parent_id: null, sort_order: "1" });

    const { roots } = buildTree([r1, r2, r3]);

    // 문자열 비교: "1" < "10" < "2"
    expect(roots.map((n) => n.doc.sort_order)).toEqual(["1", "10", "2"]);
    expect(roots.map((n) => n.doc.id)).toEqual([3, 2, 1]);
  });

  it("고아(부모 미로딩)는 루트로 승격하지 않고 누락하며 크래시하지 않는다", () => {
    const root = sampleDoc({ id: 1, parent_id: null });
    const orphan = sampleDoc({ id: 2, parent_id: 999 }); // 999 는 입력에 없음

    const { roots, nodeById } = buildTree([root, orphan]);

    expect(roots.map((n) => n.doc.id)).toEqual([1]);
    // 고아는 어떤 부모의 children 에도 들어가지 않는다.
    expect(nodeById.get(1)!.children).toEqual([]);
  });

  it("nodeById 는 포함된 모든 노드를 id 키로 담는다", () => {
    const root = sampleDoc({ id: 1, parent_id: null });
    const child = sampleDoc({ id: 2, parent_id: 1 });
    const grandchild = sampleDoc({ id: 3, parent_id: 2 });

    const { nodeById } = buildTree([root, child, grandchild]);

    expect(nodeById.size).toBe(3);
    expect(nodeById.get(1)!.doc.id).toBe(1);
    expect(nodeById.get(2)!.doc.id).toBe(2);
    expect(nodeById.get(3)!.doc.id).toBe(3);
  });
});
