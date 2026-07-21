/**
 * TrashPage — 휴지통 화면 조립부 (Req 8.1).
 *
 * 현재 워크스페이스 스코프(`useDocumentScope()`)를 `TrashList` 로 위임하는 얇은 in-boundary
 * 페이지다. 목록 로드·복원·영구삭제·member+ 게이팅은 모두 `TrashList`(+ `useTrash`)가 소유하므로
 * 여기서는 스코프의 `workspaceId`·`role` 만 전달한다. `workspaceId` 가 null(현재 WS 없음)이면
 * 명시적 안내를 표시하며, TrashList/useTrash 도 빈 문자열을 방어적으로 빈 목록으로 수렴한다.
 * TrashList 는 자체 RequireRole(MEMBER) 게이트를 소유하므로(비멤버 미노출) 여기서 role 을
 * 다시 비교하지 않는다. 401 은 apiClient 전역 인터셉터가 처리한다.
 *
 * Requirements: 8.1(휴지통 화면 결선·현재 WS 스코프 위임).
 */

import type { ReactElement } from "react";

import { EmptyState } from "@/shared/ui";

import { useDocumentScope } from "../hooks/useDocumentScope";
import { TrashList } from "../components/TrashList";

/** 휴지통 화면. 현재 WS 스코프를 TrashList 로 위임한다. */
export function TrashPage(): ReactElement {
  const scope = useDocumentScope();

  if (scope.workspaceId === null) {
    // 현재 WS 없음: 명시적 안내(useTrash 도 빈 문자열을 방어적으로 처리).
    return (
      <EmptyState
        title="워크스페이스를 선택하세요"
        message="휴지통을 보려면 먼저 워크스페이스를 선택하세요."
      />
    );
  }

  return <TrashList workspaceId={scope.workspaceId} currentRole={scope.role} />;
}
