/**
 * 조상 경로 조립 순수(부수효과 없음) 함수 — 브레드크럼 표시용 (Req 2.1).
 *
 * buildTree 로 **이미 로딩된** 트리(`nodeById` Map)만 사용해 주어진 `id` 에서 `parent_id`
 * 체인을 루트까지 거슬러 올라가며 조상 경로를 **root → … → current**(루트 먼저, 현재 문서
 * 마지막) 순서로 반환한다. 루트 문서(parent_id === null)는 단일 요소 경로 `[thatDoc]` 를
 * 반환한다(Req 2.3).
 *
 * 조상 전용 API 엔드포인트는 존재하지 않으므로 별도 네트워크 호출을 하지 않는다 — 오직
 * 로딩된 트리로만 경로를 파생한다(Req 2.4).
 *
 * 방어: `id` 가 `nodeById` 에 없으면 빈 배열을 반환한다. 잘못된 `parent_id` 순환이 있어도
 * 무한 루프에 빠지지 않도록 반복 횟수를 맵 크기(nodeById.size)로 상한하고 방문한 id 를
 * 추적한다.
 */
import type { DocumentRead, DocumentNode } from "../types";

/**
 * `nodeById` 트리에서 `id` 노드의 조상 경로(root→current)를 DocumentRead[] 로 반환한다.
 */
export function resolveAncestors(
  nodeById: Map<number, DocumentNode>,
  id: number,
): DocumentRead[] {
  // current 부터 위로 쌓은 뒤 마지막에 뒤집어 root→current 로 만든다.
  const reversed: DocumentRead[] = [];
  const visited = new Set<number>();

  let current: DocumentNode | undefined = nodeById.get(id);
  // 상한: 순환이 있어도 맵 크기를 넘는 반복은 하지 않는다(방문 추적과 이중 방어).
  while (current !== undefined && !visited.has(current.doc.id)) {
    visited.add(current.doc.id);
    reversed.push(current.doc);

    const parentId = current.doc.parent_id;
    if (parentId === null) break;
    current = nodeById.get(parentId);
  }

  reversed.reverse();
  return reversed;
}
