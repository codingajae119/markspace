/**
 * MemberManagementPanel — owner 전용 멤버 관리 UI
 * (design.md "MemberManagementPanel (UI, 표시원 전환)", Req 3.5·3.7·4.1·4.2·7.1·7.3·7.4·7.5).
 *
 * 현재 워크스페이스의 멤버를 배정 가능 사용자 선택(`AssignableUserSelect`)+role 로 추가하고, role 을
 * 변경하고, 제거한다. 뮤테이션은 `useMemberActions`(현재 WS id 를 대상)로 위임하며, 이 패널은 표시·
 * 선택·결선만 소유한다.
 *
 * ## 서버 로스터가 유일 표시원 (Req 3.7·4.2)
 * 멤버 목록의 **표시원은 서버 로스터**(`useWorkspaceMembers(workspaceId).members`, 타입
 * `MemberRosterRow`)다. 재로그인(새 세션)이어도 마운트 시 서버에서 시드되므로 기존 멤버를 즉시
 * 볼 수 있다(Req 3.2). 로컬 세션 뮤테이션 상태(`useMemberActions().members`)는 **표시에 사용하지
 * 않는다**(단일 소스, Req 4.2) — 로컬 델타를 병합하지 않아 "두 목록 분리"를 원천 차단한다. 멤버
 * 라벨은 로스터가 제공한 `name` 을 그대로 쓰며(`` `${row.user_id} ${row.name}` ``), 추가 시점에
 * 이름을 별도로 캡처하는 우회(`nameById`)에 의존하지 않는다(Req 3.7).
 *
 * ## 뮤테이션 후 로스터 재동기화 (Req 4.1·4.3)
 * add/changeRole/remove 는 `useMemberActions` 를 그대로 호출하고, 완료(await, pending false) 후
 * `roster.reload()` 로 서버 진실을 다시 읽어 반영한다(중복 없는 추가·제거 반영·role 변경 반영이
 * 서버 권위로 자명하게 성립, Req 4.1). add·remove 는 배정 가능 집합도 변하므로 `assignable.reload()`
 * 도 유지하고, changeRole 은 assignable 이 불변이라 로스터만 reload 한다. reload 는 뮤테이션의 in-flight
 * 가드와 경합하지 않도록 pending 해소 후 호출한다.
 *
 * ## 로드 상태 표면화 (Req 3.3·3.4·3.5)
 * 로딩(`roster.status==="loading"`)·오류(`roster.status==="error"`→`roster.error`)·빈
 * (`roster.status==="ready"` && `members.length===0`) 상태를 표면화한다.
 *
 * ## 추가 폼 노출·역할 단순화 (UX)
 * 배정 가능 사용자가 확정적으로 0명(`assignable.status==="ready"` && `users.length===0`)이면 추가
 * 폼 전체를 숨긴다 — 비활성 버튼 + "배정 가능한 사용자가 없습니다" 를 남기지 않는다(막다른 UI 제거).
 * 로딩·오류 상태에서는 폼을 유지해 `AssignableUserSelect` 가 그 상태를 표면화한다. 또한 추가 시 역할은
 * 항상 `member` 로 고정하므로 추가 폼에는 역할 combo 를 두지 않는다. owner 승격은 멤버 목록의 role
 * 변경(RoleSelect)으로만 수행한다(s26 owner/member 2단계).
 *
 * ## 노출 게이팅 (D-1 role seam, 사용자 승인 2026-07-19 — 무변경)
 * 패널 전체를 s16 `<RequireRole minimum={Role.OWNER} currentRole={role}>` 로 감싼다. `currentRole` 은
 * s16 `useCurrentWorkspace().role`(하드코딩 null)이 아니라 s18 `MembershipRoleSource.roleFor(id)` 에서
 * 조달한다. 컴포넌트는 role 문자열을 직접 비교하지 않으며(Req 7.1), owner 위계·admin override 판정은
 * 전적으로 `RequireRole`/`hasWorkspaceRole` 단일 소스에 있다(Req 7.3·7.4, INV-1·2·3).
 *
 * ## 클라이언트 게이팅은 보안 경계가 아님 (Req 7.5)
 * UI 를 owner 로 게이팅했더라도 서버가 반환한 403 등 **뮤테이션** 오류는 항상 s16 `ErrorMessage` 로
 * 표시한다(`useMemberActions().error`). 게이팅으로 숨겼다는 이유로 오류를 억제하지 않는다.
 *
 * Requirements: 3.1(추가·role변경·제거), 3.2(재로그인 서버 시드), 3.3(로딩), 3.4(오류), 3.5(빈 상태),
 * 3.7(이름=서버 값·캡처 우회 미의존), 4.1(뮤테이션 로스터 반영), 4.2(단일 소스 표시), 4.3(재동기화),
 * 7.1(role 직접비교 금지), 7.3(admin override), 7.4(owner 미만 은닉), 7.5(서버 오류 항상 표시).
 */

import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

import { Button, ErrorMessage, Spinner } from "@/shared/ui";
import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";

import { RoleSelect } from "./RoleSelect";
import { AssignableUserSelect } from "./AssignableUserSelect";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { useMemberActions } from "../hooks/useMemberActions";
import { useAssignableUsers } from "../hooks/useAssignableUsers";
import { useWorkspaceMembers } from "../hooks/useWorkspaceMembers";
import type { MemberRosterRow, MemberRole } from "../api/types";

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
 * 게이트 통과 후 실제 관리 UI. 현재 WS id 를 명시적으로 받아 로스터 조회·모든 뮤테이션 대상에 사용한다.
 * 선택된 WS 가 없을 때의 빈 상태 안내는 이 패널이 아니라 `WorkspaceManagementPage` 가 **단일** 소유한다.
 * 페이지가 WS 미선택 시 이 패널을 마운트하지 않으므로 여기서는 방어적으로 아무것도 렌더하지 않는다.
 */
function MemberManagementContent({ workspaceId }: { workspaceId: number | null }): ReactElement | null {
  // 표시원(유일): 서버 멤버 로스터. WS 미선택 시 안정 비로딩(hook 내부 null 가드, Req 3.6).
  const roster = useWorkspaceMembers(workspaceId);
  // 뮤테이션만 위임(표시에 members 를 사용하지 않는다 — 단일 소스, Req 4.2). pending·error 는 유지.
  const { add, changeRole, remove, pending, error } = useMemberActions();
  // 배정 가능 사용자 조회: raw user_id 입력을 대체하는 선택 UI 의 데이터·reload 소스(Req 3.2·3.3·4.3).
  const assignable = useAssignableUsers(workspaceId);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);

  // 추가되는 멤버는 항상 member 로 시작한다(s26 owner/member 2단계). owner 승격은 아래 목록의 role
  // 변경(RoleSelect)으로 수행하므로 추가 폼에는 역할 combo 를 두지 않는다.
  const ADD_ROLE: MemberRole = "member";

  const handleAdd = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (workspaceId === null || selectedUserId === null || pending) {
      return;
    }
    // add 는 항상 void resolve(실패는 useMemberActions.error 로 삼킴) → await 후 단일 경로 reload 안전.
    await add(workspaceId, { user_id: selectedUserId, role: ADD_ROLE });
    setSelectedUserId(null); // 선택 초기화
    // 서버 재동기화: 로스터(표시원) + 배정 후보(추가로 감소). 성공·stale·실패 모두 서버 진실 재확인(Req 4.1·4.3).
    void roster.reload();
    void assignable.reload();
  };

  // 멤버 표시 라벨 — 로스터 name 사용(캡처 우회 없음, Req 3.7).
  const memberLabel = (row: MemberRosterRow): string => `${row.user_id} ${row.name}`;

  // 배정 가능 사용자가 확정적으로 0명(조회 성공·빈 목록)이면 추가 UI 자체를 노출하지 않는다.
  // 비활성 버튼 + "배정 가능한 사용자가 없습니다" 를 남기는 대신 폼 전체를 숨겨 막다른 UI 를 제거한다.
  const hasNoAssignableUsers = assignable.status === "ready" && assignable.users.length === 0;

  // 배정 가능 목록이 준비되지 않았거나(로딩·오류) 0명이거나, 사용자 미선택·진행 중이면 추가 비활성(Req 3.6).
  const isAddDisabled =
    pending || assignable.status !== "ready" || assignable.users.length === 0 || selectedUserId === null;

  // 빈 상태 안내는 WorkspaceManagementPage 단일 소유(중복 제거). 방어적 no-render.
  if (workspaceId === null) {
    return null;
  }

  // changeRole 은 assignable 불변 → 로스터만 재동기화(Req 4.1).
  const handleChangeRole = async (userId: number, next: MemberRole): Promise<void> => {
    await changeRole(workspaceId, userId, { role: next });
    void roster.reload();
  };

  // remove 는 배정 후보가 늘 수 있어 로스터 + assignable 재동기화(Req 4.1·4.3).
  const handleRemove = async (userId: number): Promise<void> => {
    await remove(workspaceId, userId);
    void roster.reload();
    void assignable.reload();
  };

  return (
    <section aria-label="멤버 관리" className="flex flex-col gap-4">
      <header>
        <h2 className="text-base font-semibold text-slate-900">멤버 관리</h2>
      </header>

      {/* 서버 403 등 뮤테이션 오류는 게이팅 여부와 무관하게 항상 표시(Req 7.5). */}
      <ErrorMessage error={error} />

      {/* 배정 가능 사용자가 확정 0명이면 추가 폼(사용자 선택·멤버 추가 버튼)을 통째로 숨긴다.
          로딩·오류 상태에서는 폼을 유지해 AssignableUserSelect 가 그 상태를 표면화한다. */}
      {!hasNoAssignableUsers && (
        <form onSubmit={(event) => void handleAdd(event)} className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium text-slate-700">사용자</span>
            {/* raw user_id 입력 대체: 배정 가능 사용자 선택. loading/error 표면화는 이 컴포넌트가 소유(Req 3.1·3.6·4.1). */}
            <AssignableUserSelect
              users={assignable.users}
              status={assignable.status}
              error={assignable.error}
              value={selectedUserId}
              onChange={setSelectedUserId}
              disabled={pending}
            />
          </div>
          {/* 추가 시 역할은 항상 member(ADD_ROLE) — 역할 combo 는 두지 않는다. owner 승격은 목록의 role 변경으로. */}
          <Button type="submit" disabled={isAddDisabled}>
            멤버 추가
          </Button>
        </form>
      )}

      {/* 멤버 목록: 서버 로스터 단일 표시원. status 판별자로 로딩·오류·빈·목록 중 하나를 표면화. */}
      {roster.status === "loading" ? (
        <Spinner label="멤버 로스터 불러오는 중" />
      ) : roster.status === "error" ? (
        <ErrorMessage error={roster.error} />
      ) : roster.members.length === 0 ? (
        <p className="text-sm text-slate-500">이 워크스페이스에 멤버가 없습니다.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {roster.members.map((row) => (
            <li
              key={row.user_id}
              className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 px-3 py-2"
            >
              <span className="text-sm text-slate-800">{memberLabel(row)}</span>
              <RoleSelect
                id={`member-role-${row.user_id}`}
                label={`${memberLabel(row)} 역할`}
                srOnlyLabel
                value={row.role}
                onChange={(next) => void handleChangeRole(row.user_id, next)}
                disabled={pending}
              />
              <Button
                variant="secondary"
                aria-label={`${memberLabel(row)} 제거`}
                disabled={pending}
                onClick={() => void handleRemove(row.user_id)}
              >
                제거
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
