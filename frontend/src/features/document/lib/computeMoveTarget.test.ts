import { describe, it, expect } from "vitest";

import { computeMoveTarget } from "./computeMoveTarget";
import type { DocumentRead, DocumentNode } from "../types";

/**
 * computeMoveTarget 는 드래그&드롭 드롭 위치(`DropPosition`)를 백엔드
 * `DocumentMoveRequest` 본문으로 매핑하는 순수 함수다(부수효과 없음). 순환·동일
 * 워크스페이스·활성 여부 등 제약 판정은 하지 않으며 서버에 위임한다(Req 6.6).
 * `dragId` 는 이동 API 경로의 `{id}` 로 호출자가 별도로 사용하므로 이 함수는 오직
 * 요청 **본문**만 구성한다(Requirements 6.1, 6.2).
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

describe("computeMoveTarget", () => {
  it("inside 는 대상 id 를 new_parent_id 로 삼고 형제 필드를 두지 않는다", () => {
    const parent = sampleDoc({ id: 1, parent_id: null });
    const target = sampleDoc({ id: 2, parent_id: 1 });
    const nodeById = makeNodeById([parent, target]);

    const req = computeMoveTarget(nodeById, 9, { kind: "inside", targetId: 2 });

    expect(req).toEqual({ new_parent_id: 2 });
    expect(req.before_sibling_id).toBeUndefined();
    expect(req.after_sibling_id).toBeUndefined();
  });

  it("before 는 대상의 parent_id 를 new_parent_id, 대상 id 를 before_sibling_id 로 둔다", () => {
    const parent = sampleDoc({ id: 1, parent_id: null });
    const target = sampleDoc({ id: 2, parent_id: 1 });
    const nodeById = makeNodeById([parent, target]);

    const req = computeMoveTarget(nodeById, 9, { kind: "before", targetId: 2 });

    expect(req).toEqual({ new_parent_id: 1, before_sibling_id: 2 });
    expect(req.after_sibling_id).toBeUndefined();
  });

  it("after 는 대상의 parent_id 를 new_parent_id, 대상 id 를 after_sibling_id 로 둔다", () => {
    const parent = sampleDoc({ id: 1, parent_id: null });
    const target = sampleDoc({ id: 2, parent_id: 1 });
    const nodeById = makeNodeById([parent, target]);

    const req = computeMoveTarget(nodeById, 9, { kind: "after", targetId: 2 });

    expect(req).toEqual({ new_parent_id: 1, after_sibling_id: 2 });
    expect(req.before_sibling_id).toBeUndefined();
  });

  it("루트 문서 앞/뒤 드롭은 new_parent_id 가 null(루트의 형제 = 루트)이다", () => {
    const root = sampleDoc({ id: 5, parent_id: null });
    const nodeById = makeNodeById([root]);

    const before = computeMoveTarget(nodeById, 9, { kind: "before", targetId: 5 });
    expect(before).toEqual({ new_parent_id: null, before_sibling_id: 5 });

    const after = computeMoveTarget(nodeById, 9, { kind: "after", targetId: 5 });
    expect(after).toEqual({ new_parent_id: null, after_sibling_id: 5 });
  });

  it("root 드롭은 new_parent_id 만 null 로 두고 형제 필드를 두지 않는다", () => {
    const nodeById = makeNodeById([sampleDoc({ id: 1 })]);

    const req = computeMoveTarget(nodeById, 9, { kind: "root" });

    expect(req).toEqual({ new_parent_id: null });
    expect(req.before_sibling_id).toBeUndefined();
    expect(req.after_sibling_id).toBeUndefined();
  });
});
