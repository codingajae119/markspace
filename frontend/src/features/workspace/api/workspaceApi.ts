/**
 * 워크스페이스 엔드포인트(`/workspaces`)의 얇은 타입 래퍼 (design.md "features/workspace/api → workspaceApi").
 *
 * s16 공용 `apiClient` 위에 워크스페이스 목록·생성·상세·수정·삭제 호출만 타입 안전하게 얹는다. fetch·base URL·
 * credentials·에러 파싱·전역 401 인터셉터는 s16 단일 지점(apiClient)이 소유하므로 여기서 재구현하지 않고
 * 위임한다. `apiClient` 에는 쿼리 파라미터 전용 옵션이 없으므로 `list` 의 `limit`/`offset` 은 여기서 path
 * 문자열의 쿼리로 직접 조립한다(제공된 값만 부착; 응답 엔벨로프 `Page<T>` 에는 limit/offset 필드 없음).
 *
 * Requirements:
 * - 1.1 소비 경계(교차 관심사 재구현 금지, s16 `apiClient`·`shared` 타입만 소비)
 * - 2.1 워크스페이스 생성(`POST /workspaces` → 201 `WorkspaceRead`)
 * - 4.1 워크스페이스 설정 부분 갱신(`PATCH /workspaces/{id}` → `WorkspaceRead`)
 * - 4.4 워크스페이스 삭제(`DELETE /workspaces/{id}` → 204)
 * - 8.1 목록·상세 조회(`GET /workspaces?limit=&offset=` → `Page<WorkspaceRead>`, `GET /workspaces/{id}`)
 *
 * 계약 경계: 응답·엔벨로프 타입(`WorkspaceRead`·`Page`)과 요청 본문 타입(`WorkspaceCreate`·`WorkspaceUpdate`)은
 * `./types`(백엔드 스키마 미러)를 import 재사용하며 로컬 재선언하지 않는다(drift 방지).
 */

import { apiClient } from "@/shared/api/client";
import type {
  Page,
  WorkspaceRead,
  WorkspaceCreate,
  WorkspaceUpdate,
} from "./types";

/**
 * `GET /workspaces` 목록 경로 조립. `limit`/`offset` 은 쿼리 파라미터이며 제공된 값만 부착한다
 * (둘 다 생략 시 `/workspaces`). `URLSearchParams` 로 인코딩 정확성을 보장한다.
 */
function buildListPath(limit?: number, offset?: number): string {
  const params = new URLSearchParams();
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  if (offset !== undefined) {
    params.set("offset", String(offset));
  }
  const query = params.toString();
  return query.length > 0 ? `/workspaces?${query}` : "/workspaces";
}

/** 접근 가능한 워크스페이스 목록. `limit`/`offset` 은 쿼리로 전달된다(응답은 `Page<WorkspaceRead>`). */
function list(limit?: number, offset?: number): Promise<Page<WorkspaceRead>> {
  return apiClient.get<Page<WorkspaceRead>>(buildListPath(limit, offset));
}

/** 워크스페이스 생성. 성공 시 생성된 `WorkspaceRead`(201) 반환, 호출자는 owner 가 된다. */
function create(body: WorkspaceCreate): Promise<WorkspaceRead> {
  return apiClient.post<WorkspaceRead>("/workspaces", body);
}

/** 단일 워크스페이스 상세 조회. */
function get(id: number): Promise<WorkspaceRead> {
  return apiClient.get<WorkspaceRead>(`/workspaces/${id}`);
}

/** 워크스페이스 설정 부분 갱신(name·is_shareable·trash_retention_days). 갱신된 `WorkspaceRead` 반환. */
function update(id: number, body: WorkspaceUpdate): Promise<WorkspaceRead> {
  return apiClient.patch<WorkspaceRead>(`/workspaces/${id}`, body);
}

/** 워크스페이스 삭제(204 → `undefined`). */
function remove(id: number): Promise<void> {
  return apiClient.del<void>(`/workspaces/${id}`);
}

/** 하위 훅(useWorkspaceActions·워크스페이스 컨텍스트 소비부)이 소비하는 얇은 워크스페이스 API. */
export const workspaceApi = {
  list,
  create,
  get,
  update,
  remove,
};
