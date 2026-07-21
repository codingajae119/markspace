/**
 * AssignableUserSelect — 배정 가능 사용자 선택 UI + loading/empty/error 표면화
 * (design.md "AssignableUserSelect (신규, presentational)", Req 3.1·3.5·3.6·4.1).
 *
 * 순수 표시 컴포넌트다: 데이터·reload 는 상위(`useAssignableUsers`)가 소유하고 이 컴포넌트는
 * 어떤 fetch 도 하지 않는다. `status` 를 판별자로 삼아 정확히 하나의 표면만 렌더한다 —
 * loading→`<Spinner>`(선택 비활성, Req 3.6), ready+empty→`<EmptyState>`(Req 3.5),
 * error→`<ErrorMessage>`(Req 4.1), 그 외 스타일드 `<select>`(Req 3.1).
 *
 * 옵션 라벨은 `이름 (email)` 이며 email 이 null/빈 값이면 이름만 표시한다(Req 1.3). 빈 선택을
 * 나타내는 placeholder 옵션을 포함해 `value === null`(미선택) 을 표현 가능하게 하고, 선택 시
 * `onChange(userId)` 를, placeholder 선택 시 `onChange(null)` 을 전달한다. role 선택은 이
 * 컴포넌트 책임이 아니며 상위 패널이 기존 `RoleSelect` 를 사용한다.
 *
 * Requirements: 3.1(name·email 표시·선택), 3.5(0명 안내), 3.6(로딩 표시), 4.1(조회 실패 표시).
 */

import type { ReactElement } from "react";

import { Spinner, EmptyState, ErrorMessage } from "@/shared/ui";
import type { ApiError } from "@/shared/api/errors";

import type { AssignableUser } from "../api/types";

export interface AssignableUserSelectProps {
  /** 배정 가능 사용자 목록(상위 훅 소유 데이터). */
  users: AssignableUser[];
  /** 조회 상태 판별자 — 정확히 하나의 표면을 렌더한다. */
  status: "loading" | "ready" | "error";
  /** 조회 오류(`status==="error"` 일 때 표시). */
  error: ApiError | null;
  /** 현재 선택된 user id(미선택은 `null`). */
  value: number | null;
  /** 선택 변경 시 user id(placeholder 선택 시 `null`) 를 전달한다. */
  onChange: (userId: number | null) => void;
  /** 비활성 여부(진행 중·게이팅 시, 선택). */
  disabled?: boolean;
}

const SELECT_CLASSES =
  "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

/** 사용자 표시 라벨 — email 이 있으면 `이름 (email)`, 없으면 이름만(Req 1.3). */
function optionLabel(user: AssignableUser): string {
  return user.email ? `${user.name} (${user.email})` : user.name;
}

/** status 를 판별자로 하나의 표면만 렌더하는 순수 표시 컴포넌트. */
export function AssignableUserSelect({
  users,
  status,
  error,
  value,
  onChange,
  disabled,
}: AssignableUserSelectProps): ReactElement {
  if (status === "loading") {
    return <Spinner label="배정 가능한 사용자 불러오는 중" />;
  }

  if (status === "error") {
    return <ErrorMessage error={error} />;
  }

  if (users.length === 0) {
    return (
      <EmptyState
        title="배정 가능한 사용자가 없습니다"
        message="이 워크스페이스에 추가할 수 있는 사용자가 없습니다."
      />
    );
  }

  return (
    <select
      value={value === null ? "" : String(value)}
      disabled={disabled}
      // 빈 값은 placeholder(미선택)→null, 그 외는 옵션 value(user id 문자열)→number.
      onChange={(event) =>
        onChange(event.target.value === "" ? null : Number(event.target.value))
      }
      className={SELECT_CLASSES}
    >
      <option value="">사용자 선택</option>
      {users.map((user) => (
        <option key={user.id} value={String(user.id)}>
          {optionLabel(user)}
        </option>
      ))}
    </select>
  );
}
