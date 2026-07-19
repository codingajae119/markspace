import { describe, it, expect } from "vitest";

import { resolveAncestors } from "./resolveAncestors";
import type { DocumentRead, DocumentNode } from "../types";

/**
 * resolveAncestors 는 buildTree 로 이미 로딩된 트리(`nodeById` Map)만으로 `parent_id`
 * 체인을 루트까지 거슬러 올라가 조상 경로를 root→current 순서로 반환하는 순수 함수다
 * (별도 API 호출 없음: 조상 엔드포인트 부재 Req 2.4). 브레드크럼 표시용이며
 * (Requirements 2.1, 2.3, 2.4), 순환 방어를 위해 반복 횟수를 상한한다.
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

/** DocumentRead[] → id→DocumentNode 조회 맵(children 은 이 테스트에서 미사용). */
function makeNodeById(docs: DocumentRead[]): Map<number, DocumentNode> {
  const nodeById = new Map<number, DocumentNode>();
  for (const doc of docs) {
    nodeById.set(doc.id, { doc, children: [] });
  }
  return nodeById;
}

describe("resolveAncestors", () => {
  it("깊은 노드의 조상 경로를 root→current 순서로 반환한다", () => {
    const root = sampleDoc({ id: 1, parent_id: null });
    const a = sampleDoc({ id: 2, parent_id: 1 });
    const b = sampleDoc({ id: 3, parent_id: 2 });
    const c = sampleDoc({ id: 4, parent_id: 3 });
    const nodeById = makeNodeById([root, a, b, c]);

    const path = resolveAncestors(nodeById, 4);

    expect(path.map((d) => d.id)).toEqual([1, 2, 3, 4]);
  });

  it("루트 문서(parent_id null)는 단일 요소 경로를 반환한다", () => {
    const root = sampleDoc({ id: 1, parent_id: null });
    const nodeById = makeNodeById([root]);

    const path = resolveAncestors(nodeById, 1);

    expect(path.map((d) => d.id)).toEqual([1]);
  });

  it("맵에 없는 id 는 빈 배열을 반환한다", () => {
    const root = sampleDoc({ id: 1, parent_id: null });
    const nodeById = makeNodeById([root]);

    expect(resolveAncestors(nodeById, 999)).toEqual([]);
  });

  it("parent_id 순환에도 무한 루프 없이 유한 결과를 반환한다", () => {
    // X.parent = Y, Y.parent = X (악성 순환)
    const x = sampleDoc({ id: 10, parent_id: 11 });
    const y = sampleDoc({ id: 11, parent_id: 10 });
    const nodeById = makeNodeById([x, y]);

    const path = resolveAncestors(nodeById, 10);

    // 무한 루프 없이 종료하고, 결과는 맵 크기로 상한된다.
    expect(path.length).toBeLessThanOrEqual(nodeById.size);
    expect(path.length).toBeGreaterThan(0);
  });

  it("중간 노드는 자신까지의 전체 조상 경로를 반환한다", () => {
    const root = sampleDoc({ id: 1, parent_id: null });
    const a = sampleDoc({ id: 2, parent_id: 1 });
    const b = sampleDoc({ id: 3, parent_id: 2 });
    const c = sampleDoc({ id: 4, parent_id: 3 });
    const nodeById = makeNodeById([root, a, b, c]);

    const path = resolveAncestors(nodeById, 3);

    expect(path.map((d) => d.id)).toEqual([1, 2, 3]);
  });
});
