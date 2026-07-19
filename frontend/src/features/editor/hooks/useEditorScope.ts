/**
 * 편집(editor) feature 의 워크스페이스·세션 스코프 선택자 훅
 * (design.md "features/editor → useEditorScope").
 *
 * s16 앰비언트 계약을 얇게 감싸는 **단일 소비 지점**이다. 편집 게이팅이 필요로 하는 값만
 * 재노출하며, 컨텍스트·세션을 재구현하지 않는다. `useCurrentWorkspace()` 의 **최상위 접근자**
 * (`workspaceId`·`role`)만 읽고 중첩 필드(`currentWorkspace`·`workspaces`·`status` 등)에는
 * 접근하지 않는다. `workspaceId`·`role` 은 s16 동결 계약 형태 그대로 통과시키며(산술·가공·발명
 * 금지, `role` 실제 값 주입은 s18 멤버십 경로의 관심사) 형제 feature(`@/features/...`)에
 * 의존하지 않는다. s16 과 **동명 훅(`useCurrentWorkspace`)을 재정의하지 않는다** — 이름 충돌·
 * drift 를 피하기 위해 얇은 래퍼는 `useEditorScope` 로 명명한다.
 *
 * `isAdmin`·`currentUserId` 는 `RequireRole` 과 **동일한 idiom** 으로 세션에서만 파생한다:
 * authenticated → `user.is_admin`·`user.id`, 그 외(loading·unauthenticated) → `false`·`null`.
 *
 * Requirements: 7.1(현재 WS·세션 단일 소비·미구현), 7.2(admin bypass 판정 재료 제공).
 */

import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useSession } from "@/app/session/useSession";
import type { Role } from "@/shared/auth/roles";

/** 편집 feature 가 소비하는 워크스페이스·세션 스코프 — s16 최상위 형태의 얇은 투영. */
export interface EditorScope {
  /** 현재 WS id(라우트 파라미터용 파생 문자열, s16 통과·산술 금지) 또는 null. */
  workspaceId: string | null;
  /** 현재 WS 에서 사용자 role(s16 통과·s18 주입값) 또는 null(비멤버·미확정). */
  role: Role | null;
  /** admin override 판정: authenticated 일 때만 `user.is_admin`, 그 외 false. */
  isAdmin: boolean;
  /** 현재 사용자 식별자: authenticated 일 때만 `user.id`, 그 외 null. */
  currentUserId: number | null;
}

/**
 * s16 앰비언트 컨텍스트·세션에서 편집 스코프 값을 선택한다. `useCurrentWorkspace()` 최상위
 * 접근자(`workspaceId`·`role`)를 그대로 통과시키고, `isAdmin`·`currentUserId` 만 세션에서
 * 파생한다(RequireRole 동형).
 */
export function useEditorScope(): EditorScope {
  const { workspaceId, role } = useCurrentWorkspace();
  const session = useSession();
  const isAdmin = session.status === "authenticated" ? session.user.is_admin : false;
  const currentUserId = session.status === "authenticated" ? session.user.id : null;

  return { workspaceId, role, isAdmin, currentUserId };
}
