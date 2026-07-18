/**
 * 현재 워크스페이스 앰비언트 컨텍스트의 **동결된 단일 값 타입**
 * (design.md "app / workspace-context → CurrentWorkspaceProvider & useCurrentWorkspace").
 *
 * 세션 컨텍스트(`useSession`)와 대칭으로, 현재 사용자 스코프의 워크스페이스 목록·현재 선택 WS·
 * 최상위 편의 접근자(`workspaceId`·`role`·`isShareable`)를 단일 형태로 노출한다. 컨슈머
 * (s18/s19/s20/s22)는 이 형태에 **정확히** 바인딩하며, 중첩 필드(`currentWorkspace.id` 등)에
 * 산발적으로 접근하지 않는다. 이 형태의 변경은 하위 spec 재검증 트리거다(Revalidation Triggers).
 *
 * Requirements: 9.1(단일 타입 정의), 9.3(파생 접근자), 9.6(role 필드·기본값만 s16 소유).
 */

import type { WorkspaceRead } from "@/shared/types/workspace";
import type { Role } from "@/shared/auth/roles";

/**
 * 동결된 단일 컨텍스트 값 — s18/s19/s20/s22 가 이 형태에 바인딩한다.
 *
 * - `status`: 인증 후 목록 로드 결과. loading(부트스트랩 전/미인증 유휴)·ready(목록 있음)·empty(목록 없음).
 * - `workspaces`: 현재 사용자 스코프 목록(`GET /workspaces` → `Page<WorkspaceRead>` 의 items).
 * - `currentWorkspace`: 현재 선택 WS(없으면 null).
 * - `workspaceId`: `String(currentWorkspace.id)` 또는 null(라우트 파라미터용 파생값).
 * - `role`: 현재 WS 에서 현재 사용자의 role. 백엔드 `WorkspaceRead` 는 호출자 role 을 담지 않으므로
 *   s16 은 **필드·형태·기본값(null)만** 소유하고, 실제 값은 s18 멤버십 데이터 경로로 주입된다
 *   (=`RequireRole` 의 `currentRole` 주입 seam 과 동형). admin override 는 세션 `is_admin` 으로 별도 판정.
 * - `isShareable`: `currentWorkspace?.is_shareable ?? false`(파생).
 * - `selectWorkspace(id)`: 현재 WS 선택 + localStorage 영속.
 * - `refresh()`: 목록·현재 WS 재조회(s18 mutation 이후 호출).
 */
export interface CurrentWorkspaceContextValue {
  status: "loading" | "ready" | "empty";
  workspaces: WorkspaceRead[];
  currentWorkspace: WorkspaceRead | null;
  workspaceId: string | null;
  role: Role | null;
  isShareable: boolean;
  selectWorkspace(id: string): void;
  refresh(): Promise<void>;
}
