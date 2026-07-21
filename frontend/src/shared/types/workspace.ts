import type { WorkspaceRole } from "@/shared/auth/roles";

/**
 * 워크스페이스 응답 타입 — 백엔드 `app/workspace/schemas.py` 의 `WorkspaceRead` 미러.
 *
 * `id`·`created_at`·`updated_at` 은 백엔드 `TimestampedRead` 베이스에서 오며,
 * `updated_at` 은 null 가능하다. `created_at`/`updated_at` 은 ISO 8601 문자열로 직렬화된다.
 *
 * `role` 은 백엔드가 목록 응답 item 에 가산한 optional·nullable 필드다(superset). 옵셔널인
 * 이유는 create/get/update 등 비목록 응답이 과거 형태로 이를 생략할 수 있기 때문이고, nullable
 * 인 이유는 백엔드가 비멤버 item(admin 경로)·비목록 경로에서 `null` 을 직렬화하기 때문이다.
 * 문자열 유니온은 {@link WorkspaceRole} 단일 소스를 재사용한다.
 */
export interface WorkspaceRead {
  id: number;
  created_at: string;
  updated_at: string | null;
  name: string;
  is_shareable: boolean;
  trash_retention_days: number;
  role?: WorkspaceRole | null;
}
