/**
 * 워크스페이스 멤버십 엔드포인트(`/workspaces/{id}/members`)의 얇은 타입 래퍼
 * (design.md "features/workspace/api → memberApi").
 *
 * s16 공용 `apiClient` 위에 멤버 추가·role 변경·제거 호출만 타입 안전하게 얹는다. fetch·base URL·
 * credentials·에러 파싱·전역 401 인터셉터는 s16 단일 지점(apiClient)이 소유하므로 여기서 재구현하지
 * 않고 위임한다(교차 관심사 단일 소유). 경로 파라미터는 워크스페이스 `{id}`·멤버 대상 사용자 `{uid}` 두
 * 가지이며, changeRole·remove 는 둘 다 필요로 한다.
 *
 * Requirements:
 * - 3.1 멤버 추가(`POST /workspaces/{id}/members` → 201 `MemberRead`)
 * - 3.2 멤버 role 변경(`PATCH /workspaces/{id}/members/{uid}` → `MemberRead`)
 * - 3.3 멤버 제거(`DELETE /workspaces/{id}/members/{uid}` → 204)
 * - 8.1 소비 경계(교차 관심사 재구현 금지, s16 `apiClient`·`./types` 미러 타입만 소비)
 *
 * 계약 경계: 응답 타입(`MemberRead`)과 요청 본문 타입(`MemberCreate`·`MemberUpdate`)은 `./types`
 * (백엔드 스키마 미러)를 import 재사용하며 로컬 재선언하지 않는다(drift 방지).
 */

import { apiClient } from "@/shared/api/client";
import type { Page } from "@/shared/types/page";
import type {
  MemberRead,
  MemberCreate,
  MemberUpdate,
  MemberRosterRow,
} from "./types";

/** 워크스페이스에 멤버 추가. 성공 시 생성된 `MemberRead`(201) 반환. */
function add(id: number, body: MemberCreate): Promise<MemberRead> {
  return apiClient.post<MemberRead>(`/workspaces/${id}/members`, body);
}

/** 멤버 role 부분 변경. 갱신된 `MemberRead` 반환. */
function changeRole(
  id: number,
  uid: number,
  body: MemberUpdate,
): Promise<MemberRead> {
  return apiClient.patch<MemberRead>(`/workspaces/${id}/members/${uid}`, body);
}

/** 워크스페이스에서 멤버 제거(204 → `undefined`). */
function remove(id: number, uid: number): Promise<void> {
  return apiClient.del<void>(`/workspaces/${id}/members/${uid}`);
}

/**
 * 워크스페이스 멤버 로스터 페이지 조회. limit 기본 50·offset 기본 0.
 *
 * `assignableUserApi.listAssignable` 의 query 조립 관례를 미러한다(`apiClient` 는 query-param 옵션이
 * 없어 경로에 직접 조립). 응답 항목은 `MemberRosterRow`(백엔드 `MemberRosterRead` 미러).
 */
function list(
  id: number,
  params?: { limit?: number; offset?: number },
): Promise<Page<MemberRosterRow>> {
  const q = new URLSearchParams();
  q.set("limit", String(params?.limit ?? 50));
  q.set("offset", String(params?.offset ?? 0));
  return apiClient.get<Page<MemberRosterRow>>(
    `/workspaces/${id}/members?${q.toString()}`,
  );
}

/** 하위 훅(멤버 관리 컨텍스트 소비부)이 소비하는 얇은 멤버십 API. */
export const memberApi = {
  add,
  changeRole,
  remove,
  list,
};
