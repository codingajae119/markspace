/**
 * 워크스페이스 스위처 (design.md "WorkspaceSwitcher / CreateWorkspaceDialog", Req 1.1·1.2·1.5).
 *
 * s16 현재 WS 앰비언트 컨텍스트(`useCurrentWorkspace()`)의 `workspaces` 목록을 표시하고
 * `currentWorkspace` 를 `aria-current` 로 강조하며, 항목 선택 시 `selectWorkspace(String(id))` 로
 * 현재 WS 전환을 위임한다. `workspaceId` 는 s16 이 `String(id)` 로 파생하므로 여기서는 문자열 id 만 넘긴다.
 *
 * 목록 로드(`GET /workspaces`)·현재 WS 선택 영속(localStorage)은 **s16 소유**이므로 재구현하지 않고
 * 컨텍스트를 소비만 한다(Req 1.3·1.6). status 별 표시:
 * - `loading` → s16 `Spinner`.
 * - `empty`  → s16 `EmptyState`(안내만; 잘못된 현재 WS 선택을 강제하지 않음, Req 1.5).
 * - `ready`  → 목록 렌더.
 *
 * 계약 경계: UI 프리미티브(`Button`·`Spinner`·`EmptyState`)는 `@/shared/ui` 배럴에서만 소비한다.
 *
 * Requirements: 1.1(목록·현재 WS 표시), 1.2(선택→selectWorkspace(String(id))), 1.5(empty 빈 상태).
 */

import type { ReactElement } from "react";

import { Button, Spinner, EmptyState } from "@/shared/ui";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";

/** s16 현재 WS 컨텍스트를 소비해 목록·전환 UI 를 렌더한다(목록 로드·영속 재구현 없음). */
export function WorkspaceSwitcher(): ReactElement {
  const { status, workspaces, currentWorkspace, selectWorkspace } = useCurrentWorkspace();

  if (status === "loading") {
    return <Spinner label="워크스페이스 불러오는 중" />;
  }

  if (status === "empty") {
    return (
      <EmptyState
        title="소속된 워크스페이스가 없습니다"
        message="새 워크스페이스를 만들어 시작하세요."
      />
    );
  }

  return (
    <nav aria-label="워크스페이스 전환">
      <ul className="flex flex-col gap-1">
        {workspaces.map((workspace) => {
          const isCurrent = currentWorkspace?.id === workspace.id;
          return (
            <li key={workspace.id}>
              <Button
                variant={isCurrent ? "primary" : "secondary"}
                aria-current={isCurrent ? "true" : undefined}
                onClick={() => selectWorkspace(String(workspace.id))}
              >
                {workspace.name}
              </Button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
