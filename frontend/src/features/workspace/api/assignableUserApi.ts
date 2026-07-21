/**
 * 배정 가능 사용자 엔드포인트(`GET /workspaces/{id}/assignable-users`)의 얇은 타입 래퍼
 * (design.md "features/workspace/api → assignableUserApi").
 *
 * s16 공용 `apiClient` 위에 배정 가능 사용자 조회 호출만 타입 안전하게 얹는다. fetch·base URL·
 * credentials·에러 파싱·전역 401 인터셉터는 s16 단일 지점(apiClient)이 소유하므로 여기서 재구현하지
 * 않고 위임한다(교차 관심사 단일 소유). `apiClient` 는 query-param 옵션이 없어 경로에 직접 조립한다
 * (기존 목록 경로 빌더 관례). 페이지네이션 기본값은 백엔드 관례와 동일하게 limit=50·offset=0.
 *
 * Requirements:
 * - 3.1 배정 가능 사용자 목록 조회(`GET /workspaces/{id}/assignable-users` → `Page[AssignableUserRead]`)
 *
 * 계약 경계: 응답 항목 타입(`AssignableUser`)은 `./types`(백엔드 `AssignableUserRead` 미러)를 import
 * 재사용하며 로컬 재선언하지 않는다(drift 방지). 봉투 `Page<T>` 는 s16 소유(`@/shared/types/page`).
 */

import { apiClient } from "@/shared/api/client";
import type { Page } from "@/shared/types/page";
import type { AssignableUser } from "./types";

interface ListAssignableParams {
  limit?: number;
  offset?: number;
}

/** 워크스페이스의 배정 가능 사용자 페이지 조회. limit 기본 50·offset 기본 0. */
function listAssignable(
  workspaceId: number,
  params?: ListAssignableParams,
): Promise<Page<AssignableUser>> {
  const q = new URLSearchParams();
  q.set("limit", String(params?.limit ?? 50));
  q.set("offset", String(params?.offset ?? 0));
  return apiClient.get<Page<AssignableUser>>(
    `/workspaces/${workspaceId}/assignable-users?${q.toString()}`,
  );
}

/** 하위 조회 훅(`useAssignableUsers`)이 소비하는 얇은 배정 가능 사용자 API. */
export const assignableUserApi = { listAssignable };
