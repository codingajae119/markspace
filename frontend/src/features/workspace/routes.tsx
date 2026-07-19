/**
 * 등록 결선: workspaceRoutes (design.md "WorkspaceRouteModule (s16 RouteModule[] export)").
 *
 * 워크스페이스 관리 화면과 admin 서브트리를 s16 **보호 슬롯**(`scope: "protected"`)에 대응시키는
 * `RouteModule[]` 을 export 한다. s16 취합 함수(`collectRoutesByScope`/`composeRouter`)가 이를 보호
 * 슬롯(`ProtectedRoute` 하위 pathless 레이아웃 자식)에 가산 합성한다(Req 8.3·8.5).
 *
 * 경계: 프레임·가드·전역 401·Provider 마운트는 s16(`@/app/router`·`ProtectedRoute`·`main.tsx`)이
 * 단일 소유하며 여기서 재정의하지 않는다. 이 모듈은 `RouteModule[]`(경로·element)만 제공한다.
 * admin 게이팅은 `AdminConsolePage` 가 내부에서 s16 `RequireAdmin`(세션 `is_admin`)으로 self-gating
 * 하므로(INV-3), 이 라우트 층은 별도 게이트를 재구현하지 않는다.
 *
 * 보호 슬롯은 pathless 레이아웃 자식이라 라우트 정의에는 **상대 경로**("workspace"/"admin")를,
 * 네비게이션·테스트용 **절대 경로**는 이 파일의 상수(WORKSPACE_PATH/ADMIN_CONSOLE_PATH)를 쓴다
 * (하드코딩 산재 금지, s17 CHANGE_PASSWORD_PATH idiom).
 *
 * Requirements:
 * - 8.3 워크스페이스 화면을 s16 보호 프레임 하위 경로로 결선
 * - 8.5 admin 화면군을 s16 RouteModule 계약(보호 슬롯)에 결선(RequireAdmin 하위)
 */

import type { ReactElement } from "react";

import type { RouteModule } from "@/app/routeModule";

import { WorkspaceSwitcher } from "./components/WorkspaceSwitcher";
import { CreateWorkspaceDialog } from "./components/CreateWorkspaceDialog";
import { MemberManagementPanel } from "./components/MemberManagementPanel";
import { WorkspaceSettingsPanel } from "./components/WorkspaceSettingsPanel";
import { AdminConsolePage } from "./admin/AdminConsolePage";

// s18 소유 화면 경로(절대). 보호 슬롯 상대 경로("workspace"/"admin")와 짝을 이루며, 네비게이션·
// 테스트는 이 상수를 소비한다(단일 소스로 여기 정의; 하드코딩 산재 금지).
export const WORKSPACE_PATH = "/workspace";
export const ADMIN_CONSOLE_PATH = "/admin";

/**
 * 워크스페이스 관리 화면. 이미 구현된 스위처·생성 폼·owner 패널(멤버/설정)을 하나의 관리 페이지로
 * 조합한다. owner 패널은 s18 `MembershipRoleSource` role 로 self-gating 하므로(비-owner 은닉) 여기서
 * 게이트를 재구현하지 않는다. 라우트 element 조합만 담당하는 in-boundary 컴포넌트다.
 */
function WorkspaceManagementPage(): ReactElement {
  return (
    <section aria-labelledby="workspace-management-heading" className="flex flex-col gap-8">
      <header>
        <h1 id="workspace-management-heading" className="text-lg font-semibold text-slate-900">
          워크스페이스 관리
        </h1>
      </header>

      <WorkspaceSwitcher />
      <CreateWorkspaceDialog />
      <MemberManagementPanel />
      <WorkspaceSettingsPanel />
    </section>
  );
}

/** 워크스페이스 관리 화면·admin 서브트리를 s16 보호 슬롯에 대응시키는 등록 결선 계약. */
export const workspaceRoutes: RouteModule[] = [
  {
    scope: "protected",
    routes: [
      { path: "workspace", element: <WorkspaceManagementPage /> },
      { path: "admin", element: <AdminConsolePage /> },
    ],
  },
];
