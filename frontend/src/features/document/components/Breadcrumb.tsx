/**
 * Breadcrumb — 선택 문서의 조상 경로 표시·이동 컴포넌트
 * (design.md "features/document → Breadcrumb").
 *
 * `useDocumentTree` 결과 객체(`tree`)를 prop 으로 소비하며(훅은 상위 페이지가 호출),
 * 로드된 트리에서 `tree.ancestorsOf(tree.selectedId)` 로 조상 경로(root → … → current)를
 * 파생해 순서대로 표시한다(Req 2.1). 조상 전용 조회 API 를 호출하지 않고 이미 로딩된
 * 트리에서만 파생한다(ancestorsOf → resolveAncestors 위임, Req 2.4).
 *
 * 중간 조상 항목 클릭 시 `tree.select(doc.id)` 로 현재 선택을 전환한다(Req 2.2). 마지막
 * 항목(현재 문서)은 비활성 current 로 구분 표시한다. 루트 문서(parent_id null)는 단일
 * 요소 경로 `[thatDoc]` 로 그 하나만 표시한다(Req 2.3). `selectedId` 가 null 이면 아무
 * 항목도 렌더하지 않는다(빈 nav).
 *
 * Requirements: 2.1, 2.2, 2.3
 */

import type { ReactElement } from "react";

import type { useDocumentTree } from "../hooks/useDocumentTree";

export interface BreadcrumbProps {
  /** 트리 상태+액션 객체(= useDocumentTree() 반환; 상위가 결선). */
  tree: ReturnType<typeof useDocumentTree>;
}

/** 선택 문서의 조상 경로를 breadcrumb 으로 렌더하고 조상 클릭 시 선택을 전환한다. */
export function Breadcrumb({ tree }: BreadcrumbProps): ReactElement {
  const { selectedId } = tree;

  // 선택이 없으면 파생·렌더를 하지 않는다(빈 nav).
  const path = selectedId === null ? [] : tree.ancestorsOf(selectedId);

  return (
    <nav aria-label="breadcrumb" className="min-h-6 text-sm text-gray-600">
      <ol className="flex flex-wrap items-center gap-1">
        {path.map((doc, index) => {
          const isCurrent = index === path.length - 1;
          return (
            <li key={doc.id} className="flex items-center gap-1">
              {index > 0 && (
                <span aria-hidden="true" className="text-gray-400 select-none">
                  /
                </span>
              )}
              {isCurrent ? (
                <span
                  aria-current="page"
                  className="font-medium text-gray-900"
                >
                  {doc.title}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => tree.select(doc.id)}
                  className="rounded px-1 text-gray-600 hover:text-gray-900 hover:underline"
                >
                  {doc.title}
                </button>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
