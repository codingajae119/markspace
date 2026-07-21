/**
 * 전역 네비게이션 헤더 콘텐츠 (인증 영역 공통 프레임의 header 슬롯).
 *
 * s16 은 `AppLayout` 에 header 구조 영역만 두고 "네비게이션 콘텐츠는 후속 spec 이 채운다"는
 * seam 을 남겼으나, 어떤 feature spec 도 이 슬롯을 채우지 않아 로그인 후 워크스페이스/문서/관리자
 * 화면으로 이동할 링크가 전혀 없었다. 이 컴포넌트가 그 seam 을 채운다.
 *
 * 구성:
 * - 브랜드 링크(홈=문서 메인)
 * - 주요 이동 링크: 문서(`ROUTES.root`) · 워크스페이스(`WORKSPACE_PATH`)
 * - 관리자 콘솔 링크(`ADMIN_CONSOLE_PATH`) — s16 `RequireAdmin`(세션 `is_admin`)으로 게이팅하여
 *   admin 세션에만 노출한다(INV-3, 콘솔 자체도 `RequireAdmin` self-gating 이라 이중 안전).
 * - 로그아웃(auth feature `LogoutButton`)
 *
 * 배치: `ProtectedRoute`(라우터·세션 컨텍스트 보유) 가 `AppLayout` 의 nav 슬롯으로 주입한다.
 * app 계층 조립부(main.tsx)가 이미 feature 를 소비하는 것과 동일한 합성 경계다.
 */

import type { ReactElement } from "react";
import { NavLink } from "react-router-dom";

import { ROUTES } from "@/app/routes";
import { RequireAdmin } from "@/shared/auth/RequireAdmin";
import { LogoutButton } from "@/features/auth/components/LogoutButton";
import { WORKSPACE_PATH, ADMIN_CONSOLE_PATH } from "@/features/workspace/routes";
import { CurrentWorkspaceIndicator } from "@/features/workspace/components/CurrentWorkspaceIndicator";

/** 활성 라우트를 강조하는 NavLink 클래스 계산기. */
function navLinkClass({ isActive }: { isActive: boolean }): string {
  const base =
    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
    "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400";
  return isActive
    ? `${base} bg-slate-900 text-white`
    : `${base} text-slate-600 hover:bg-slate-100 hover:text-slate-900`;
}

/** 인증 영역 상단 헤더에 놓이는 전역 네비게이션. */
export function AppHeaderNav(): ReactElement {
  return (
    <div className="flex w-full items-center gap-4">
      <NavLink to={ROUTES.root} end className="text-base font-semibold text-slate-900">
        Notion-lite
      </NavLink>

      <nav aria-label="주요" className="flex items-center gap-1">
        <NavLink to={ROUTES.root} end className={navLinkClass}>
          문서
        </NavLink>
        <NavLink to={WORKSPACE_PATH} className={navLinkClass}>
          워크스페이스
        </NavLink>
        {/* 관리자 링크는 admin 세션에만 노출한다(세션 is_admin, INV-3). */}
        <RequireAdmin>
          <NavLink to={ADMIN_CONSOLE_PATH} className={navLinkClass}>
            관리자
          </NavLink>
        </RequireAdmin>
      </nav>

      {/*
       * 현재 WS·역할 배지: 모든 인증 화면에서 활성 워크스페이스와 내 역할(owner/editor/viewer)을
       * 항상 노출한다. 문서 탭 등으로 전이해도 선택된 WS 를 헤더에서 확인할 수 있게 하는 단일 표시 지점.
       */}
      <div className="ml-auto flex items-center gap-3">
        <CurrentWorkspaceIndicator />
        <LogoutButton />
      </div>
    </div>
  );
}
