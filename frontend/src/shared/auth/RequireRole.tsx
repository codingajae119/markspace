/**
 * 선언형 워크스페이스 role 게이팅 컴포넌트 (design.md "shared / auth → RolePermissions & RequireRole").
 *
 * `hasWorkspaceRole` 순수 유틸을 감싸는 얇은 래퍼로, 조건 충족 시에만 `children` 을 렌더한다.
 * 위계·admin override 규칙은 유틸에만 정의되며(단일 소스, INV) 여기서 재구현하지 않는다.
 *
 * - `isAdmin` 은 `useSession()` 에서만 취득한다: authenticated → `user.is_admin`, 그 외
 *   (loading·unauthenticated) → `false`(설계 승인된 shared→app 주입 seam, AC 6.5·INV-3).
 * - `currentRole` 은 feature 가 현재 WS 멤버십(`useCurrentWorkspace().role`)에서 주입하는 prop
 *   이며, 이 컴포넌트는 role 을 조회하지 않는다(s18 소유 데이터 경로).
 * - 미충족 시 `fallback`(기본 `null`)을 렌더한다.
 *
 * **보안 경계 아님(AC 6.6, 13.3)**: 클라이언트 게이팅은 UI 노출 편의일 뿐 서버측 권한 강제
 * (백엔드 403)를 대체하지 않는다.
 *
 * Requirements: 6.5(재사용 유틸 + 선언형 게이팅 컴포넌트, currentRole 주입은 feature 수행).
 */

import type { ReactNode } from "react";

import { hasWorkspaceRole } from "@/shared/auth/permissions";
import type { Role } from "@/shared/auth/roles";
import { useSession } from "@/app/session/useSession";

/** `<RequireRole>` props — design.md `RequireRoleProps` 계약. */
export interface RequireRoleProps {
  /** UI 요소가 요구하는 최소 role. */
  minimum: Role;
  /** 현재 워크스페이스에서 사용자의 role. 비멤버·미확정이면 `null`(feature 가 주입). */
  currentRole: Role | null;
  /** 미충족 시 대체 렌더(기본 `null`). */
  fallback?: ReactNode;
  /** 충족 시 렌더할 게이팅 대상. */
  children: ReactNode;
}

/**
 * `hasWorkspaceRole({ currentRole, isAdmin, minimum })` 충족 시 `children`, 아니면
 * `fallback ?? null` 을 렌더한다. `isAdmin` 은 세션이 authenticated 일 때만 `user.is_admin`.
 */
export function RequireRole({
  minimum,
  currentRole,
  fallback = null,
  children,
}: RequireRoleProps): ReactNode {
  const session = useSession();
  const isAdmin = session.status === "authenticated" ? session.user.is_admin : false;

  return hasWorkspaceRole({ currentRole, isAdmin, minimum }) ? children : fallback;
}
