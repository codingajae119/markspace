/**
 * 드래그&드롭 드롭 위치 → 이동 요청 본문 매핑 순수(부수효과 없음) 함수 (Req 6.1·6.2).
 *
 * 트리(`nodeById` Map)에서 대상 노드의 `parent_id` 만 조회해 `DropPosition` 을 백엔드
 * `DocumentMoveRequest` **본문**으로 변환한다:
 * - `inside` → `{ new_parent_id: 대상 id }` (대상이 새 부모).
 * - `before` → `{ new_parent_id: 대상의 parent_id, before_sibling_id: 대상 id }`.
 * - `after`  → `{ new_parent_id: 대상의 parent_id, after_sibling_id: 대상 id }`.
 * - `root`   → `{ new_parent_id: null }` (루트로 이동).
 *
 * before/after 에서 대상이 루트(parent_id === null)면 `new_parent_id` 도 `null` 이다 —
 * 루트의 형제는 곧 루트이므로 정상이다. 각 케이스에 해당하는 필드만 설정한다.
 *
 * 순환·동일 워크스페이스·활성 여부 등 이동 제약 판정은 **하지 않으며 서버에 위임**한다
 * (Req 6.6). `dragId` 는 이동 API 경로의 `{id}` 로 호출자가 별도로 사용하므로 이 함수는
 * 오직 요청 본문만 구성한다(계약 충실성을 위해 시그니처에 유지).
 */
import type { DocumentNode, DocumentMoveRequest, DropPosition } from "../types";

/**
 * `drop` 위치를 `DocumentMoveRequest` 본문으로 변환한다.
 * 대상의 부모는 `nodeById.get(targetId)?.doc.parent_id` 로 조회(부재 시 null 방어).
 */
export function computeMoveTarget(
  nodeById: Map<number, DocumentNode>,
  dragId: number,
  drop: DropPosition,
): DocumentMoveRequest {
  // dragId 는 경로 파라미터로 호출자가 별도 사용하므로 본문 구성에는 관여하지 않는다.
  void dragId;

  switch (drop.kind) {
    case "inside":
      return { new_parent_id: drop.targetId };
    case "before":
      return {
        new_parent_id: nodeById.get(drop.targetId)?.doc.parent_id ?? null,
        before_sibling_id: drop.targetId,
      };
    case "after":
      return {
        new_parent_id: nodeById.get(drop.targetId)?.doc.parent_id ?? null,
        after_sibling_id: drop.targetId,
      };
    case "root":
      return { new_parent_id: null };
  }
}
