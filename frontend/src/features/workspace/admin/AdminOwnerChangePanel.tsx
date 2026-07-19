/**
 * AdminOwnerChangePanel — admin 워크스페이스 소유권 변경 패널
 * (design.md "AdminOwnerChangePanel", Req 6.1·6.2·6.3, INV-3 admin override).
 *
 * admin 이 대상 워크스페이스 ID 와 새 소유자 사용자 ID(`new_owner_user_id`)를 지정해
 * `adminApi.changeOwner(id, { new_owner_user_id })`(`POST /admin/workspaces/{id}/owner`)로 소유권을
 * 변경한다. 성공(200) 시 반환된 `WorkspaceRead`(이관된 워크스페이스)를 확인으로 표시한다. 두 입력 중
 * 하나라도 유효한 양의 정수가 아니면 요청 전에 막고(클라이언트 가드), 서버 오류(404 대상 미존재·403
 * 권한 미충족·검증 422 등)는 s16 `ErrorMessage`(ApiError)로 표시한다.
 *
 * 계약 경계: fetch·에러 파싱은 `adminApi`→s16 `apiClient` 위임(직접 fetch 금지). admin 게이팅은 이
 * 패널이 아니라 상위 `AdminConsolePage`(task 6.3)가 s16 `RequireAdmin` 으로 수행한다 — 이 컴포넌트는
 * 게이트 하위의 내부 패널로만 구성된다(INV-3, 요구 6.2). admin 전용 경로이므로 WS role 위계를 판정하지 않는다.
 *
 * Requirements: 6.1(소유권 변경·200 WorkspaceRead 반영), 6.2(admin 전용 경로), 6.3(누락·404·403 오류 표시).
 */

import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

import { Button, ErrorMessage } from "@/shared/ui";
import { ApiError } from "@/shared/api/errors";

import { adminApi } from "../api/adminApi";
import type { WorkspaceRead } from "../api/types";

/** 입력 문자열을 양의 정수로 파싱한다. 유효하지 않으면(빈 값·비정수·0 이하) `null` 을 돌려준다. */
function parsePositiveInt(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    return null;
  }
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/** admin WS 소유권 변경 패널. 대상 WS·새 소유자 입력을 소유하고 결과·오류를 표시한다. */
export function AdminOwnerChangePanel(): ReactElement {
  const [workspaceIdInput, setWorkspaceIdInput] = useState("");
  const [newOwnerIdInput, setNewOwnerIdInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [changed, setChanged] = useState<WorkspaceRead | null>(null);

  const workspaceId = parsePositiveInt(workspaceIdInput);
  const newOwnerUserId = parsePositiveInt(newOwnerIdInput);
  // 클라이언트 가드: 두 입력이 모두 유효한 양의 정수여야 요청을 보낸다(요구 6.3).
  const canSubmit = workspaceId !== null && newOwnerUserId !== null && !pending;

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (workspaceId === null || newOwnerUserId === null || pending) {
      return;
    }
    setPending(true);
    setError(null);
    setChanged(null);
    void adminApi
      .changeOwner(workspaceId, { new_owner_user_id: newOwnerUserId })
      .then((updated) => {
        // 200 확인: 반환된 WorkspaceRead 를 반영(요구 6.1).
        setChanged(updated);
      })
      .catch((caught: unknown) => {
        if (caught instanceof ApiError) {
          setError(caught);
        }
      })
      .finally(() => {
        setPending(false);
      });
  };

  return (
    <section aria-label="워크스페이스 소유권 변경" className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold text-slate-900">워크스페이스 소유권 변경</h2>
        <p className="text-sm text-slate-600">
          대상 워크스페이스와 새 소유자 사용자를 지정해 소유권을 이관합니다(관리자 전용).
        </p>
      </header>

      <ErrorMessage error={error} />
      {changed !== null ? (
        <p role="status" className="text-sm text-emerald-700">
          워크스페이스 &quot;{changed.name}&quot;(ID {changed.id})의 소유권이 사용자{" "}
          {newOwnerUserId}에게 이관되었습니다.
        </p>
      ) : null}

      <form onSubmit={handleSubmit} noValidate className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="admin-owner-ws-id" className="text-sm font-medium text-slate-700">
            워크스페이스 ID
          </label>
          <input
            id="admin-owner-ws-id"
            type="number"
            inputMode="numeric"
            min={1}
            value={workspaceIdInput}
            onChange={(event) => setWorkspaceIdInput(event.target.value)}
            disabled={pending}
            className="w-40 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="admin-owner-new-user-id" className="text-sm font-medium text-slate-700">
            새 소유자 사용자 ID
          </label>
          <input
            id="admin-owner-new-user-id"
            type="number"
            inputMode="numeric"
            min={1}
            value={newOwnerIdInput}
            onChange={(event) => setNewOwnerIdInput(event.target.value)}
            disabled={pending}
            className="w-40 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
          />
        </div>
        <Button type="submit" disabled={!canSubmit}>
          소유권 변경
        </Button>
      </form>
    </section>
  );
}
