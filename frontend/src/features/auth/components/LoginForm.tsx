/**
 * 로그인 폼 컴포넌트 (design.md "features/auth/components & pages → LoginForm").
 *
 * `login_id`·`password` 제어 입력과 제출 컨트롤(`<form>` + submit 버튼)을 렌더한다.
 * 제출 시 `event.preventDefault()` 후 `useLogin().submit({ login_id, password })` 를 호출한다.
 * 진행 중(`submitting`)에는 입력·제출 컨트롤을 비활성화하고 `Spinner` 로 로딩을 표시하여
 * 중복 제출을 막는다(Req 1.4). `useLogin().error` 를 s16 `ErrorMessage` 로 인라인 표시하며,
 * 401 자격/비활동/삭제(단일 메시지)와 기타 4xx/5xx 를 동일 유틸로 표면화한다(Req 2.1·2.4).
 * 리다이렉트/returnTo 복귀는 useLogin 소관이며 이 폼은 네비게이션하지 않는다.
 *
 * 계약 경계(모두 s16 소비): `Button`·`Spinner`·`ErrorMessage` 는 `@/shared/ui` 배럴에서만,
 * 로그인 useCase 는 같은 feature 의 `useLogin` 에서만 소비한다(다른 feature import 금지).
 *
 * Requirements:
 * - 1.1 login_id·password 입력·제출 컨트롤 제공
 * - 1.4 진행 중 제출 비활성 + 로딩 인디케이터(중복 제출 방지)
 * - 2.1 실패 401 을 인라인 표시(리다이렉트 없음) / 2.4 401 외 4xx/5xx 도 동일 유틸
 * - 2.5 재제출 시 직전 오류 해제(useLogin 이 error 를 null 로 초기화 → null 이면 미렌더)
 */

import { useState, type FormEvent, type ReactElement } from "react";

import { Button, Spinner, ErrorMessage } from "@/shared/ui";
import { useLogin } from "../hooks/useLogin";

/** login_id·password 제어 입력과 제출을 렌더하고 useLogin 플로우에 결선한다. */
export function LoginForm(): ReactElement {
  const { submit, submitting, error } = useLogin();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    // 기본 폼 제출(페이지 리로드)을 막고 useLogin 플로우로만 진행한다.
    event.preventDefault();
    void submit({ login_id: loginId, password });
  };

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div>
        <label htmlFor="login_id">아이디</label>
        <input
          id="login_id"
          name="login_id"
          type="text"
          autoComplete="username"
          value={loginId}
          onChange={(event) => setLoginId(event.target.value)}
          disabled={submitting}
        />
      </div>
      <div>
        <label htmlFor="password">비밀번호</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={submitting}
        />
      </div>

      {/* 단일 에러 표시 유틸(s16). error 가 null 이면 아무것도 렌더하지 않는다. */}
      <ErrorMessage error={error} />

      <Button type="submit" disabled={submitting}>
        {submitting ? <Spinner /> : "로그인"}
      </Button>
    </form>
  );
}
