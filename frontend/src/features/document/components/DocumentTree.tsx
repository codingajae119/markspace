/**
 * DocumentTree — 문서 트리 최상위 컨테이너 컴포넌트
 * (design.md "features/document → DocumentTree/Node").
 *
 * `useDocumentTree` 결과 객체(`tree`)를 prop 으로 소비하며(훅은 상위 페이지가 호출) `tree.roots` 를
 * `DocumentTreeNode` 로 재귀 렌더한다(Req 1.3, 1.6). 또한 명시적 루트 드롭 존을 두어 노드를 루트로
 * 승격하는 이동을 지원한다: drop 시 `onMove(dragId, { kind: "root" })`(Req 6.1). `canEdit` 가 거짓
 * (뷰어)이면 루트 드롭 존을 결선하지 않는다(Req 6.7).
 *
 * 상태·이동 판정은 소유하지 않으며 `tree`(액션)와 `onMove`(상위가 useDocumentMutations.move 결선)에 위임한다.
 *
 * Requirements: 1.3, 1.4, 1.5, 1.6, 6.1, 6.3, 6.7
 */

import type { DragEvent, ReactElement } from "react";

import type { UseDocumentTreeResult } from "../hooks/useDocumentTree";
import type { DropPosition } from "../types";
import { DocumentTreeNode, readDragId } from "./DocumentTreeNode";

export interface DocumentTreeProps {
  /** 트리 상태+액션 객체(= useDocumentTree() 반환; 상위가 결선). */
  tree: UseDocumentTreeResult;
  /** 편집 가능(editor 이상)이면 DnD 활성, 뷰어면 비활성(Req 6.7). */
  canEdit: boolean;
  /** 드롭 위치 산정 결과를 상위(useDocumentMutations.move)로 전달. */
  onMove: (dragId: number, drop: DropPosition) => void;
}

/** `tree.roots` 를 재귀 트리로 렌더하고 루트 드롭 존을 제공한다. */
export function DocumentTree({ tree, canEdit, onMove }: DocumentTreeProps): ReactElement {
  const allowDrop = (event: DragEvent<HTMLElement>): void => {
    // drop 이 발화하도록 dragover 기본동작을 취소한다.
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const handleRootDrop = (event: DragEvent<HTMLElement>): void => {
    event.preventDefault();
    const dragId = readDragId(event);
    if (dragId === null) {
      return;
    }
    onMove(dragId, { kind: "root" });
  };

  return (
    <div className="flex flex-col gap-1">
      <ul role="tree" className="flex flex-col">
        {tree.roots.map((root) => (
          <DocumentTreeNode
            key={root.doc.id}
            node={root}
            tree={tree}
            canEdit={canEdit}
            onMove={onMove}
          />
        ))}
      </ul>
      <div
        data-testid="tree-root-drop"
        aria-label="루트로 이동"
        onDragOver={canEdit ? allowDrop : undefined}
        onDrop={canEdit ? handleRootDrop : undefined}
        className="min-h-8 flex-1 rounded border border-dashed border-transparent"
      />
    </div>
  );
}
