/**
 * 워크스페이스 뮤테이션 useCase 훅 (design.md "features/workspace/hooks → useWorkspaceActions").
 *
 * `workspaceApi.create` 로 워크스페이스를 생성하고, 성공 시 s16·s18 계약을 결선한다:
 * 1. `MembershipRoleSource.recordOwner(created.id)` — 생성자를 해당 WS 의 owner 로 기록(Req 2.3,
 *    현재 WS role 조달 신호). role 파생은 MembershipRoleSource 단일 소스에만 존재한다.
 * 2. s16 `useCurrentWorkspace().refresh()` — 목록·현재 WS 컨텍스트 재조회(목록 로드·영속은 s16 소유).
 * 3. `selectWorkspace(String(created.id))` — **refresh 이후** 새 WS 를 현재 WS 로 선택(Req 2.3).
 *
 * 실패 시 `ApiError` 를 상태로 보관해 폼이 `ErrorMessage` 로 인라인 표시하게 하고, refresh·recordOwner·
 * selectWorkspace 를 호출하지 않아 낙관적 반영을 남기지 않는다(Design Error Handling: 롤백). 진행 중
 * `creating` 플래그로 중복 제출을 방지하고, 재제출 시 직전 오류를 해제한다.
 *
 * 계약 경계(모두 s16/s18 소비, 재구현 금지):
 * - fetch·base URL·에러 파싱은 `workspaceApi`→s16 `apiClient` 단일 지점 위임.
 * - 목록 로드·현재 WS 선택 영속은 s16 `useCurrentWorkspace` 소유(재구현 금지, refresh/selectWorkspace 호출만).
 * - role 파생·번역은 `MembershipRoleSource` 단일 소스(recordOwner 호출만).
 *
 * 이 훅은 **응집된 액션 객체**를 반환하도록 구성되어, 후속 task(5.1 WorkspaceSettingsPanel)가
 * `update`/`remove` 뮤테이션을 같은 훅에 확장할 수 있다.
 *
 * Requirements: 2.1(생성), 2.3(owner화·refresh·선택), 2.4(실패 오류 표시·목록 미손상).
 */

import { useCallback, useState } from "react";

import { workspaceApi } from "../api/workspaceApi";
import type { WorkspaceCreate, WorkspaceRead } from "../api/types";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { ApiError } from "@/shared/api/errors";

/** useWorkspaceActions 가 노출하는 워크스페이스 뮤테이션 액션·진행 상태·인라인 오류. */
export interface UseWorkspaceActionsResult {
  /** 워크스페이스 생성. 성공 시 생성된 `WorkspaceRead`, 실패 시 `null`(성공 신호). */
  create: (body: WorkspaceCreate) => Promise<WorkspaceRead | null>;
  /** 생성 진행 중 여부(중복 제출 방지). */
  creating: boolean;
  /** 직전 뮤테이션 실패의 정규화된 오류(없으면 null). */
  error: ApiError | null;
}

/**
 * 워크스페이스 생성 뮤테이션과 s16 컨텍스트 결선(owner 기록·refresh·선택)·진행/오류 상태를 노출한다.
 */
export function useWorkspaceActions(): UseWorkspaceActionsResult {
  const { refresh, selectWorkspace } = useCurrentWorkspace();
  const { recordOwner } = useMembershipRoleSource();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const create = useCallback(
    async (body: WorkspaceCreate): Promise<WorkspaceRead | null> => {
      // 재제출 시 직전 오류 해제 + 진행 표시(중복 제출 방지).
      setCreating(true);
      setError(null);
      try {
        const workspace = await workspaceApi.create(body);
        // 조달 신호: 생성자=owner 기록(Req 2.3). role 파생 단일 소스에만 존재.
        recordOwner(workspace.id);
        // 목록·현재 WS 컨텍스트 갱신은 s16 소유(refresh). 그 다음 새 WS 를 선택.
        await refresh();
        selectWorkspace(String(workspace.id));
        return workspace;
      } catch (caught) {
        // apiClient 는 비정상 응답을 항상 ApiError 로 던진다. 그 외는 안전하게 무시(Req 2.4).
        if (caught instanceof ApiError) {
          setError(caught);
        }
        // 실패 시 refresh·recordOwner·selectWorkspace 미실행 → 낙관적 반영 없음(롤백).
        return null;
      } finally {
        setCreating(false);
      }
    },
    [refresh, selectWorkspace, recordOwner],
  );

  return { create, creating, error };
}
