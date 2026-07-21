/**
 * MemberManagementPanel — owner 전용 멤버 관리 UI
 * (design.md "MemberManagementPanel / WorkspaceSettingsPanel", Req 3.1·3.5·3.6·3.7·7.1·7.3·7.4·7.5).
 *
 * 현재 워크스페이스의 멤버를 `user_id`+role 로 추가하고, role 을 변경하고, 제거한다. 모든 뮤테이션은
 * `useMemberActions`(현재 WS id 를 대상)로 위임하며, 이 패널은 표시·입력·결선만 소유한다.
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
 * Requirements: 3.1(추가·role변경·제거), 3.5(owner 게이팅 s16 경유), 3.6(오류 표시), 3.7(열거 한계),
 * 7.1(role 직접비교 금지), 7.3(admin override), 7.4(owner 미만 은닉), 7.5(서버 403 항상 표시).
 */

import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

import { Button, ErrorMessage } from "@/shared/ui";
import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";

import { RoleSelect } from "./RoleSelect";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { useMemberActions } from "../hooks/useMemberActions";
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
  const [userIdInput, setUserIdInput] = useState("");
  const [addRole, setAddRole] = useState<MemberRole>("viewer");

  // user_id 는 양의 정수만 유효(빈 문자열·NaN·0 이하는 제출 불가).
  const parsedUserId = Number.parseInt(userIdInput, 10);
  const isUserIdValid = Number.isInteger(parsedUserId) && parsedUserId > 0;

  const handleAdd = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (workspaceId === null || !isUserIdValid || pending) {
      return;
    }
    void add(workspaceId, { user_id: parsedUserId, role: addRole });
    setUserIdInput("");
  };

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

      <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="member-add-user-id" className="text-sm font-medium text-slate-700">
            사용자 ID
          </label>
          <input
            id="member-add-user-id"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            value={userIdInput}
            onChange={(event) => setUserIdInput(event.target.value)}
            className="w-32 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          />
        </div>
        <div className="flex items-center">
          <RoleSelect id="member-add-role" label="역할" value={addRole} onChange={setAddRole} disabled={pending} />
        </div>
        <Button type="submit" disabled={!isUserIdValid || pending}>
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
