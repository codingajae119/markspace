/**
 * 평면 문서 목록을 트리로 조립하는 순수(부수효과 없음) 함수 (Req 1.1).
 *
 * 백엔드에서 전체 병합 로드된 `DocumentRead[]` 를 `parent_id` 로 부모-자식 연결하여 트리를
 * 만든다. 형제(루트 포함)는 `sort_order` **오름차순**으로 정렬하되, `sort_order` 는 백엔드
 * `Decimal` 의 불투명 정렬 키(string)이므로 **문자열 비교**만 사용한다 — 숫자 파싱·산술·재계산은
 * 하지 않는다(Req 1.7: 정렬은 오로지 서버가 부여한 sort_order 를 따르며 프론트에서 정렬값을
 * 파생하지 않는다).
 *
 * 고아(부모 미로딩: `parent_id` 가 입력에 없는 문서를 가리킴)는 전체 병합 로드 전제에서 정상적으로
 * 발생하지 않지만, 방어적으로 루트로 승격하지 않고 누락 처리한다(크래시 금지).
 */
import type { DocumentRead, DocumentNode } from "../types";

/**
 * 불투명 정렬 키 문자열 비교자 — `sort_order` 오름차순.
 *
 * 숫자로 해석하지 않고 문자열 그대로 비교한다(Req 1.7).
 */
function compareSortOrder(a: DocumentNode, b: DocumentNode): number {
  const sa = a.doc.sort_order;
  const sb = b.doc.sort_order;
  if (sa < sb) return -1;
  if (sa > sb) return 1;
  return 0;
}

/**
 * 평면 `DocumentRead[]` → 트리(`roots`) + id→노드 조회 맵(`nodeById`).
 */
export function buildTree(docs: DocumentRead[]): {
  roots: DocumentNode[];
  nodeById: Map<number, DocumentNode>;
} {
  const nodeById = new Map<number, DocumentNode>();

  // 1) 모든 문서를 노드로 등록(children 은 아직 비어 있음).
  for (const doc of docs) {
    nodeById.set(doc.id, { doc, children: [] });
  }

  // 2) 부모-자식 연결. parent_id 가 null 이면 루트, 존재하지만 미로딩이면 고아(누락).
  const roots: DocumentNode[] = [];
  for (const doc of docs) {
    const node = nodeById.get(doc.id)!;
    if (doc.parent_id === null) {
      roots.push(node);
      continue;
    }
    const parent = nodeById.get(doc.parent_id);
    if (parent === undefined) {
      // 고아: 루트로 승격하지 않고 방어적으로 누락.
      continue;
    }
    parent.children.push(node);
  }

  // 3) 형제(루트 포함) 정렬 — sort_order 문자열 오름차순.
  roots.sort(compareSortOrder);
  for (const node of nodeById.values()) {
    node.children.sort(compareSortOrder);
  }

  return { roots, nodeById };
}
