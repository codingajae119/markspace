/**
 * AdminUserForm — admin 계정 생성 폼 / 계정 상태(is_active·is_deleted) 독립 편집 컨트롤
 * (design.md "AdminUserPanel / AdminUserForm", Req 5.2·5.3·5.5·5.7).
 *
 * 한 컴포넌트가 `user` prop 유무로 두 모드를 갖는다:
 * - **생성 모드**(`user` 미제공): `login_id`·`password`·`name`·선택 `email` 을 입력받아
 *   `adminApi.createUser` 로 계정을 만든다. `is_admin`·상태 flag 는 **입력받지 않는다**(Req 5.2).
 *   성공 시 반환된 `UserRead` 를 `onSaved` 로 전달하고 입력(특히 비밀번호)을 초기화한다.
 * - **상태 편집 모드**(`user` 제공): `is_active`·`is_deleted` 를 **독립된 두 컨트롤**로 토글한다
 *   (Req 5.3 — 하나의 상태로 접합하지 않음). 각 토글은 자신의 필드만 담은 부분 갱신을 보낸다
 *   (`updateUser(id, { is_active })` 또는 `updateUser(id, { is_deleted })`) — 다른 필드는 절대
 *   함께 보내지 않는다. 성공 시 반환된 `UserRead` 를 `onSaved` 로 전달한다.
 *
 * ## 오류 처리 (Req 5.5·5.7)
 * 모든 오류는 s16 `ErrorMessage`(ApiError)로 표시한다. 상태 편집 모드에서 서버가 409(단일 admin
 * 잠금)를 반환하면 "마지막 admin은 비활동·삭제할 수 없습니다." 안내를 덧붙이고 `onSaved` 를
 * 호출하지 않는다 → 로컬 목록 상태(패널)가 시도 이전 값으로 남는다(롤백). 생성 모드의 중복
 * login_id 409·검증 422 는 `ErrorMessage` 로 표시한다.
 *
 * 계약 경계: fetch·base URL·에러 파싱·401 은 `adminApi`→s16 `apiClient` 단일 지점 위임. 상태
 * 관리·전역 컨텍스트는 소유하지 않으며, 상위 `AdminUserPanel` 이 목록 상태를 소유하고 `onSaved`
 * 로 반영한다.
 *
 * Requirements: 5.2(생성·is_admin/상태 flag 미입력), 5.3(is_active/is_deleted 독립 토글),
 * 5.5(단일 admin 409 안내·롤백), 5.7(중복 409·검증 422 오류 표시).
 */

import { useState } from "react";
import type { FormEvent, ReactElement } from "react";

import { Button, ErrorMessage } from "@/shared/ui";
import { ApiError } from "@/shared/api/errors";

import { adminApi } from "../api/adminApi";
import type { UserCreate, UserRead, UserUpdate } from "../api/types";

/** 단일 admin 잠금(409) 안내 문구(Req 5.5). */
const SINGLE_ADMIN_GUIDANCE = "마지막 admin은 비활동·삭제할 수 없습니다.";

export interface AdminUserFormProps {
  /** 제공되면 상태 편집 모드(is_active/is_deleted 독립 토글), 미제공이면 생성 모드. */
  user?: UserRead;
  /** 생성/갱신 성공 시 반환된 `UserRead` 를 전달한다(상위 목록 반영용). */
  onSaved: (user: UserRead) => void;
}

/**
 * `user` 유무로 생성/상태편집 모드를 분기한다. 두 모드 모두 `adminApi` 로 결선하고 오류는 s16
 * `ErrorMessage` 로 표시한다.
 */
export function AdminUserForm({ user, onSaved }: AdminUserFormProps): ReactElement {
  return user === undefined ? (
    <CreateUserForm onSaved={onSaved} />
  ) : (
    <UserStatusControls user={user} onSaved={onSaved} />
  );
}

/** 계정 생성 폼(Req 5.2). is_admin·상태 flag 는 입력받지 않는다. */
function CreateUserForm({ onSaved }: { onSaved: (user: UserRead) => void }): ReactElement {
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const canSubmit =
    loginId.trim().length > 0 && password.length > 0 && name.trim().length > 0 && !pending;

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    // 생성 본문: email 은 입력이 있을 때만 포함(선택 필드).
    const body: UserCreate = {
      login_id: loginId.trim(),
      password,
      name: name.trim(),
    };
    const trimmedEmail = email.trim();
    if (trimmedEmail.length > 0) {
      body.email = trimmedEmail;
    }

    setPending(true);
    setError(null);
    void adminApi
      .createUser(body)
      .then((created) => {
        onSaved(created);
        // 성공 시 입력 초기화 — 비밀번호는 화면에 보존하지 않는다.
        setLoginId("");
        setPassword("");
        setName("");
        setEmail("");
      })
      .catch((caught: unknown) => {
        // 중복 login_id 409·검증 422 등은 ApiError 로 표시(Req 5.7).
        if (caught instanceof ApiError) {
          setError(caught);
        }
      })
      .finally(() => {
        setPending(false);
      });
  };

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-slate-900">계정 생성</h3>

      {/* 중복 login_id 409·검증 422 표시(Req 5.7). */}
      <ErrorMessage error={error} />

      <div className="flex flex-wrap items-end gap-3">
        <Field id="admin-create-login-id" label="로그인 ID">
          <input
            id="admin-create-login-id"
            type="text"
            value={loginId}
            onChange={(event) => setLoginId(event.target.value)}
            disabled={pending}
            className={INPUT_CLASSES}
          />
        </Field>
        <Field id="admin-create-password" label="비밀번호">
          <input
            id="admin-create-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={pending}
            className={INPUT_CLASSES}
          />
        </Field>
        <Field id="admin-create-name" label="이름">
          <input
            id="admin-create-name"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={pending}
            className={INPUT_CLASSES}
          />
        </Field>
        <Field id="admin-create-email" label="이메일">
          <input
            id="admin-create-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={pending}
            className={INPUT_CLASSES}
          />
        </Field>
        <Button type="submit" disabled={!canSubmit}>
          계정 생성
        </Button>
      </div>
    </form>
  );
}

/**
 * 계정 상태 독립 토글(Req 5.3). is_active·is_deleted 를 각각 별개 컨트롤로 갱신하며, 각 토글은
 * 자신의 필드만 담은 부분 갱신을 보낸다(다른 필드 미포함).
 */
function UserStatusControls({
  user,
  onSaved,
}: {
  user: UserRead;
  onSaved: (user: UserRead) => void;
}): ReactElement {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  // 단일 필드만 담은 부분 갱신(Req 5.3 독립). 성공 시에만 onSaved → 실패 시 목록 상태 무변경(롤백).
  const applyPatch = (patch: UserUpdate): void => {
    if (pending) {
      return;
    }
    setPending(true);
    setError(null);
    void adminApi
      .updateUser(user.id, patch)
      .then((updated) => {
        onSaved(updated);
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

  // 단일 admin 잠금 409 안내(Req 5.5). 서버 message 는 ErrorMessage 가 별도 표시한다.
  const isSingleAdminConflict = error !== null && (error.code === "conflict" || error.status === 409);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          aria-label={`${user.login_id} ${user.is_active ? "비활성화" : "재활성화"}`}
          disabled={pending}
          onClick={() => applyPatch({ is_active: !user.is_active })}
        >
          {user.is_active ? "비활성화" : "재활성화"}
        </Button>
        <Button
          variant="secondary"
          aria-label={`${user.login_id} ${user.is_deleted ? "복원" : "삭제"}`}
          disabled={pending}
          onClick={() => applyPatch({ is_deleted: !user.is_deleted })}
        >
          {user.is_deleted ? "복원" : "삭제"}
        </Button>
      </div>

      {/* 서버 오류는 항상 표시(Req 5.7). 단일 admin 409 는 안내 문구를 덧붙인다(Req 5.5). */}
      <ErrorMessage error={error} />
      {isSingleAdminConflict ? (
        <p className="text-sm text-amber-700">{SINGLE_ADMIN_GUIDANCE}</p>
      ) : null}
    </div>
  );
}

const INPUT_CLASSES =
  "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

/** label + 컨트롤을 세로로 묶는 소형 필드 래퍼. */
function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactElement;
}): ReactElement {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
      </label>
      {children}
    </div>
  );
}
