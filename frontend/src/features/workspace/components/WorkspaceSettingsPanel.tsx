/**
 * WorkspaceSettingsPanel — owner 전용 워크스페이스 설정 UI
 * (design.md "MemberManagementPanel / WorkspaceSettingsPanel", Req 4.1·4.2·4.3·4.4·4.5·4.6·7.1·7.4·8.4).
 *
 * 현재 워크스페이스의 이름·`is_shareable` 게이트·휴지통 보관 기간을 편집하고 빈 워크스페이스를 삭제한다.
 * 모든 뮤테이션은 `useWorkspaceActions`(현재 WS id 를 대상)로 위임하며, 이 패널은 표시·입력·결선만
 * 소유한다. 저장 성공 시 s16 `refresh()` 로 현재 WS 컨텍스트에 반영된다(훅이 수행).
 *
 * ## 노출 게이팅 (D-1 role seam, 사용자 승인 2026-07-19)
 * 패널 전체를 s16 `<RequireRole minimum={Role.OWNER} currentRole={role}>` 로 감싼다. `currentRole` 은
 * s16 `useCurrentWorkspace().role`(s16 이 `null` 하드코딩 → 실제 owner 를 은닉)이 아니라 s18
 * `MembershipRoleSource.roleFor(currentWorkspace.id)` 에서 조달한다. 컴포넌트는 role 문자열을 직접
 * 비교하지 않으며(Req 7.1), owner 위계·admin override(세션 `is_admin`) 판정은 전적으로 `RequireRole`/
 * `hasWorkspaceRole` 단일 소스에 있다(Req 7.4, INV-1·2·3). owner 미만·비-admin 은 은닉된다.
 *
 * ## is_shareable 단독 소유 (Req 4.2)
 * `is_shareable` 게이트 토글 UI 는 이 패널이 **단독 소유**한다(s22 는 이 플래그를 소비만). 현재 값은 s16
 * 컨텍스트의 파생 `isShareable`(=`currentWorkspace.is_shareable`)로 표시하고, 토글 시 즉시
 * `update(id, { is_shareable })` 로 저장해 refresh 로 반영한다("즉시 반영").
 *
 * ## retention 클라이언트 가드 (Req 4.3)
 * `trash_retention_days` 는 요청 전에 양의 정수(>0)만 통과시킨다(비양수·비정수는 막고 클라 오류 표시).
 * 서버가 422 를 반환하면 s16 `ErrorMessage` 로 함께 표시한다.
 *
 * ## 클라이언트 게이팅은 보안 경계가 아님 (Req 4.6, 7.5)
 * UI 를 owner 로 게이팅했더라도 서버가 반환한 403(권한)·404(미존재)·409(비-empty)·422(검증) 오류는 항상
 * s16 `ErrorMessage` 로 표시한다. 비-empty 삭제 409(`code==="conflict"`/status 409)는 "빈 워크스페이스만
 * 삭제 가능" 안내를 덧붙인다.
 *
 * Requirements: 4.1(이름·부분 갱신·refresh), 4.2(is_shareable 단독 소유·즉시 반영), 4.3(retention 가드/422),
 * 4.4(빈 WS 삭제·409 안내), 4.5(owner 게이팅 s16 경유), 4.6(오류 표시·컨텍스트 미손상), 7.1(role 직접비교
 * 금지), 7.4(owner 미만 은닉), 8.4(교차 관심사 소비 경계).
 */

import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

import { Button, ErrorMessage } from "@/shared/ui";
import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";

import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { useWorkspaceActions } from "../hooks/useWorkspaceActions";
import type { WorkspaceRead } from "../api/types";

/**
 * owner(및 admin override) 조건에서만 노출되는 워크스페이스 설정 패널. 노출 판정은 s16 `RequireRole`
 * 단일 소스로만 수행하고, role 은 s18 `MembershipRoleSource` 에서 조달한다(D-1).
 */
export function WorkspaceSettingsPanel(): ReactElement {
  const { currentWorkspace, isShareable } = useCurrentWorkspace();
  const { roleFor } = useMembershipRoleSource();
  // D-1: role 은 MembershipRoleSource 에서 조달(useCurrentWorkspace().role 사용 금지 — 하드코딩 null).
  const role = currentWorkspace ? roleFor(currentWorkspace.id) : null;

  return (
    <RequireRole minimum={Role.OWNER} currentRole={role}>
      <WorkspaceSettingsContent workspace={currentWorkspace} isShareable={isShareable} />
    </RequireRole>
  );
}

/**
 * 게이트 통과 후 실제 설정 UI. 선택된 WS 가 없을 때의 빈 상태 안내는 이 패널이 아니라
 * `WorkspaceManagementPage` 가 **단일** 소유한다(과거 이 패널과 MemberManagementPanel 이 각자 같은 문구를
 * 렌더해 admin override 진입 시 중복 노출됨). 페이지가 WS 미선택 시 이 패널을 마운트하지 않으므로 여기서는
 * 방어적으로 아무것도 렌더하지 않는다.
 */
function WorkspaceSettingsContent({
  workspace,
  isShareable,
}: {
  workspace: WorkspaceRead | null;
  isShareable: boolean;
}): ReactElement | null {
  const { update, remove, saving, error } = useWorkspaceActions();
  const [name, setName] = useState(workspace?.name ?? "");
  const [retention, setRetention] = useState(
    workspace ? String(workspace.trash_retention_days) : "",
  );
  const [retentionError, setRetentionError] = useState<string | null>(null);

  // 빈 상태 안내는 WorkspaceManagementPage 단일 소유(중복 제거). 방어적 no-render.
  if (workspace === null) {
    return null;
  }

  const workspaceId = workspace.id;

  const handleNameSave = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length === 0 || saving) {
      return;
    }
    void update(workspaceId, { name: trimmed });
  };

  const handleShareableToggle = (): void => {
    if (saving) {
      return;
    }
    // 단독 소유: 토글 즉시 저장 → refresh 로 즉시 반영(Req 4.2).
    void update(workspaceId, { is_shareable: !isShareable });
  };

  const handleRetentionSave = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (saving) {
      return;
    }
    // 클라이언트 가드: 양의 정수(>0)만 통과(비양수·비정수는 요청 전에 차단, Req 4.3).
    const parsed = Number(retention);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      setRetentionError("보관 기간은 1 이상의 양의 정수여야 합니다.");
      return;
    }
    setRetentionError(null);
    void update(workspaceId, { trash_retention_days: parsed });
  };

  const handleDelete = (): void => {
    if (saving) {
      return;
    }
    void remove(workspaceId);
  };

  // 비-empty 삭제 409(conflict) 안내(Req 4.4). 서버 message 는 ErrorMessage 가 별도 표시한다.
  const isConflict = error !== null && (error.code === "conflict" || error.status === 409);

  return (
    <section aria-label="워크스페이스 설정" className="flex flex-col gap-6">
      <header>
        <h2 className="text-base font-semibold text-slate-900">워크스페이스 설정</h2>
      </header>

      {/* 서버 403·404·409·422 등 오류는 게이팅 여부와 무관하게 항상 표시(Req 4.6, 7.5). */}
      <ErrorMessage error={error} />
      {isConflict ? (
        <p className="text-sm text-amber-700">빈 워크스페이스만 삭제 가능합니다.</p>
      ) : null}

      {/* 이름 편집(부분 갱신, Req 4.1). */}
      <form onSubmit={handleNameSave} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="ws-settings-name" className="text-sm font-medium text-slate-700">
            워크스페이스 이름
          </label>
          <input
            id="ws-settings-name"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="w-64 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          />
        </div>
        <Button type="submit" disabled={name.trim().length === 0 || saving}>
          이름 저장
        </Button>
      </form>

      {/* is_shareable 토글(단독 소유·즉시 반영, Req 4.2). 현재 값은 s16 파생 isShareable. */}
      <div className="flex items-center gap-3">
        <input
          id="ws-settings-shareable"
          type="checkbox"
          checked={isShareable}
          disabled={saving}
          onChange={handleShareableToggle}
          className="h-4 w-4 rounded border-slate-300 text-slate-900 focus-visible:ring-2 focus-visible:ring-slate-400"
        />
        <label htmlFor="ws-settings-shareable" className="text-sm font-medium text-slate-700">
          공유 허용 (is_shareable)
        </label>
      </div>

      {/* trash_retention_days 편집(클라 가드 + 부분 갱신, Req 4.3·4.1). noValidate 로 네이티브 제약
          검증(min) 이 submit 을 가로채지 않게 해, 비양수도 명시적 JS 가드가 처리하도록 한다. */}
      <form onSubmit={handleRetentionSave} noValidate className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label
            htmlFor="ws-settings-retention"
            className="text-sm font-medium text-slate-700"
          >
            휴지통 보관 기간(일)
          </label>
          <input
            id="ws-settings-retention"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            value={retention}
            onChange={(event) => setRetention(event.target.value)}
            className="w-32 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          />
          {retentionError !== null ? (
            <p className="text-xs text-red-600">{retentionError}</p>
          ) : null}
        </div>
        <Button type="submit" disabled={saving}>
          보관 기간 저장
        </Button>
      </form>

      {/* 빈 WS 삭제(409 시 위 안내, Req 4.4). */}
      <div className="flex flex-col gap-2 border-t border-slate-200 pt-4">
        <p className="text-sm text-slate-600">
          비어 있는 워크스페이스만 삭제할 수 있습니다. 삭제 시 목록에서 제외됩니다.
        </p>
        <div>
          <Button
            variant="secondary"
            aria-label="워크스페이스 삭제"
            disabled={saving}
            onClick={handleDelete}
          >
            워크스페이스 삭제
          </Button>
        </div>
      </div>
    </section>
  );
}
