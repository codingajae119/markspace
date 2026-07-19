import { describe, it, expect, expectTypeOf } from "vitest";

import type {
  DocumentStatus,
  DocumentRead,
  DocumentCreate,
  DocumentUpdate,
  DocumentMoveRequest,
  TrashMemberRead,
  TrashBundleRead,
  DocumentNode,
  DropPosition,
  Page,
} from "./types";

/**
 * 순수 타입 모듈이므로 각 계약을 타입 지정 픽스처로 구성해 구조(필드 이름·형태)를 고정한다.
 * 백엔드 `app/document/schemas.py`·`app/trash/schemas.py` 미러가 어긋나면 컴파일이 깨진다.
 */

/** 백엔드 `DocumentRead` 미러 픽스처(TimestampedRead + 파생 content 필드 포함). */
function sampleDocument(): DocumentRead {
  return {
    id: 10,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    workspace_id: 1,
    parent_id: null,
    title: "루트 문서",
    status: "active",
    sort_order: "1.5", // 불투명 정렬 키(문자열)
    current_version_id: 42,
    created_by: 7,
    content: "# 본문",
    content_html: "<h1>본문</h1>",
  };
}

describe("document types (계약 미러)", () => {
  it("DocumentStatus 는 세 상태 문자열만 허용한다", () => {
    const active: DocumentStatus = "active";
    const trashed: DocumentStatus = "trashed";
    const deleted: DocumentStatus = "deleted";
    expect([active, trashed, deleted]).toEqual(["active", "trashed", "deleted"]);
  });

  it("DocumentRead 는 백엔드 스키마 필드를 노출한다", () => {
    const doc = sampleDocument();
    expect(doc.id).toBe(10);
    expect(doc.updated_at).toBeNull();
    expect(doc.status).toBe("active");
    // sort_order 는 불투명 문자열 키(산술 금지) — 타입 수준으로 고정.
    expectTypeOf(doc.sort_order).toEqualTypeOf<string>();
    expectTypeOf(doc.content).toEqualTypeOf<string>();
    expectTypeOf(doc.content_html).toEqualTypeOf<string>();
    expect(doc.content).toBe("# 본문");
    expect(doc.content_html).toBe("<h1>본문</h1>");
  });

  it("DocumentCreate 는 title 필수·parent_id 선택이다", () => {
    const root: DocumentCreate = { title: "새 문서" };
    const child: DocumentCreate = { title: "하위", parent_id: 10 };
    expect(root.title).toBe("새 문서");
    expect(child.parent_id).toBe(10);
  });

  it("DocumentUpdate 는 title 만 선택적으로 받는다", () => {
    const update: DocumentUpdate = { title: "변경" };
    const empty: DocumentUpdate = {};
    expect(update.title).toBe("변경");
    expect(empty.title).toBeUndefined();
  });

  it("DocumentMoveRequest 는 부모·형제 삽입 기준을 선택적으로 받는다", () => {
    const move: DocumentMoveRequest = {
      new_parent_id: 5,
      before_sibling_id: null,
      after_sibling_id: 8,
    };
    expect(move.new_parent_id).toBe(5);
    expect(move.after_sibling_id).toBe(8);
  });

  it("TrashMemberRead·TrashBundleRead 는 휴지통 표시 필드를 노출한다", () => {
    const member: TrashMemberRead = { id: 10, parent_id: null, title: "루트" };
    const bundle: TrashBundleRead = {
      bundle_id: 10,
      root_document_id: 10,
      root_title: "루트",
      workspace_id: 1,
      trashed_at: "2026-07-18T00:00:00Z",
      expires_at: "2026-08-17T00:00:00Z",
      member_count: 1,
      members: [member],
    };
    expect(bundle.bundle_id).toBe(bundle.root_document_id);
    expect(bundle.members[0].title).toBe("루트");
    expect(bundle.member_count).toBe(1);
  });

  it("DocumentNode 는 doc·children 재귀 구조의 파생 타입이다", () => {
    const leaf: DocumentNode = { doc: sampleDocument(), children: [] };
    const node: DocumentNode = { doc: sampleDocument(), children: [leaf] };
    expect(node.children[0].children).toEqual([]);
    expect(node.doc.id).toBe(10);
  });

  it("DropPosition 은 대상 기준 4 종 판별 유니온이다", () => {
    const positions: DropPosition[] = [
      { kind: "inside", targetId: 10 },
      { kind: "before", targetId: 11 },
      { kind: "after", targetId: 12 },
      { kind: "root" },
    ];
    expect(positions.map((p) => p.kind)).toEqual([
      "inside",
      "before",
      "after",
      "root",
    ]);
  });

  it("Page<T> 는 s16 공용 엔벨로프를 재-export 한다", () => {
    const page: Page<TrashBundleRead> = { items: [], total: 0 };
    expect(page.items).toEqual([]);
    expect(page.total).toBe(0);
  });
});
