/**
 * DocumentTreeNode — 문서 트리의 단일 노드(재귀) 컴포넌트
 * (design.md "features/document → DocumentTree/Node").
 *
 * `useDocumentTree` 결과 객체(`tree`)를 prop 으로 소비하며 훅을 직접 호출하지 않는다(테스트 용이).
 * - 펼침/접힘: 자식이 있을 때만 토글 버튼을 렌더하고, `tree.expandedIds.has(id)` 로 펼침 여부를
 *   판정하며 펼쳐졌을 때만 자식을 재귀 렌더한다(Req 1.3).
 * - 선택: 라벨 클릭 시 `tree.select(id)` 를 호출하고 `tree.selectedId` 를 `aria-selected` 로 반영한다(Req 1.4).
 * - DnD(HTML5 native): `canEdit` 가 참이면 노드는 `draggable` 이고 dragStart 에서 dataTransfer 에
 *   노드 id 를 실어 보낸다. 노드마다 before/inside/after 세 개의 결정적 drop 존을 두어 jsdom 에서도
 *   getBoundingClientRect 없이 위치를 판정한다. drop 은 dragId 를 읽어 `onMove(dragId, drop)` 를
 *   호출하되 자기 자신 위 드롭(dragId === targetId)은 무시한다(Req 6.1, 6.3). `canEdit` 가 거짓(뷰어)
 *   이면 draggable 을 끄고 drop 핸들러를 결선하지 않는다(Req 6.7).
 *
 * 상태·정렬·이동 판정은 소유하지 않는다 — `tree`(액션)와 `onMove`(상위가 useDocumentMutations.move 결선)에 위임.
 *
 * Requirements: 1.3, 1.4, 1.5, 1.6, 6.1, 6.3, 6.7
 */

import type { DragEvent, ReactElement } from "react";

import type { UseDocumentTreeResult } from "../hooks/useDocumentTree";
import type { DocumentNode, DropPosition } from "../types";

export interface DocumentTreeNodeProps {
  /** 렌더할 노드(자식 포함). */
  node: DocumentNode;
  /** 트리 상태+액션 객체(훅은 상위가 호출, 여기선 소비만). */
  tree: UseDocumentTreeResult;
  /** 편집 가능(editor 이상)이면 DnD 활성, 뷰어면 비활성(Req 6.7). */
  canEdit: boolean;
  /** 드롭 위치 산정 결과를 상위(useDocumentMutations.move)로 전달. */
  onMove: (dragId: number, drop: DropPosition) => void;
}

/**
 * dataTransfer 에서 드래그 노드 id 를 읽어 숫자로 파싱한다(빈 문자열·NaN 은 null).
 * DocumentTree 의 루트 드롭 존과 공유하기 위해 export 한다.
 */
export function readDragId(event: DragEvent<HTMLElement>): number | null {
  const raw = event.dataTransfer.getData("text/plain");
  if (raw === "") {
    return null;
  }
  const id = Number(raw);
  return Number.isNaN(id) ? null : id;
}

const DROP_STRIP_CLASSES = "h-1 w-full";

/** 한 노드를 렌더하고(제목·토글·선택·DnD 존) 펼쳐졌으면 자식을 재귀 렌더한다. */
export function DocumentTreeNode({
  node,
  tree,
  canEdit,
  onMove,
}: DocumentTreeNodeProps): ReactElement {
  const id = node.doc.id;
  const hasChildren = node.children.length > 0;
  const expanded = tree.expandedIds.has(id);
  const selected = tree.selectedId === id;

  const handleDragStart = (event: DragEvent<HTMLElement>): void => {
    // 중첩 draggable 에서 부모로의 버블 시 dataTransfer 덮어쓰기를 막는다.
    event.stopPropagation();
    event.dataTransfer.setData("text/plain", String(id));
    event.dataTransfer.effectAllowed = "move";
  };

  const allowDrop = (event: DragEvent<HTMLElement>): void => {
    // drop 이 발화하도록 dragover 기본동작을 취소한다.
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const makeDropHandler =
    (kind: "before" | "inside" | "after") =>
    (event: DragEvent<HTMLElement>): void => {
      event.preventDefault();
      // 상위 루트 드롭 존으로 버블 방지(위치는 이 존이 결정).
      event.stopPropagation();
      const dragId = readDragId(event);
      if (dragId === null) {
        return;
      }
      if (dragId === id) {
        // 자기 자신 위 드롭 무시(프론트 편의; 서버도 거절).
        return;
      }
      onMove(dragId, { kind, targetId: id });
    };

  return (
    <li
      role="treeitem"
      aria-selected={selected}
      aria-expanded={hasChildren ? expanded : undefined}
      data-testid={`tree-node-${id}`}
      draggable={canEdit}
      onDragStart={canEdit ? handleDragStart : undefined}
      className="relative select-none"
    >
      <div
        data-testid={`tree-drop-before-${id}`}
        onDragOver={canEdit ? allowDrop : undefined}
        onDrop={canEdit ? makeDropHandler("before") : undefined}
        className={DROP_STRIP_CLASSES}
      />
      <div
        data-testid={`tree-drop-inside-${id}`}
        onDragOver={canEdit ? allowDrop : undefined}
        onDrop={canEdit ? makeDropHandler("inside") : undefined}
        className={[
          "flex items-center gap-1 rounded px-2 py-1 text-sm",
          selected
            ? "bg-slate-200 text-slate-900"
            : "text-slate-700 hover:bg-slate-100",
        ].join(" ")}
      >
        {hasChildren ? (
          <button
            type="button"
            data-testid={`tree-toggle-${id}`}
            aria-label={expanded ? "접기" : "펼치기"}
            onClick={() => tree.toggleExpand(id)}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-200"
          >
            {expanded ? "▾" : "▸"}
          </button>
        ) : (
          <span className="inline-block h-5 w-5 shrink-0" aria-hidden="true" />
        )}
        <button
          type="button"
          onClick={() => tree.select(id)}
          className="min-w-0 flex-1 truncate text-left"
        >
          {node.doc.title}
        </button>
      </div>
      <div
        data-testid={`tree-drop-after-${id}`}
        onDragOver={canEdit ? allowDrop : undefined}
        onDrop={canEdit ? makeDropHandler("after") : undefined}
        className={DROP_STRIP_CLASSES}
      />
      {hasChildren && expanded ? (
        <ul role="group" className="ml-4 flex flex-col">
          {node.children.map((child) => (
            <DocumentTreeNode
              key={child.doc.id}
              node={child}
              tree={tree}
              canEdit={canEdit}
              onMove={onMove}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
