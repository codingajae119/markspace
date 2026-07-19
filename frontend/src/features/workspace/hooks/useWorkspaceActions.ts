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
import type { WorkspaceCreate, WorkspaceRead, WorkspaceUpdate } from "../api/types";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { ApiError } from "@/shared/api/errors";

/** useWorkspaceActions 가 노출하는 워크스페이스 뮤테이션 액션·진행 상태·인라인 오류. */
export interface UseWorkspaceActionsResult {
  /** 워크스페이스 생성. 성공 시 생성된 `WorkspaceRead`, 실패 시 `null`(성공 신호). */
  create: (body: WorkspaceCreate) => Promise<WorkspaceRead | null>;
  /** 생성 진행 중 여부(중복 제출 방지). */
  creating: boolean;
  /**
   * 워크스페이스 설정 부분 갱신(name·is_shareable·trash_retention_days). 성공 시 갱신된
   * `WorkspaceRead` 를 반환하고 s16 `refresh()` 로 현재 WS 컨텍스트에 반영, 실패 시 `null`(Req 4.1).
   */
  update: (id: number, body: WorkspaceUpdate) => Promise<WorkspaceRead | null>;
  /**
   * 워크스페이스 삭제. 성공(204) 시 s16 `refresh()` 로 목록·현재 WS 컨텍스트에서 제외하고 `true`,
   * 실패 시 `false`(Req 4.4). 비-empty 409 는 `error` 로 보관되어 소비 UI 가 안내한다.
   */
  remove: (id: number) => Promise<boolean>;
  /** update·remove 진행 중 여부(중복 제출 방지). */
  saving: boolean;
  /** 직전 뮤테이션 실패의 정규화된 오류(없으면 null). */
  error: ApiError | null;
}

/**
 * 워크스페이스 생성·갱신·삭제 뮤테이션과 s16 컨텍스트 결선(owner 기록·refresh·선택)·진행/오류 상태를
 * 노출한다. 각 뮤테이션은 성공 시에만 s16 `refresh()` 로 컨텍스트를 반영하고, 실패 시 `ApiError` 를
 * `error` 로 보관하며 컨텍스트를 건드리지 않는다(낙관적 반영 없음, Design Error Handling: 롤백).
 */
export function useWorkspaceActions(): UseWorkspaceActionsResult {
  const { refresh, selectWorkspace } = useCurrentWorkspace();
  const { recordOwner } = useMembershipRoleSource();
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
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

  const update = useCallback(
    async (id: number, body: WorkspaceUpdate): Promise<WorkspaceRead | null> => {
      // 재제출 시 직전 오류 해제 + 진행 표시(중복 제출 방지).
      setSaving(true);
      setError(null);
      try {
        const workspace = await workspaceApi.update(id, body);
        // 갱신물(name·is_shareable·retention)을 s16 컨텍스트에 반영(refresh 소유는 s16).
        await refresh();
        return workspace;
      } catch (caught) {
        // apiClient 는 비정상 응답을 항상 ApiError 로 던진다. 실패 시 refresh 미실행(롤백).
        if (caught instanceof ApiError) {
          setError(caught);
        }
        return null;
      } finally {
        setSaving(false);
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: number): Promise<boolean> => {
      setSaving(true);
      setError(null);
      try {
        await workspaceApi.remove(id);
        // 성공(204) 시에만 목록·현재 WS 컨텍스트에서 제외(refresh). 실패 시 미실행(롤백).
        await refresh();
        return true;
      } catch (caught) {
        // 비-empty 409 등은 ApiError 로 보관되어 소비 UI 가 안내(Req 4.4·4.6).
        if (caught instanceof ApiError) {
          setError(caught);
        }
        return false;
      } finally {
        setSaving(false);
      }
    },
    [refresh],
  );

  return { create, creating, update, remove, saving, error };
}
