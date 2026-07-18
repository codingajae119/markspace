/**
 * 워크스페이스 응답 타입 — 백엔드 `app/workspace/schemas.py` 의 `WorkspaceRead` 미러.
 *
 * `id`·`created_at`·`updated_at` 은 백엔드 `TimestampedRead` 베이스에서 오며,
 * `updated_at` 은 null 가능하다. `created_at`/`updated_at` 은 ISO 8601 문자열로 직렬화된다.
 */
export interface WorkspaceRead {
  id: number;
  created_at: string;
  updated_at: string | null;
  name: string;
  is_shareable: boolean;
  trash_retention_days: number;
}
