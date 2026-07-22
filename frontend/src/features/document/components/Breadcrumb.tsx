/**
 * Breadcrumb — 선택 문서의 상위 경로(조상만) 표시·이동 컴포넌트
 * (design.md "features/document → Breadcrumb").
 *
 * `useDocumentTree` 결과 객체(`tree`)를 prop 으로 소비하며(훅은 상위 페이지가 호출),
 * 로드된 트리에서 `tree.ancestorsOf(tree.selectedId)` 로 경로(root → … → current)를
 * 파생한다(Req 2.1). 조상 전용 조회 API 를 호출하지 않고 이미 로딩된 트리에서만 파생한다
 * (ancestorsOf → resolveAncestors 위임, Req 2.4).
 *
 * UX: 현재 문서 제목은 바로 아래 `DocumentViewer` 의 `<h1>` 이 단독으로 소유하므로
 * 브레드크럼은 파생 경로에서 **마지막 요소(현재 문서)를 제외한 상위 경로만** 표시해 제목
 * 중복을 없앤다. 남는 항목은 모두 조상이므로 전부 클릭 가능한 버튼으로 렌더하고, 클릭 시
 * `tree.select(doc.id)` 로 선택을 전환한다(Req 2.2). 루트 문서(조상 없음)나 `selectedId`
 * 가 null 이면 표시할 상위 경로가 없어 아무 항목도 렌더하지 않는다(빈 nav).
 *
 * Requirements: 2.1, 2.2, 2.3
 */

import type { ReactElement } from "react";

import type { useDocumentTree } from "../hooks/useDocumentTree";

export interface BreadcrumbProps {
  /** 트리 상태+액션 객체(= useDocumentTree() 반환; 상위가 결선). */
  tree: ReturnType<typeof useDocumentTree>;
}

/** 선택 문서의 상위 경로(조상만)를 breadcrumb 으로 렌더하고 클릭 시 선택을 전환한다. */
export function Breadcrumb({ tree }: BreadcrumbProps): ReactElement {
  const { selectedId } = tree;

  // 선택이 없으면 파생·렌더를 하지 않는다(빈 nav).
  // 파생 경로(root→current)에서 마지막 요소(현재 문서)를 잘라내 상위 경로만 남긴다 —
  // 현재 문서 제목은 아래 DocumentViewer 의 <h1> 이 단독 소유한다(제목 중복 제거).
  const ancestors =
    selectedId === null ? [] : tree.ancestorsOf(selectedId).slice(0, -1);

  return (
    <nav aria-label="breadcrumb" className="min-h-6 text-sm text-gray-600">
      <ol className="flex flex-wrap items-center gap-1">
        {ancestors.map((doc, index) => (
          <li key={doc.id} className="flex items-center gap-1">
            {index > 0 && (
              <span aria-hidden="true" className="text-gray-400 select-none">
                /
              </span>
            )}
            <button
              type="button"
              onClick={() => tree.select(doc.id)}
              className="rounded px-1 text-gray-600 hover:text-gray-900 hover:underline"
            >
              {doc.title}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
