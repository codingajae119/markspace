/**
 * admin 계정·소유권 엔드포인트(`/admin/users`·`/admin/workspaces/{id}/owner`)의 얇은 타입 래퍼
 * (design.md "features/workspace/api → adminApi").
 *
 * s16 공용 `apiClient` 위에 admin 사용자 목록·생성·부분 갱신·비밀번호 재설정·소유권 변경 호출만 타입 안전하게
 * 얹는다. fetch·base URL·credentials·에러 파싱·전역 401 인터셉터는 s16 단일 지점(apiClient)이 소유하므로
 * 여기서 재구현하지 않고 위임한다. `apiClient` 에는 쿼리 파라미터 전용 옵션이 없으므로 `listUsers` 의
 * `limit`/`offset` 은 여기서 path 문자열의 쿼리로 직접 조립한다(제공된 값만 부착; 응답 엔벨로프 `Page<T>` 에는
 * limit/offset 필드 없음).
 *
 * Requirements:
 * - 5.1 admin 계정 목록(`GET /admin/users?limit=&offset=` → `Page<UserRead>`, 삭제·비활동 포함)
 * - 5.2 admin 계정 생성(`POST /admin/users` → 201 `UserRead`)
 * - 5.3 admin 계정 상태 부분 갱신(`PATCH /admin/users/{user_id}` → `UserRead`)
 * - 5.4 admin 비밀번호 재설정(`POST /admin/users/{user_id}/password` → 204)
 * - 6.1 admin 소유권 변경(`POST /admin/workspaces/{id}/owner`, OwnerChangeRequest → `WorkspaceRead`)
 * - 8.1 목록 조회 엔벨로프(`Page<UserRead>`)
 *
 * 계약 경계: 응답·엔벨로프 타입(`UserRead`·`WorkspaceRead`·`Page`)과 요청 본문 타입(`UserCreate`·`UserUpdate`·
 * `AdminPasswordResetRequest`·`OwnerChangeRequest`)은 `./types`(백엔드 스키마 미러)를 import 재사용하며
 * 로컬 재선언하지 않는다(drift 방지).
 */

import { apiClient } from "@/shared/api/client";
import type {
  Page,
  UserRead,
  UserCreate,
  UserUpdate,
  AdminPasswordResetRequest,
  OwnerChangeRequest,
  WorkspaceRead,
} from "./types";

/**
 * `GET /admin/users` 목록 경로 조립. `limit`/`offset` 은 쿼리 파라미터이며 제공된 값만 부착한다
 * (둘 다 생략 시 `/admin/users`). `URLSearchParams` 로 인코딩 정확성을 보장한다.
 */
function buildListUsersPath(limit?: number, offset?: number): string {
  const params = new URLSearchParams();
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  if (offset !== undefined) {
    params.set("offset", String(offset));
  }
  const query = params.toString();
  return query.length > 0 ? `/admin/users?${query}` : "/admin/users";
}

/** admin 사용자 목록(삭제·비활동 포함). `limit`/`offset` 은 쿼리로 전달된다(응답은 `Page<UserRead>`). */
function listUsers(limit?: number, offset?: number): Promise<Page<UserRead>> {
  return apiClient.get<Page<UserRead>>(buildListUsersPath(limit, offset));
}

/** admin 사용자 생성. 성공 시 생성된 `UserRead`(201) 반환. */
function createUser(body: UserCreate): Promise<UserRead> {
  return apiClient.post<UserRead>("/admin/users", body);
}

/** admin 사용자 상태 부분 갱신(name·email·is_active·is_deleted). 갱신된 `UserRead` 반환. */
function updateUser(id: number, body: UserUpdate): Promise<UserRead> {
  return apiClient.patch<UserRead>(`/admin/users/${id}`, body);
}

/** admin 비밀번호 재설정(204 → `undefined`). */
function resetPassword(id: number, body: AdminPasswordResetRequest): Promise<void> {
  return apiClient.post<void>(`/admin/users/${id}/password`, body);
}

/** admin 워크스페이스 소유권 변경. 성공 시 갱신된 `WorkspaceRead`(200) 반환. */
function changeOwner(id: number, body: OwnerChangeRequest): Promise<WorkspaceRead> {
  return apiClient.post<WorkspaceRead>(`/admin/workspaces/${id}/owner`, body);
}

/** admin 콘솔(AdminUserPanel·PasswordResetDialog·AdminOwnerChangePanel)이 소비하는 얇은 admin API. */
export const adminApi = {
  listUsers,
  createUser,
  updateUser,
  resetPassword,
  changeOwner,
};
