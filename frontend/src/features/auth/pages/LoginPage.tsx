/**
 * 로그인 페이지 (design.md "features/auth/components & pages → LoginPage").
 *
 * s16 게스트 접근 프레임의 대상 element 로, 최소 헤딩과 함께 `LoginForm` 을 배치한다.
 * 프레임/가드/게스트 리다이렉트 규약은 s16 라우터 셸이 단일 소유하며 여기서 재정의하지 않는다.
 *
 * Requirements:
 * - 1.1 로그인 화면(게스트 프레임 대상 element) 제공
 */

import type { ReactElement } from "react";

import { LoginForm } from "../components/LoginForm";

/** 게스트 프레임에 배치되는 로그인 화면 컨텐츠. */
export function LoginPage(): ReactElement {
  return (
    <section aria-labelledby="login-heading">
      <h1 id="login-heading">로그인</h1>
      <LoginForm />
    </section>
  );
}
