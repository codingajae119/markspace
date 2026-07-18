/**
 * 현재 워크스페이스 앰비언트 컨텍스트 소비 훅
 * (design.md "app / workspace-context → CurrentWorkspaceProvider & useCurrentWorkspace").
 *
 * {@link CurrentWorkspaceProvider} 가 노출한 동결된 단일 형태({@link CurrentWorkspaceContextValue})를
 * 반환한다. 컨슈머(s18/s19/s20/s22)는 이 훅으로만 현재 WS 를 소비하며 중첩 필드에 산발 접근하지 않는다.
 *
 * Requirements: 9.1(단일 훅), 9.3(파생 접근자 소비 표면).
 */

import { useContext } from "react";

import { CurrentWorkspaceContext } from "@/app/workspace-context/CurrentWorkspaceProvider";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";

/**
 * 현재 워크스페이스 컨텍스트를 읽는다. `CurrentWorkspaceProvider` 밖에서 호출되면(기본값 `null`)
 * 조립 실수를 조기에 드러내도록 명확한 오류를 던진다.
 */
export function useCurrentWorkspace(): CurrentWorkspaceContextValue {
  const value = useContext(CurrentWorkspaceContext);
  if (value === null) {
    throw new Error("useCurrentWorkspace must be used within a CurrentWorkspaceProvider");
  }
  return value;
}
