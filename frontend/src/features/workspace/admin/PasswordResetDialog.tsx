/**
 * PasswordResetDialog — admin 대상 사용자 비밀번호 재설정 다이얼로그
 * (design.md "AdminUserPanel / PasswordResetDialog", Req 5.4·5.7).
 *
 * 대상 `user` 의 새 비밀번호를 입력받아 `adminApi.resetPassword(id, { new_password })` 로 재설정한다.
 * 성공(204) 시 재설정 완료를 사용자에게 확인(성공 메시지)하고 입력한 비밀번호를 화면에 보존하지
 * 않는다(민감 정보 미보존). 검증 422 등 오류는 s16 `ErrorMessage`(ApiError)로 표시한다.
 *
 * 계약 경계: fetch·에러 파싱은 `adminApi`→s16 `apiClient` 위임. 다이얼로그 개폐 상태는 상위
 * `AdminUserPanel` 이 소유하며(`onClose` 로 닫힘 위임), 이 컴포넌트는 입력·제출·결과 표시만 소유한다.
 *
 * Requirements: 5.4(비밀번호 재설정·204 확인), 5.7(오류 표시).
 */

import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

import { Button, ErrorMessage } from "@/shared/ui";
import { ApiError } from "@/shared/api/errors";

import { adminApi } from "../api/adminApi";
import type { UserRead } from "../api/types";

export interface PasswordResetDialogProps {
  /** 비밀번호를 재설정할 대상 계정. */
  user: UserRead;
  /** 다이얼로그 닫기 위임(개폐 상태는 상위가 소유). */
  onClose: () => void;
}

/** 대상 사용자의 새 비밀번호 입력·재설정 폼. 성공 시 완료를 확인하고 비밀번호를 보존하지 않는다. */
export function PasswordResetDialog({ user, onClose }: PasswordResetDialogProps): ReactElement {
  const [newPassword, setNewPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [succeeded, setSucceeded] = useState(false);

  const canSubmit = newPassword.length > 0 && !pending;

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setPending(true);
    setError(null);
    setSucceeded(false);
    void adminApi
      .resetPassword(user.id, { new_password: newPassword })
      .then(() => {
        // 204 확인 + 비밀번호 미보존(민감 정보).
        setSucceeded(true);
        setNewPassword("");
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
    <section aria-label={`${user.login_id} 비밀번호 재설정`} className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-slate-900">
        {user.login_id} 비밀번호 재설정
      </h3>

      <ErrorMessage error={error} />
      {succeeded ? (
        <p role="status" className="text-sm text-emerald-700">
          비밀번호가 재설정되었습니다.
        </p>
      ) : null}

      <form onSubmit={handleSubmit} noValidate className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="admin-reset-password" className="text-sm font-medium text-slate-700">
            새 비밀번호
          </label>
          <input
            id="admin-reset-password"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={pending}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
          />
        </div>
        <Button type="submit" disabled={!canSubmit}>
          재설정
        </Button>
        <Button type="button" variant="secondary" onClick={onClose}>
          닫기
        </Button>
      </form>
    </section>
  );
}
