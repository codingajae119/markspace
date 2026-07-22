/**
 * 문서 트리 상태 훅 (design.md "features/document → useDocumentTree").
 *
 * 현재 워크스페이스의 전체 활성 문서를 병합 로드(`documentApi.loadAllActiveDocuments`)하고
 * `buildTree` 로 트리(`roots`)·조회 맵(`nodeById`)을 파생하며, 선택(`selectedId`)·확장
 * (`expandedIds`)·조상 경로(`ancestorsOf`)·재로드(`reload`)와 낙관적 반영 seam(`applyLocal`)을
 * 노출한다. 정렬은 오직 서버가 부여한 `sort_order`(buildTree)만 따르며 프론트에서 재계산하지
 * 않는다(Req 1.7).
 *
 * 스코프는 `useDocumentScope()` 의 최상위 `workspaceId` 만 소비한다(useCurrentWorkspace 직접
 * 접근 금지). `workspaceId` 가 null(현재 WS 없음)이면 API 를 호출하지 않고 빈 트리로 ready 수렴
 * 한다. 이후 non-null workspaceId 가 나타나면 로드한다. 로드 실패는 `ApiError` 를 `error` 에
 * 보존하고 status="error" 로 수렴한다(Req 1.5).
 *
 * 동시성: 언마운트 후 setState 방지 + 최신 실행만 반영(latest-wins)을 위해
 * `CurrentWorkspaceProvider` 와 동일한 `mountedRef`/`runIdRef` idiom 을 사용한다.
 *
 * `applyLocal` 은 useDocumentMutations(task 3.2)를 위한 낙관 반영 seam 이다: `DocumentNode[]`
 * 패치는 roots 를 대체하고 패치 노드를 순회해 nodeById 를 재조립하며(조상/선택 일관성 유지),
 * `null` 은 마지막으로 성공한 서버 스냅샷(ref 보존)으로 정확히 복원한다. 네트워크 호출은 하지 않는다.
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 7.1
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/shared/api/errors";
import type { DocumentRead, DocumentNode } from "../types";
import { documentApi } from "../api/documentApi";
import { buildTree } from "../lib/buildTree";
import { resolveAncestors } from "../lib/resolveAncestors";
import { readLastDocumentId, writeLastDocumentId } from "../lib/lastSelectedDocument";
import { useDocumentScope } from "./useDocumentScope";

/** 로드/트리/선택 상태 표면 (design.md §useDocumentTree). */
export interface DocumentTreeState {
  /** 로드 상태: 진행 중(loading)·성공(ready, 빈 WS 포함)·실패(error). */
  status: "loading" | "ready" | "error";
  /** 트리 루트(형제는 buildTree 가 sort_order 오름차순 정렬). */
  roots: DocumentNode[];
  /** id → 노드 조회 맵(조상 파생·선택 정합). */
  nodeById: Map<number, DocumentNode>;
  /** 로드 실패 시 보존한 ApiError, 그 외 null. */
  error: ApiError | null;
  /** 현재 선택 문서 id 또는 null. */
  selectedId: number | null;
  /** 펼쳐진 노드 id 집합. */
  expandedIds: Set<number>;
}

/** 상태 표면 + 조작/파생 seam. */
export type UseDocumentTreeResult = DocumentTreeState & {
  /** 서버 재조회(삭제/이동 후 캐스케이드 반영). */
  reload(): Promise<void>;
  /** 선택 설정(id 또는 null). */
  select(id: number | null): void;
  /** 확장 토글(불변 Set 갱신). */
  toggleExpand(id: number): void;
  /** 조상 경로(root→current) — resolveAncestors 위임(Req 2.1~2.4). */
  ancestorsOf(id: number): DocumentRead[];
  /** 낙관 반영 seam: 패치 배열 대체 / null 은 서버 스냅샷 복원. */
  applyLocal(patch: DocumentNode[] | null): void;
};

/** buildTree 결과 형태(서버 스냅샷 ref 타입). */
type Tree = { roots: DocumentNode[]; nodeById: Map<number, DocumentNode> };

const EMPTY_TREE: Tree = { roots: [], nodeById: new Map<number, DocumentNode>() };

/** 낙관 패치 노드를 순회해 id→노드 맵을 재조립한다(조상/선택 정합). */
function collectNodeById(patch: DocumentNode[]): Map<number, DocumentNode> {
  const map = new Map<number, DocumentNode>();
  const stack: DocumentNode[] = [...patch];
  while (stack.length > 0) {
    const node = stack.pop()!;
    map.set(node.doc.id, node);
    for (const child of node.children) {
      stack.push(child);
    }
  }
  return map;
}

/** 알 수 없는 throw 를 안정적 ApiError 로 정규화(Req 1.5, 내부 세부정보 미노출). */
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

/**
 * 현재 워크스페이스의 문서 트리를 로드·조립하고 선택/확장/조상/낙관 반영을 노출하는 훅.
 */
export function useDocumentTree(): UseDocumentTreeResult {
  const { workspaceId } = useDocumentScope();

  const [status, setStatus] = useState<DocumentTreeState["status"]>("loading");
  const [roots, setRoots] = useState<DocumentNode[]>([]);
  const [nodeById, setNodeById] = useState<Map<number, DocumentNode>>(
    () => new Map<number, DocumentNode>(),
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(() => new Set<number>());

  // 언마운트 후 setState 방지 + 최신 실행만 반영(reload 와 마운트/스코프 변경 로드 경합 시 latest-wins).
  const mountedRef = useRef(true);
  const runIdRef = useRef(0);
  // applyLocal(null) 복원 대상: 마지막으로 성공한 서버 로드 스냅샷.
  const serverSnapshotRef = useRef<Tree>(EMPTY_TREE);
  // 비동기 load 완료 시점에서 "현재 선택 없음" 을 최신값으로 판정하기 위한 selectedId 미러(복원 게이트).
  const selectedIdRef = useRef<number | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async (): Promise<void> => {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    // 현재 WS 없음: API 호출 없이 빈 트리로 ready 수렴(Req 1.4).
    if (workspaceId === null) {
      if (mountedRef.current && runIdRef.current === runId) {
        serverSnapshotRef.current = EMPTY_TREE;
        setRoots(EMPTY_TREE.roots);
        setNodeById(EMPTY_TREE.nodeById);
        setError(null);
        setStatus("ready");
      }
      return;
    }

    setStatus("loading");
    let docs: DocumentRead[];
    try {
      docs = await documentApi.loadAllActiveDocuments(workspaceId);
    } catch (err) {
      if (mountedRef.current && runIdRef.current === runId) {
        setError(toApiError(err));
        setStatus("error");
      }
      return;
    }

    // 정렬은 buildTree(서버 sort_order)만 따른다 — 프론트 재계산 금지(Req 1.7).
    const tree = buildTree(docs);
    if (mountedRef.current && runIdRef.current === runId) {
      serverSnapshotRef.current = tree;
      setRoots(tree.roots);
      setNodeById(tree.nodeById);
      setError(null);
      // 빈 WS 도 성공이다: roots=[] 인 채 ready(Req 1.6).
      setStatus("ready");

      // 마지막 선택/편집 문서 복원: 현재 활성 선택이 없을 때만(신규 마운트·WS 전환 직후)
      // 저장된 id 를 되살린다. 저장 id 가 이 트리에 실제로 존재할 때만 선택하고(삭제·타 WS
      // 유령 방지) 조상 노드를 펼쳐 트리에서 가시화한다. 진행 중 선택은 덮지 않는다.
      if (selectedIdRef.current === null && workspaceId !== null) {
        const remembered = readLastDocumentId(workspaceId);
        if (remembered !== null && tree.nodeById.has(remembered)) {
          selectedIdRef.current = remembered;
          setSelectedId(remembered);
          // resolveAncestors 는 root→current(자기 포함)를 반환한다. 자신은 제외하고 조상만 펼친다.
          const toExpand = resolveAncestors(tree.nodeById, remembered)
            .map((doc) => doc.id)
            .filter((ancestorId) => ancestorId !== remembered);
          if (toExpand.length > 0) {
            setExpandedIds((prev) => {
              const next = new Set(prev);
              for (const ancestorId of toExpand) {
                next.add(ancestorId);
              }
              return next;
            });
          }
        }
      }
    }
  }, [workspaceId]);

  // WS 전환 시 이전 WS 의 선택/펼침을 비운다. 이렇게 비워 두어야 이어지는 load 의 복원 게이트
  // (selectedIdRef===null)가 열려 새 WS 의 마지막 문서가 복원되고, 교차-WS stale 선택도 제거된다.
  // 마운트(초기 null)에서도 무해하게 실행된다. load 보다 먼저 선언해 동기 리셋이 앞서게 한다.
  useEffect(() => {
    selectedIdRef.current = null;
    setSelectedId(null);
    setExpandedIds(new Set<number>());
  }, [workspaceId]);

  // 마운트 및 workspaceId 변경 시 로드(load 는 workspaceId 에 의존).
  useEffect(() => {
    void load();
  }, [load]);

  const reload = useCallback((): Promise<void> => load(), [load]);

  const select = useCallback(
    (id: number | null): void => {
      selectedIdRef.current = id;
      setSelectedId(id);
      // 마지막 선택을 워크스페이스별로 영속해 편집 후 복귀(읽기로 돌아가기·"문서" 탭) 시 복원되게 한다.
      if (id !== null && workspaceId !== null) {
        writeLastDocumentId(workspaceId, id);
      }
    },
    [workspaceId],
  );

  const toggleExpand = useCallback((id: number): void => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const ancestorsOf = useCallback(
    (id: number): DocumentRead[] => resolveAncestors(nodeById, id),
    [nodeById],
  );

  const applyLocal = useCallback((patch: DocumentNode[] | null): void => {
    if (patch === null) {
      // 서버 스냅샷으로 정확 복원(네트워크 호출 없음).
      const snapshot = serverSnapshotRef.current;
      setRoots(snapshot.roots);
      setNodeById(snapshot.nodeById);
      return;
    }
    setRoots(patch);
    setNodeById(collectNodeById(patch));
  }, []);

  return {
    status,
    roots,
    nodeById,
    error,
    selectedId,
    expandedIds,
    reload,
    select,
    toggleExpand,
    ancestorsOf,
    applyLocal,
  };
}
