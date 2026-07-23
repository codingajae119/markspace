/**
 * 문서 feature 의 워크스페이스 스코프 선택자 훅
 * (design.md "features / document → useDocumentScope").
 *
 * s16 앰비언트 계약을 얇게 감싸는 **단일 소비 지점**이다. 문서 feature 가 필요로 하는 값만
 * 재노출하며, 컨텍스트를 재구현하지 않는다. `useCurrentWorkspace()` 의 **최상위 접근자**
 * (`status`·`workspaceId`·`role`)만 읽고 중첩 필드(`currentWorkspace`·`workspaces` 등)에는
 * 접근하지 않는다. `workspaceId`·`role` 은 s16 동결 계약 형태 그대로 통과시키며(산술·가공 금지,
 * 실제 값 주입은 상위 spec 의 관심사) 형제 feature(s18 `@/features/workspace/...`)에 의존하지 않는다.
 *
 * `isAdmin` 은 `RequireRole` 과 **동일한 idiom** 으로 세션에서만 파생한다:
 * authenticated → `user.is_admin`, 그 외(loading·unauthenticated) → `false`.
 *
 * Requirements: 9.1(s16 최상위 형태 단일 바인딩), 9.2(문서 스코프 선택자·admin override 판정).
 */

import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useSession } from "@/app/session/useSession";
import type { Role } from "@/shared/auth/roles";

/** 문서 feature 가 소비하는 워크스페이스 스코프 — s16 최상위 형태의 얇은 투영. */
export interface DocumentScope {
  /** 부트스트랩/목록 상태(s16 통과). */
  status: "loading" | "ready" | "empty";
  /** 현재 WS id(라우트 파라미터용 파생 문자열, s16 통과·산술 금지) 또는 null. */
  workspaceId: string | null;
  /** 현재 WS 에서 사용자 role(s16 통과) 또는 null(비멤버·미확정). */
  role: Role | null;
  /** admin override 판정: authenticated 일 때만 `user.is_admin`, 그 외 false. */
  isAdmin: boolean;
  /** 현재 WS 의 공유 가능 여부(s16 통과·산술 금지) — `useCurrentWorkspace().isShareable` 1필드 투영. */
  isShareable: boolean;
}

/**
 * s16 앰비언트 컨텍스트에서 문서 스코프 값을 선택한다. `useCurrentWorkspace()` 최상위
 * 접근자를 그대로 통과시키고, `isAdmin` 만 세션에서 파생한다(RequireRole 동형).
 */
export function useDocumentScope(): DocumentScope {
  const { status, workspaceId, role, isShareable } = useCurrentWorkspace();
  const session = useSession();
  const isAdmin = session.status === "authenticated" ? session.user.is_admin : false;

  return { status, workspaceId, role, isAdmin, isShareable };
}
