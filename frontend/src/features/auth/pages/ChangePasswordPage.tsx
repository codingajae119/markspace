/**
 * 본인 비밀번호 변경 페이지 (design.md "features/auth/components & pages → ChangePasswordPage",
 * "비밀번호 변경 플로우").
 *
 * s16 보호 프레임의 대상 element 로, `current_password`·`new_password` 제어 입력과 제출 컨트롤을 렌더한다.
 * 대상은 항상 현재 인증 사용자로 고정하며 타인 지정 입력을 제공하지 않는다(Req 4.1). 제출 시
 * `event.preventDefault()` 후 `useChangePassword().submit({ current_password, new_password })` 를 호출한다.
 * 성공(`succeeded === true`)하면 성공 상태를 표시하고 입력을 안전한 초기 상태로 정리한다(Req 4.3).
 * 실패는 `useChangePassword().error` 를 s16 `ErrorMessage` 로 표면화하며, 422 `unprocessable`(현재 비밀번호
 * 불일치, Req 4.4)와 422 `validation_error`(새 비밀번호 정책 `field_errors`, Req 4.5)를 사유별 분기 없이 동일
 * 유틸로 표시한다. 진행 중(`submitting`)에는 입력·제출을 비활성화하고 `Spinner` 로 로딩을 표시한다.
 *
 * 새 비밀번호 최소 길이(8자)의 최종 강제는 백엔드 계약(422)이 소유하며, 이 화면은 클라이언트 검증을 보안
 * 경계로 취급하지 않는다(Req 4.6). 편의 안내는 선택 사항이라 여기서는 두지 않고 백엔드 계약을 단일 강제로 둔다.
 *
 * 계약 경계(모두 s16 소비): `Button`·`Spinner`·`ErrorMessage` 는 `@/shared/ui` 배럴에서만, 비밀번호 변경
 * useCase 는 같은 feature 의 `useChangePassword` 에서만 소비한다(다른 feature·apiClient·useSession 직접 import 금지).
 *
 * Requirements:
 * - 4.1 현재/새 비밀번호 입력·제출 제공, 대상은 현재 사용자 고정(타인 지정 입력 미제공)
 * - 4.3 성공(204) 시 성공 상태 표시 + 입력 필드 안전 초기화
 * - 4.4 422 unprocessable(현재 비밀번호 불일치) message 표면화(변경 미적용)
 * - 4.5 422 validation_error(새 비밀번호 정책) field_errors 표면화 — 4.4 와 동일 유틸(분기 없음)
 * - 4.6 정책 최종 강제는 백엔드 계약 소유(프론트 검증은 보안 경계 아님)
 */

import { useEffect, useState, type FormEvent, type ReactElement } from "react";

import { Button, Spinner, ErrorMessage } from "@/shared/ui";
import { useChangePassword } from "../hooks/useChangePassword";

/** 현재/새 비밀번호 제어 입력과 제출을 렌더하고 useChangePassword 플로우에 결선한다. */
export function ChangePasswordPage(): ReactElement {
  const { submit, submitting, succeeded, error } = useChangePassword();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  // 성공 신호가 서면 입력을 안전한 초기 상태로 정리한다(Req 4.3). succeeded 전이에만 반응하여
  // 렌더 중 setState 로 React 와 다투지 않는다(effect 로 커밋 이후 1회 수행, 이미 빈 값이면 no-op).
  useEffect(() => {
    if (succeeded) {
      setCurrentPassword("");
      setNewPassword("");
    }
  }, [succeeded]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    // 기본 폼 제출(페이지 리로드)을 막고 useChangePassword 플로우로만 진행한다.
    event.preventDefault();
    void submit({ current_password: currentPassword, new_password: newPassword });
  };

  return (
    <section aria-labelledby="change-password-heading">
      <h1 id="change-password-heading">비밀번호 변경</h1>
      <form onSubmit={handleSubmit} noValidate>
        <div>
          <label htmlFor="current_password">현재 비밀번호</label>
          <input
            id="current_password"
            name="current_password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            disabled={submitting}
          />
        </div>
        <div>
          <label htmlFor="new_password">새 비밀번호</label>
          <input
            id="new_password"
            name="new_password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={submitting}
          />
        </div>

        {/* 성공 신호. 입력은 effect 가 초기화하며 여기서는 성공 표시만 담당(Req 4.3). */}
        {succeeded ? <p role="status">비밀번호가 변경되었습니다.</p> : null}

        {/* 단일 에러 표시 유틸(s16). 422 두 갈래(unprocessable·validation_error)를 분기 없이 표면화. null → 미렌더. */}
        <ErrorMessage error={error} />

        <Button type="submit" disabled={submitting}>
          {submitting ? <Spinner /> : "비밀번호 변경"}
        </Button>
      </form>
    </section>
  );
}
