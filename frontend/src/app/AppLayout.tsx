/**
 * 인증 영역 공통 레이아웃 프레임 (design.md "shared / ui & app / layout → AppLayout", AC 7.2).
 *
 * 인증된 영역에 공통으로 적용되는 전역 앱 레이아웃 프레임이다. 하위 feature 화면이 이 프레임의
 * 콘텐츠 영역(`<main>`) 안에 렌더된다. 상단에는 header/nav 를 놓을 구조적 영역(`<header>`)만
 * 두고, feature 별 네비게이션 콘텐츠는 후속 spec(s18+)이 채운다 — 이 task 는 프레임 골격과
 * children 슬롯만 소유한다.
 *
 * 배선 주의: authenticated 분기에서 `ProtectedRoute` 를 이 프레임으로 감싸는 조립은 task 7.1
 * (`main.tsx`/router)에서 이뤄진다. 이 task 는 컴포넌트만 제공하며 라우터/세션을 건드리지 않는다.
 *
 * Requirements: 7.2(인증 영역 공통 프레임 + feature children 슬롯), 7.5(Tailwind 4).
 */

import type { ReactElement, ReactNode } from "react";

/** AppLayout props — 프레임 안에 렌더할 feature 자식 + 상단 header 네비게이션 슬롯. */
export interface AppLayoutProps {
  children: ReactNode;
  /** 상단 header 영역에 렌더할 네비게이션 콘텐츠(선택). 라우터·세션 컨텍스트를 가진
   *  조립부(`ProtectedRoute`)가 `AppHeaderNav` 를 주입한다. 미지정 시 헤더는 구조만 유지한다. */
  nav?: ReactNode;
}

/** 인증 영역 공통 프레임: 상단 header 영역 + main 콘텐츠 슬롯. */
export function AppLayout({ children, nav }: AppLayoutProps): ReactElement {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center px-4">{nav}</div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
