/**
 * TrashList — 휴지통 묶음 목록 화면(editor+ 게이팅)
 * (design.md §화면 컴포넌트 TrashList ~602-603).
 *
 * 화면 전체를 `<RequireRole minimum={EDITOR}>` 로 게이팅한다(Req 8.6): viewer·비멤버는
 * 휴지통 화면을 보지 못하고 editor/owner/admin 만 접근한다(admin override 는 RequireRole 이
 * 세션 is_admin 으로 소유 — 여기서 role 을 수동 비교하지 않는다, Req 9.2 정신). 단, 실제
 * 강제는 서버 403 이며 클라이언트 게이팅은 노출 편의일 뿐이다.
 *
 * 게이트 통과 시에만 렌더되는 내부 `TrashListBody` 가 `useTrash(workspaceId)` 를 (React hooks
 * 규칙에 맞게) 최상단에서 무조건 호출한다. 이 구조 덕분에 훅은 각 컴포넌트 내부에서 조건 없이
 * 호출되며, 동시에 viewer 는 body 자체가 렌더되지 않으므로 트래시 로드를 유발하지 않는다.
 *
 * body 는 `trash.status` 로 분기해 로딩(Spinner)·오류(ErrorMessage)·빈 목록(EmptyState)·
 * 목록(TrashBundleItem 행들)을 렌더한다(Req 8.1). 각 행의 복구는 `trash.restore(id)`, 완전삭제
 * 확인은 `trash.purge(id)` 로 위임하며(Req 8.5 — 훅이 204 후 재목록·404 표면화 소유), 변이 후
 * 남은 `trash.error` 를 목록과 함께 표시한다. 복원 위치·묶음·보존 규칙은 전혀 판단하지 않는다
 * (그 정책은 훅·백엔드 소유, Req 8.7).
 *
 * Requirements: 8.1(휴지통 목록·상태 표시), 8.5(복구·완전삭제 위임), 8.6(editor+ 화면 게이팅),
 * 8.7(복원 위치·묶음·보존 규칙 비판단).
 */

import type { ReactElement } from "react";

import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { Spinner, EmptyState, ErrorMessage } from "@/shared/ui";

import { useTrash } from "../hooks/useTrash";
import { TrashBundleItem } from "./TrashBundleItem";

export interface TrashListProps {
  /** 현재 워크스페이스 식별자(useTrash 로 전달). */
  workspaceId: string;
  /** RequireRole 게이팅용 현재 role(useDocumentScope().role 주입). 비멤버·미확정이면 null. */
  currentRole: Role | null;
}

/**
 * 게이트 통과 시에만 렌더되는 내부 body. `useTrash` 를 최상단에서 무조건 호출하고
 * status 로 분기해 로딩·오류·빈 목록·목록을 렌더한다(Req 8.1·8.5).
 */
function TrashListBody({ workspaceId }: { workspaceId: string }): ReactElement {
  const trash = useTrash(workspaceId);

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-slate-900">휴지통</h2>

      {trash.status === "loading" ? (
        <Spinner />
      ) : trash.status === "error" ? (
        <ErrorMessage error={trash.error} />
      ) : trash.bundles.length === 0 ? (
        <EmptyState
          title="휴지통이 비어 있습니다."
          message="삭제한 문서 묶음이 없습니다."
        />
      ) : (
        <>
          {/* 변이 후 남은 오류(예: 404)는 목록과 함께 표면화한다(Req 8.5). */}
          <ErrorMessage error={trash.error} />
          <ul className="space-y-3">
            {trash.bundles.map((bundle) => (
              <li key={bundle.bundle_id}>
                <TrashBundleItem
                  bundle={bundle}
                  onRestore={(id) => trash.restore(id)}
                  onPurge={(id) => trash.purge(id)}
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/** 휴지통 화면 전체를 editor+ 로 게이팅하고, 통과 시 body 를 렌더한다(Req 8.6). */
export function TrashList({ workspaceId, currentRole }: TrashListProps): ReactElement {
  return (
    <RequireRole minimum={Role.EDITOR} currentRole={currentRole}>
      <TrashListBody workspaceId={workspaceId} />
    </RequireRole>
  );
}
