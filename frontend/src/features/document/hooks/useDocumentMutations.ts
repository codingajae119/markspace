/**
 * 문서 변이 오케스트레이션 훅 (design.md "features/document → useDocumentMutations").
 *
 * 생성·이름변경·삭제·이동을 `documentApi` 호출로 수행하며, 공통 규약은 "낙관 반영→확정/복원,
 * ApiError 그대로 표면화" 다: 이름변경·이동은 서버 응답 전 트리에 낙관적으로 반영(`tree.applyLocal`)
 * 하고, 성공 시 확정(재조회 또는 유지)·실패 시 `tree.applyLocal(null)` 로 서버 스냅샷 복원한다.
 * 실패는 documentApi/apiClient 가 던진 raw `ApiError` 를 `state.error` 에 그대로 보존하며 자체
 * 에러 형태를 발명하지 않는다(Req 9.4). `state.error` 는 매 변이 시작 시 null 로 초기화하고,
 * `state.pending` 은 변이 진행 중 true 다(Req 9.3).
 *
 * - create: 성공(201) 시 `tree.reload()`→`tree.select(created.id)`(반영+현재 선택, Req 3.3),
 *   실패(422/404/409) 시 트리 불변·null 반환(Req 3.4·3.5).
 * - rename: 낙관 title 반영 후 확정/복원(Req 4.2·4.3·4.4).
 * - remove: 성공(204) 시 `tree.reload()` 로 서버 묶음 캐스케이드 반영(프론트 재계산 금지, Req 5.2·5.3),
 *   실패(409 비active/404) 시 false(Req 5.4·5.5). 파괴적 확인 UX 는 툴바 책임(여기 아님).
 * - move: `computeMoveTarget` 로 본문 구성 후 낙관 재배치 반영, 성공(200) 시 `tree.reload()` 로
 *   서버 확정 부모·sort_order 반영(서버가 정렬 소유, 프론트 재계산 금지, Req 6.5), 실패(409/422) 시
 *   복원(Req 6.4). 순환·동일WS·비active 판정은 프론트가 하지 않고 서버 오류만 표면화한다(Req 6.6).
 *
 * 401 은 apiClient 단일 지점의 전역 인터셉터가 처리하므로 여기서 특별 취급하지 않는다(Req 9.5).
 *
 * Requirements: 3.1, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.4, 5.5, 6.1, 6.2, 6.3,
 *   6.4, 6.5, 9.3, 9.4
 */

import { useCallback, useState } from "react";

import { ApiError } from "@/shared/api/errors";
import type { DocumentRead, DocumentNode, DropPosition } from "../types";
import { documentApi } from "../api/documentApi";
import { computeMoveTarget } from "../lib/computeMoveTarget";
import { resolveAncestors } from "../lib/resolveAncestors";
import type { useDocumentTree } from "./useDocumentTree";

/** 변이 상태 표면 (design.md §useDocumentMutations). */
export interface MutationState {
  /** 변이 진행 중 여부. */
  pending: boolean;
  /** 마지막 변이 실패 시 raw ApiError, 그 외 null(매 변이 시작 시 초기화). */
  error: ApiError | null;
}

/** useDocumentMutations 반환 계약. */
export interface UseDocumentMutationsResult {
  /** 문서/하위 문서 생성: 성공 시 반영+선택, 실패 시 null. */
  create(input: { title: string; parentId: number | null }): Promise<DocumentRead | null>;
  /** 이름 변경: 낙관 반영 후 확정/복원. 실패 시 null. */
  rename(id: number, title: string): Promise<DocumentRead | null>;
  /** 삭제→휴지통: 성공(204)→reload, true. 실패 시 false. */
  remove(id: number): Promise<boolean>;
  /** 이동/재정렬: 낙관 재배치 후 확정/복원. 실패 시 null. */
  move(dragId: number, drop: DropPosition): Promise<DocumentRead | null>;
  /** 변이 상태(pending·error). */
  state: MutationState;
}

/** 진행 중이 아니고 오류도 없는 초기/확정 상태. */
const IDLE_STATE: MutationState = { pending: false, error: null };

/** 미상 throw 를 raw ApiError 로 정규화한다(apiClient 는 항상 ApiError 를 던지므로 사실상 통과). */
function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) {
    return err;
  }
  return new ApiError({
    status: 0,
    code: "internal",
    message: "예기치 못한 오류가 발생했습니다.",
  });
}

/** 노드 서브트리를 깊은 복제한다(doc 는 얕은 스프레드로 충분: 낙관 표시 전용). */
function cloneNode(node: DocumentNode): DocumentNode {
  return { doc: { ...node.doc }, children: node.children.map(cloneNode) };
}

/** roots 를 깊은 복제한다(원본 트리 불변 유지). */
function cloneRoots(roots: DocumentNode[]): DocumentNode[] {
  return roots.map(cloneNode);
}

/**
 * (a) 지정 노드의 title 만 바꾼 roots 클론을 만든다(이름변경 낙관 반영).
 * sort_order 등 다른 필드는 건드리지 않는다(서버 소유).
 */
function cloneRootsWithRenamedTitle(
  roots: DocumentNode[],
  id: number,
  title: string,
): DocumentNode[] {
  const cloned = cloneRoots(roots);
  const stack: DocumentNode[] = [...cloned];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === undefined) {
      break;
    }
    if (node.doc.id === id) {
      node.doc.title = title;
    }
    stack.push(...node.children);
  }
  return cloned;
}

/** roots 클론에서 dragId 노드를 분리해 반환(부모 children 또는 루트에서 splice). */
function detachNode(roots: DocumentNode[], dragId: number): DocumentNode | null {
  const rootIdx = roots.findIndex((n) => n.doc.id === dragId);
  if (rootIdx !== -1) {
    return roots.splice(rootIdx, 1)[0] ?? null;
  }
  const stack: DocumentNode[] = [...roots];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === undefined) {
      break;
    }
    const childIdx = node.children.findIndex((c) => c.doc.id === dragId);
    if (childIdx !== -1) {
      return node.children.splice(childIdx, 1)[0] ?? null;
    }
    stack.push(...node.children);
  }
  return null;
}

/**
 * (b) dragId 서브트리를 새 부모(newParentId, null=루트) 아래로 재배치한 roots 클론을 만든다.
 * 형제 위치·정렬은 서버가 소유하므로 append 로만 표시하고 sort_order 는 재계산하지 않는다
 * (최종 진실은 tree.reload()). 노드/부모 미발견은 방어적으로 루트에 붙이거나 원본을 반환한다.
 */
function relocateSubtree(
  roots: DocumentNode[],
  dragId: number,
  newParentId: number | null,
): DocumentNode[] {
  const cloned = cloneRoots(roots);
  const dragged = detachNode(cloned, dragId);
  if (dragged === null) {
    return cloned;
  }
  dragged.doc.parent_id = newParentId;
  if (newParentId === null) {
    cloned.push(dragged);
    return cloned;
  }
  const stack: DocumentNode[] = [...cloned];
  while (stack.length > 0) {
    const node = stack.pop();
    if (node === undefined) {
      break;
    }
    if (node.doc.id === newParentId) {
      node.children.push(dragged);
      return cloned;
    }
    stack.push(...node.children);
  }
  // 새 부모 미발견: 방어적으로 루트에 부착.
  cloned.push(dragged);
  return cloned;
}

/**
 * 문서 변이(생성·이름변경·삭제·이동)를 낙관 반영·복원·오류 표면화로 오케스트레이션하는 훅.
 * `tree` 는 useDocumentTree 결과를 파라미터로 주입받아 reload/select/applyLocal seam 을 사용한다.
 */
export function useDocumentMutations(
  tree: ReturnType<typeof useDocumentTree>,
  workspaceId: string,
): UseDocumentMutationsResult {
  const [state, setState] = useState<MutationState>(IDLE_STATE);

  const create = useCallback(
    async (input: { title: string; parentId: number | null }): Promise<DocumentRead | null> => {
      setState({ pending: true, error: null });
      try {
        const created = await documentApi.createDocument(workspaceId, {
          title: input.title,
          parent_id: input.parentId,
        });
        // 반영 후 현재 선택으로 승격(Req 3.3).
        await tree.reload();
        tree.select(created.id);
        setState(IDLE_STATE);
        return created;
      } catch (err) {
        // 트리 불변·null 반환(Req 3.4·3.5).
        setState({ pending: false, error: toApiError(err) });
        return null;
      }
    },
    [tree, workspaceId],
  );

  const rename = useCallback(
    async (id: number, title: string): Promise<DocumentRead | null> => {
      setState({ pending: true, error: null });
      // 낙관 title 반영(Req 4.2).
      tree.applyLocal(cloneRootsWithRenamedTitle(tree.roots, id, title));
      try {
        const updated = await documentApi.updateDocument(id, { title });
        setState(IDLE_STATE);
        return updated;
      } catch (err) {
        // 서버 스냅샷 복원(Req 4.3·4.4).
        tree.applyLocal(null);
        setState({ pending: false, error: toApiError(err) });
        return null;
      }
    },
    [tree],
  );

  const remove = useCallback(
    async (id: number): Promise<boolean> => {
      setState({ pending: true, error: null });
      // 삭제 전 스냅샷에서 조상 체인을 확보한다(reload 후엔 삭제 묶음이 사라져 계산 불가).
      // resolveAncestors 는 root→self 이므로 자신을 제외하고 뒤집어 부모→루트(가까운 순)로 만든다.
      const candidateIdsNearestFirst = resolveAncestors(tree.nodeById, id)
        .filter((ancestor) => ancestor.id !== id)
        .map((ancestor) => ancestor.id)
        .reverse();
      try {
        await documentApi.deleteDocument(id);
        // 서버 묶음 캐스케이드 반영(프론트 재계산 금지, Req 5.2·5.3).
        await tree.reload();
        // 보던 문서(또는 그 후손)가 삭제 묶음에 있었으면 가장 가까운 부모로 선택 이동(없으면 빈 화면).
        // 삭제된 문서 id 가 selectedId 로 남아 뷰어가 유령 문서를 계속 표시하는 것을 방지한다.
        tree.reselectAfterRemoval(candidateIdsNearestFirst);
        setState(IDLE_STATE);
        return true;
      } catch (err) {
        // 409 비active/404 → false(Req 5.4·5.5).
        setState({ pending: false, error: toApiError(err) });
        return false;
      }
    },
    [tree],
  );

  const move = useCallback(
    async (dragId: number, drop: DropPosition): Promise<DocumentRead | null> => {
      setState({ pending: true, error: null });
      // 요청 본문 구성(Req 6.1·6.2)과 낙관 재배치 반영(Req 6.3).
      const body = computeMoveTarget(tree.nodeById, dragId, drop);
      tree.applyLocal(relocateSubtree(tree.roots, dragId, body.new_parent_id ?? null));
      try {
        const moved = await documentApi.moveDocument(dragId, body);
        // 서버 확정 부모·sort_order 반영(서버가 정렬 소유, Req 6.5).
        await tree.reload();
        setState(IDLE_STATE);
        return moved;
      } catch (err) {
        // 순환·동일WS·비active·형제 오류는 서버가 판정 — 복원 후 표면화(Req 6.4·6.6).
        tree.applyLocal(null);
        setState({ pending: false, error: toApiError(err) });
        return null;
      }
    },
    [tree],
  );

  return { create, rename, remove, move, state };
}
