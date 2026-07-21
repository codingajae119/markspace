/**
 * MemberManagementPanel — owner 전용 멤버 관리 UI
 * (design.md "MemberManagementPanel / WorkspaceSettingsPanel", Req 3.1·3.5·3.6·3.7·7.1·7.3·7.4·7.5).
 *
 * 현재 워크스페이스의 멤버를 배정 가능 사용자 선택(`AssignableUserSelect`)+role 로 추가하고, role 을
 * 변경하고, 제거한다. 배정 가능 목록·reload 는 `useAssignableUsers`(현재 WS id), 뮤테이션은
 * `useMemberActions`(현재 WS id 를 대상)로 위임하며, 이 패널은 표시·선택·결선만 소유한다.
 *
 * ## 노출 게이팅 (D-1 role seam, 사용자 승인 2026-07-19)
 * 패널 전체를 s16 `<RequireRole minimum={Role.OWNER} currentRole={role}>` 로 감싼다. `currentRole` 은
 * s16 `useCurrentWorkspace().role`(s16 이 `null` 하드코딩 → 실제 owner 를 은닉)이 아니라 s18
 * `MembershipRoleSource.roleFor(currentWorkspace.id)` 에서 조달한다. 컴포넌트는 role 문자열을 직접
 * 비교하지 않으며(Req 7.1), owner 위계·admin override(세션 `is_admin`) 판정은 전적으로 `RequireRole`/
 * `hasWorkspaceRole` 단일 소스에 있다(Req 7.3·7.4, INV-1·2·3). owner 미만(viewer/editor)·비-admin 은
 * 은닉된다(fallback `null`).
 *
 * ## S1 열거 한계 (Req 3.7)
 * 계약에 멤버 목록 조회(GET) 엔드포인트가 없다(design.md Contract Constraints S1). 따라서 표시하는
 * 멤버는 `useMemberActions().members` — 이 세션의 뮤테이션으로 확인된 멤버뿐이며 권위 있는 전체
 * 열거가 아니다. 이 한계를 UI 에 명시한다.
 *
 * ## 클라이언트 게이팅은 보안 경계가 아님 (Req 7.5)
 * UI 를 owner 로 게이팅했더라도 서버가 반환한 403 등 오류는 항상 s16 `ErrorMessage` 로 표시한다
 * (`useMemberActions().error`). 게이팅으로 숨겼다는 이유로 오류를 억제하지 않는다.
 *
 * Requirements: 3.1(추가·role변경·제거), 3.2(raw user_id 입력 → 선택 교체), 3.3(선택 사용자+role 추가),
 * 3.4(성공 시 목록 갱신·reload), 3.5(owner 게이팅 s16 경유), 3.6(오류 표시), 3.7(열거 한계),
 * 4.2(추가 실패 표시·상태 롤백), 4.3(stale-409 표시 + 목록 갱신), 7.1(role 직접비교 금지),
 * 7.3(admin override), 7.4(owner 미만 은닉), 7.5(서버 403 항상 표시).
 */

import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

import { Button, ErrorMessage } from "@/shared/ui";
import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";

import { RoleSelect } from "./RoleSelect";
import { AssignableUserSelect } from "./AssignableUserSelect";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { useMemberActions } from "../hooks/useMemberActions";
import { useAssignableUsers } from "../hooks/useAssignableUsers";
import type { MemberRole } from "../api/types";

/**
 * owner(및 admin override) 조건에서만 노출되는 멤버 관리 패널. 노출 판정은 s16 `RequireRole` 단일
 * 소스로만 수행하고, role 은 s18 `MembershipRoleSource` 에서 조달한다(D-1).
 */
export function MemberManagementPanel(): ReactElement {
  const { currentWorkspace } = useCurrentWorkspace();
  const { roleFor } = useMembershipRoleSource();
  // D-1: role 은 MembershipRoleSource 에서 조달(useCurrentWorkspace().role 사용 금지 — 하드코딩 null).
  const role = currentWorkspace ? roleFor(currentWorkspace.id) : null;

  return (
    <RequireRole minimum={Role.OWNER} currentRole={role}>
      <MemberManagementContent workspaceId={currentWorkspace?.id ?? null} />
    </RequireRole>
  );
}

/**
 * 게이트 통과 후 실제 관리 UI. 현재 WS id 를 명시적으로 받아 모든 뮤테이션 대상에 사용한다.
 * 선택된 WS 가 없을 때의 빈 상태 안내는 이 패널이 아니라 `WorkspaceManagementPage` 가 **단일** 소유한다
 * (과거 이 패널과 WorkspaceSettingsPanel 이 각자 같은 문구를 렌더해 admin override 진입 시 중복 노출됨).
 * 페이지가 WS 미선택 시 이 패널을 마운트하지 않으므로 여기서는 방어적으로 아무것도 렌더하지 않는다.
 */
function MemberManagementContent({ workspaceId }: { workspaceId: number | null }): ReactElement | null {
  const { members, add, changeRole, remove, pending, error } = useMemberActions();
  // 배정 가능 사용자 조회(신규): raw user_id 입력을 대체하는 선택 UI 의 데이터·reload 소스(Req 3.2·3.3·4.3).
  const assignable = useAssignableUsers(workspaceId);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [addRole, setAddRole] = useState<MemberRole>("viewer");

  const handleAdd = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (workspaceId === null || selectedUserId === null || pending) {
      return;
    }
    // add 는 항상 void resolve(실패는 useMemberActions.error 로 삼킴) → await 후 단일 경로 reload 안전.
    await add(workspaceId, { user_id: selectedUserId, role: addRole });
    setSelectedUserId(null); // 선택 초기화
    // 단일 경로: 성공(추가 사용자 제외)·stale-409(목록 교정)·기타 실패(서버 진실 재확인) 모두 reload(Req 3.4·4.3).
    void assignable.reload();
  };

  // 배정 가능 목록이 준비되지 않았거나(로딩·오류) 0명이거나, 사용자 미선택·진행 중이면 추가 비활성(Req 3.5·3.6).
  const isAddDisabled =
    pending || assignable.status !== "ready" || assignable.users.length === 0 || selectedUserId === null;

  // 빈 상태 안내는 WorkspaceManagementPage 단일 소유(중복 제거). 방어적 no-render.
  if (workspaceId === null) {
    return null;
  }

  return (
    <section aria-label="멤버 관리" className="flex flex-col gap-4">
      <header>
        <h2 className="text-base font-semibold text-slate-900">멤버 관리</h2>
        {/* S1 열거 한계 명시(Req 3.7): 뮤테이션으로 확인된 멤버만 표시, 전체 목록 아님. */}
        <p className="mt-1 text-xs text-slate-500">
          여기 표시되는 멤버는 이 화면에서 추가·변경으로 확인된 멤버뿐이며, 워크스페이스의 전체 멤버
          목록이 아닙니다.
        </p>
      </header>

      {/* 서버 403 등 오류는 게이팅 여부와 무관하게 항상 표시(Req 7.5). */}
      <ErrorMessage error={error} />

      <form onSubmit={(event) => void handleAdd(event)} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">사용자</span>
          {/* raw user_id 입력 대체: 배정 가능 사용자 선택. loading/empty/error 표면화는 이 컴포넌트가 소유(Req 3.1·3.5·3.6·4.1). */}
          <AssignableUserSelect
            users={assignable.users}
            status={assignable.status}
            error={assignable.error}
            value={selectedUserId}
            onChange={setSelectedUserId}
            disabled={pending}
          />
        </div>
        <div className="flex items-center">
          <RoleSelect id="member-add-role" label="역할" value={addRole} onChange={setAddRole} disabled={pending} />
        </div>
        <Button type="submit" disabled={isAddDisabled}>
          멤버 추가
        </Button>
      </form>

      {members.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {members.map((member) => (
            <li
              key={member.user_id}
              className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 px-3 py-2"
            >
              <span className="text-sm text-slate-800">사용자 {member.user_id}</span>
              <RoleSelect
                id={`member-role-${member.user_id}`}
                label={`사용자 ${member.user_id} 역할`}
                value={member.role}
                onChange={(next) => void changeRole(workspaceId, member.user_id, { role: next })}
                disabled={pending}
              />
              <Button
                variant="secondary"
                aria-label={`사용자 ${member.user_id} 제거`}
                disabled={pending}
                onClick={() => void remove(workspaceId, member.user_id)}
              >
                제거
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">이 화면에서 확인된 멤버가 아직 없습니다.</p>
      )}
    </section>
  );
}
