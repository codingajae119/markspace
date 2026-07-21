import { Role } from "@/shared/auth/roles";

/**
 * `hasWorkspaceRole` 입력 — 현재 role·admin 여부·요구 최소 role.
 *
 * `currentRole` 과 `isAdmin` 은 이 유틸이 세션/멤버십을 조회하지 않고 **호출자가 주입**한다
 * (feature 또는 `<RequireRole>` 가 `useCurrentWorkspace().role` / `useSession().is_admin`
 * 으로 취득해 전달). 순수 함수 계약을 지키기 위한 의도적 설계다(AC 6.5).
 */
export interface HasWorkspaceRoleInput {
  /** 현재 워크스페이스에서 사용자의 role. 멤버가 아니거나 미확정이면 `null`. */
  currentRole: Role | null;
  /** 세션 `is_admin`. admin 이면 role 무관하게 통과(INV-3). */
  isAdmin: boolean;
  /** UI 요소가 요구하는 최소 role. */
  minimum: Role;
}

/**
 * 워크스페이스 role 위계 판정 + admin override — 백엔드
 * `WorkspaceRoleResolver.has_at_least` 의 프론트 미러(순수 함수).
 *
 * 판정 순서(백엔드와 동일):
 * 1. `isAdmin === true` → 항상 `true`. currentRole·멤버십과 무관하며 가장 먼저 판정한다
 *    (INV-3, admin override / AC 6.3).
 * 2. `currentRole === null` → `false`. role 이 없으면(비멤버·미확정) 거부한다
 *    (AC 6.4, 비멤버·none 은 변경성 UI 미노출 / INV-2).
 * 3. 그 외 → `currentRole >= minimum`. owner ≥ member 위계로 충족 여부 판정
 *    (AC 6.2, workspace 단위 role 만 / INV-1).
 *
 * **보안 경계 아님(AC 6.6, 13.3)**: 이 판정은 UI 노출 편의일 뿐이며 서버측 권한 강제
 * (백엔드 resolver 의 403)를 대체하지 않는다. 클라이언트 게이팅을 통과·우회했다 해도
 * 실제 변경은 백엔드가 다시 판정한다.
 */
export function hasWorkspaceRole({ currentRole, isAdmin, minimum }: HasWorkspaceRoleInput): boolean {
  if (isAdmin) {
    return true;
  }
  if (currentRole === null) {
    return false;
  }
  return currentRole >= minimum;
}
