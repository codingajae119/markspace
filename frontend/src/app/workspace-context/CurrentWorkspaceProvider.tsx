/**
 * 현재 워크스페이스 앰비언트 컨텍스트 provider
 * (design.md "app / workspace-context → CurrentWorkspaceProvider & useCurrentWorkspace").
 *
 * 세션 컨텍스트와 대칭으로, 인증 후 `GET /workspaces`(→ `Page<WorkspaceRead>`)로 현재 사용자
 * 스코프의 목록을 로드하고 현재 선택 WS 를 localStorage 에 영속·복원한다. 컨슈머는
 * {@link useCurrentWorkspace} 를 통해 동결된 단일 형태({@link CurrentWorkspaceContextValue})만 소비한다.
 *
 * Requirements:
 * - 9.1 provider·훅·단일 컨텍스트 타입 단일 정의
 * - 9.2 인증 시 목록 로드 → status(loading|ready|empty)·workspaces 노출
 * - 9.3 파생 접근자(workspaceId·isShareable) 노출 + role 필드
 * - 9.4 selectWorkspace 선택 + localStorage 영속·재로드 복원, 목록 비면 empty, 유효하지 않은 저장 id 무시
 * - 9.5 refresh() 로 목록·현재 WS 재조회(현재 선택 유지, 없으면 폴백)
 * - 9.6 role 은 필드·형태·기본값(null)만 s16 소유(값은 s18 멤버십 경로로 주입)
 *
 * 경계: 인증 게이팅은 {@link useSession} 의 status 로 판정하며 미인증/로딩이면 provider 는 유휴
 * (`/workspaces` 미호출). mutation·관리 화면은 s18 소유이고 s16 은 읽기 표면·선택 영속만 소유한다.
 * 전역 401 리다이렉트는 apiClient 단일 지점 소유이므로 여기서 재구현하지 않는다.
 */

import { createContext, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { apiClient } from "@/shared/api/client";
import { useSession } from "@/app/session/useSession";
import { memberRoleToRole } from "@/shared/auth/roles";
import type { Page } from "@/shared/types/page";
import type { WorkspaceRead } from "@/shared/types/workspace";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";

/**
 * 현재 WS 선택을 영속하는 **단일** localStorage 키. 선택 영속/복원은 이 키 하나로만 수행한다
 * (AC 9.4). 이 키 규약 변경은 하위 spec 재검증 트리거다.
 */
export const CURRENT_WORKSPACE_STORAGE_KEY = "notion-lite.currentWorkspaceId";

/**
 * 컨텍스트. provider 밖 소비를 감지하기 위해 기본값을 `null` 로 둔다({@link useCurrentWorkspace} 가드).
 */
export const CurrentWorkspaceContext = createContext<CurrentWorkspaceContextValue | null>(null);

/** 저장/현재 선택 id 를 items 에서 해석한다: 일치하면 그 WS, 아니면 첫 WS, 목록 비면 null. */
function resolveCurrent(items: WorkspaceRead[], preferredId: string | null): WorkspaceRead | null {
  if (items.length === 0) {
    return null;
  }
  if (preferredId !== null) {
    const match = items.find((ws) => String(ws.id) === preferredId);
    if (match !== undefined) {
      return match;
    }
  }
  return items[0];
}

/**
 * 현재 워크스페이스 앰비언트 컨텍스트 provider. `SessionProvider` 하위에 마운트되어 인증 상태에
 * 의존한다(design.md Precondition). status 와 무관하게 항상 `children` 을 렌더한다.
 */
export function CurrentWorkspaceProvider({ children }: { children: ReactNode }) {
  const session = useSession();

  const [status, setStatus] = useState<CurrentWorkspaceContextValue["status"]>("loading");
  const [workspaces, setWorkspaces] = useState<WorkspaceRead[]>([]);
  const [currentWorkspace, setCurrentWorkspace] = useState<WorkspaceRead | null>(null);

  // 언마운트 후 setState 방지 + 최신 실행만 반영(refresh 와 마운트 로드 경합 시 latest-wins).
  const mountedRef = useRef(true);
  const runIdRef = useRef(0);
  // 콜백에서 최신 값을 읽기 위한 미러: 현재 선택 id(영속 규약)와 목록(selectWorkspace 조회).
  const selectedIdRef = useRef<string | null>(null);
  const workspacesRef = useRef<WorkspaceRead[]>([]);
  // 서버가 확정한 마지막 선택 WS id(교차 브라우저·기기 복원 소스). 세션 설정에서 미러링해
  // 빈 deps 의 load() 콜백에서 최신값을 읽는다. 미인증/미설정이면 null.
  const serverPreferredIdRef = useRef<string | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // 세션 설정의 last_selected_workspace_id 를 ref 로 미러링한다. load 트리거 effect 보다 먼저
  // 선언해, authenticated 전환 시 이 effect 가 먼저 실행되어 ref 가 확정된 뒤 load 가 읽게 한다.
  useEffect(() => {
    const serverId =
      session.status === "authenticated"
        ? session.settings?.last_selected_workspace_id ?? null
        : null;
    serverPreferredIdRef.current = serverId === null ? null : String(serverId);
  }, [session]);

  const load = useCallback(async (): Promise<void> => {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    let page: Page<WorkspaceRead>;
    try {
      page = await apiClient.get<Page<WorkspaceRead>>("/workspaces");
    } catch {
      // 목록 로드 실패 시 세션은 유효하되 목록을 확정할 수 없다. 로딩 고착 대신 empty 로 수렴한다.
      if (mountedRef.current && runIdRef.current === runId) {
        setWorkspaces([]);
        workspacesRef.current = [];
        setCurrentWorkspace(null);
        setStatus("empty");
      }
      return;
    }

    const items = page.items;
    // 선호 id 우선순위: 진행 중 선택(있으면) → 서버 설정(교차 브라우저 복원) → localStorage.
    // 서버 값을 localStorage 보다 우선시켜 다른 브라우저/기기에서도 마지막 선택이 복원되게 한다.
    // localStorage 는 서버 미설정/미인증 시의 로컬 폴백으로 남는다. stale id(목록에 없음)는 resolveCurrent 가 무시.
    const preferredId =
      selectedIdRef.current ??
      serverPreferredIdRef.current ??
      localStorage.getItem(CURRENT_WORKSPACE_STORAGE_KEY);
    const current = resolveCurrent(items, preferredId);

    if (mountedRef.current && runIdRef.current === runId) {
      setWorkspaces(items);
      workspacesRef.current = items;
      setCurrentWorkspace(current);
      setStatus(items.length === 0 ? "empty" : "ready");
      if (current !== null) {
        // 해석된 현재 선택을 영속(폴백 결과 포함)해 다음 재로드에서 복원되게 한다.
        selectedIdRef.current = String(current.id);
        localStorage.setItem(CURRENT_WORKSPACE_STORAGE_KEY, String(current.id));
      } else {
        selectedIdRef.current = null;
      }
    }
  }, []);

  // 인증 게이팅: authenticated 일 때만 목록을 로드한다. 미인증/로딩이면 provider 는 유휴(`/workspaces` 미호출).
  useEffect(() => {
    if (session.status === "authenticated") {
      void load();
    }
  }, [session.status, load]);

  const selectWorkspace = useCallback((id: string): void => {
    const match = workspacesRef.current.find((ws) => String(ws.id) === id);
    if (match === undefined) {
      // 목록에 없는 id 선택은 무시한다(영속 오염 방지).
      return;
    }
    selectedIdRef.current = id;
    localStorage.setItem(CURRENT_WORKSPACE_STORAGE_KEY, id);
    // 서버에도 마지막 선택을 영속(교차 브라우저 복원). fire-and-forget: 실패해도 로컬 선택은
    // 유지되므로 UX 를 막지 않는다. 다음 세션 부트스트랩 시 서버값이 우선 복원된다.
    serverPreferredIdRef.current = id;
    void apiClient
      .patch("/me/settings", { last_selected_workspace_id: Number(id) })
      .catch(() => {
        // 설정 영속 실패는 무시(로컬 선택 유지). 관측은 apiClient 단일 지점에 위임.
      });
    setCurrentWorkspace(match);
  }, []);

  const value = useMemo<CurrentWorkspaceContextValue>(
    () => ({
      status,
      workspaces,
      currentWorkspace,
      workspaceId: currentWorkspace !== null ? String(currentWorkspace.id) : null,
      // provider-role 파생(s24): 로드된 현재 WS 의 멤버십 role 을 Role enum 으로 번역한다. 형태
      // (Role|null)는 s16 소유이며 여기선 값만 주입한다. currentWorkspace 부재(미선택) 또는 role
      // 부재/null(비멤버·미시드)이면 null. 전환(selectWorkspace)은 currentWorkspace 갱신으로 재파생된다.
      role: currentWorkspace?.role ? memberRoleToRole(currentWorkspace.role) : null,
      isShareable: currentWorkspace?.is_shareable ?? false,
      selectWorkspace,
      refresh: load,
    }),
    [status, workspaces, currentWorkspace, selectWorkspace, load],
  );

  return (
    <CurrentWorkspaceContext.Provider value={value}>{children}</CurrentWorkspaceContext.Provider>
  );
}
