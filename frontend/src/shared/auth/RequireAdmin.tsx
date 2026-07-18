/**
 * 선언형 admin 라우트/화면 게이팅 컴포넌트 (design.md "shared / auth → RolePermissions & RequireRole").
 *
 * 판정을 오직 `useSession()` 의 `is_admin`(INV-3)으로만 수행하며, 워크스페이스 role 과 완전히
 * 독립적이다(AC 13.2). 따라서 `hasWorkspaceRole`·`Role` 위계는 여기서 관여하지 않는다
 * (WS role 게이팅은 형제 표면 {@link RequireRole} 이 담당). 세션이 authenticated 이고
 * `user.is_admin === true` 일 때만 `children` 을 렌더하고, 그 외(비-admin authenticated·loading·
 * unauthenticated)에는 `fallback`(기본 `null`)을 렌더한다.
 *
 * `RequireAdmin` 은 `useSession` 을 `@/app/session` 에서 직접 소비한다: 설계상 승인된 shared→app
 * seam 이며(계약 "is_admin으로만 판정", INV-3), 별도 role 데이터 경로를 두지 않는다.
 *
 * **s16-소유 게이팅 표면**: `hasWorkspaceRole`·`<RequireRole>`(WS role) 과 `<RequireAdmin>`(admin)
 * 은 함께 s16 이 단일 소유하는 게이팅 표면을 이루며, s18 admin 콘솔 화면은 이를 재구현하지 않고
 * 그대로 소비한다(AC 13.1·13.2).
 *
 * **보안 경계 아님(AC 6.6, 13.3)**: 클라이언트 게이팅은 UI 노출 편의일 뿐 서버측 권한 강제
 * (백엔드 403)를 대체하지 않는다.
 *
 * Requirements: 13.1(s16-소유 게이팅 표면), 13.2(세션 is_admin 판정·WS role 독립),
 * 13.3(보안 경계 아님).
 */

import type { ReactNode } from "react";

import { useSession } from "@/app/session/useSession";

/** `<RequireAdmin>` props — design.md `RequireAdminProps` 계약. */
export interface RequireAdminProps {
  /** 미충족 시 대체 렌더(기본 `null`, 라우트 사용 시 리다이렉트/차단 요소). */
  fallback?: ReactNode;
  /** admin 일 때 렌더할 게이팅 대상. */
  children: ReactNode;
}

/**
 * 세션이 authenticated 이고 `user.is_admin === true` 이면 `children`, 아니면 `fallback ?? null`
 * 을 렌더한다. 판정은 세션 `is_admin` 만으로 이뤄지며 워크스페이스 role 과 무관하다(INV-3, 13.2).
 */
export function RequireAdmin({ fallback = null, children }: RequireAdminProps): ReactNode {
  const session = useSession();
  const isAdmin = session.status === "authenticated" && session.user.is_admin;

  return isAdmin ? children : fallback;
}
