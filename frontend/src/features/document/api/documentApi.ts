/**
 * 문서(`/workspaces/{id}/documents`·`/documents`)·휴지통(`/workspaces/{id}/trash`·`/trash`)
 * 엔드포인트의 얇은 타입 래퍼 (design.md "features/document/api → documentApi").
 *
 * s16 공용 `apiClient` 위에 문서 목록·상세·생성·수정·이동·삭제와 휴지통 목록·복원·영구삭제
 * 호출만 타입 안전하게 얹는다. fetch·base URL·credentials·에러 파싱(`ApiError`)·전역 401
 * 인터셉터는 s16 단일 지점(apiClient)이 소유하므로 여기서 재구현하지 않고 위임한다. `apiClient`
 * 에는 쿼리 파라미터 전용 옵션이 없으므로 `limit`/`offset` 은 여기서 `URLSearchParams` 로 path
 * 쿼리에 직접 조립한다(응답 엔벨로프 `Page<T>` 에는 limit/offset 필드 없음).
 *
 * Requirements:
 * - 1.1 소비 경계(교차 관심사 재구현 금지, s16 `apiClient`·`shared`/`../types` 타입만 소비)
 * - 1.2 전체 활성 문서 병합 로더(`loadAllActiveDocuments`: limit/offset 순회로 `page.total` 까지 누적)
 * - 3.1 문서 부분 갱신(`PATCH /documents/{id}` → `DocumentRead`)
 * - 4.1 문서 이동/재정렬(`POST /documents/{id}/move` → `DocumentRead`)
 * - 5.1 문서 삭제→휴지통(`DELETE /documents/{id}` → 204)
 * - 6.1 휴지통 목록(`GET /workspaces/{id}/trash?limit=&offset=` → `Page<TrashBundleRead>`)
 * - 7.1 휴지통 묶음 복원(`POST /trash/{bundleId}/restore` → 204)
 * - 8.1 문서 목록·상세·생성(`GET`·`POST /workspaces/{id}/documents`, `GET /documents/{id}`)
 * - 8.3 휴지통 묶음 영구삭제(`DELETE /trash/{bundleId}` → 204)
 * - 8.4 204 무본문 응답은 `Promise<void>`(apiClient 가 `undefined` 반환)
 * - 9.6 목록 쿼리 조립 단일 규약(`URLSearchParams`)
 *
 * 계약 경계: 응답·엔벨로프 타입(`DocumentRead`·`TrashBundleRead`·`Page`)과 요청 본문
 * 타입(`DocumentCreate`·`DocumentUpdate`·`DocumentMoveRequest`)은 `../types`(task 1.1,
 * 백엔드 스키마 미러)를 import 재사용하며 로컬 재선언하지 않는다(drift 방지).
 */

import { apiClient } from "@/shared/api/client";
import type {
  Page,
  DocumentRead,
  DocumentCreate,
  DocumentUpdate,
  DocumentMoveRequest,
  TrashBundleRead,
} from "../types";

/**
 * `loadAllActiveDocuments` 병합 로더의 페이지 크기. 한 번의 목록 호출로 가져올 최대 항목 수이며,
 * 트리 조립을 위해 전체를 순회 병합할 때 offset 증가 폭 상한이 아닌 페이지 단위 크기로 쓰인다.
 */
const ACTIVE_PAGE_SIZE = 100;

/** `limit`/`offset` 을 쿼리 문자열로 조립(`URLSearchParams` 로 인코딩 정확성 보장). */
function buildPagedPath(base: string, limit: number, offset: number): string {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `${base}?${params.toString()}`;
}

/** 워크스페이스 문서 목록(단일 페이지). `limit`/`offset` 은 쿼리로 전달된다. */
function listDocuments(
  workspaceId: string,
  limit: number,
  offset: number,
): Promise<Page<DocumentRead>> {
  return apiClient.get<Page<DocumentRead>>(
    buildPagedPath(`/workspaces/${workspaceId}/documents`, limit, offset),
  );
}

/**
 * 워크스페이스의 전체 활성 문서를 페이지 순회로 병합해 평면 배열로 반환한다(Req 1.2).
 *
 * offset 을 0 부터 시작해 `listDocuments` 를 반복 호출하며 `page.items` 를 누적하고,
 * 누적 개수가 `page.total` 에 도달하면 종료한다. 어떤 페이지가 0개를 반환하면(총계 미달이어도)
 * 무한 루프를 막기 위해 즉시 종료한다.
 */
async function loadAllActiveDocuments(
  workspaceId: string,
): Promise<DocumentRead[]> {
  const accumulated: DocumentRead[] = [];
  let offset = 0;
  for (;;) {
    const page = await listDocuments(workspaceId, ACTIVE_PAGE_SIZE, offset);
    accumulated.push(...page.items);
    // 빈 페이지 가드: 총계에 못 미쳐도 더 진행할 항목이 없으면 종료(무한 루프 방지).
    if (page.items.length === 0) {
      break;
    }
    if (accumulated.length >= page.total) {
      break;
    }
    offset += page.items.length;
  }
  return accumulated;
}

/** 단일 문서 상세 조회. */
function getDocument(id: number): Promise<DocumentRead> {
  return apiClient.get<DocumentRead>(`/documents/${id}`);
}

/** 문서/하위 문서 생성. 성공 시 생성된 `DocumentRead` 반환. */
function createDocument(
  workspaceId: string,
  body: DocumentCreate,
): Promise<DocumentRead> {
  return apiClient.post<DocumentRead>(
    `/workspaces/${workspaceId}/documents`,
    body,
  );
}

/** 문서 부분 갱신(title). 갱신된 `DocumentRead` 반환. */
function updateDocument(
  id: number,
  body: DocumentUpdate,
): Promise<DocumentRead> {
  return apiClient.patch<DocumentRead>(`/documents/${id}`, body);
}

/** 문서 이동/재정렬(new_parent_id·before/after_sibling_id). 갱신된 `DocumentRead` 반환. */
function moveDocument(
  id: number,
  body: DocumentMoveRequest,
): Promise<DocumentRead> {
  return apiClient.post<DocumentRead>(`/documents/${id}/move`, body);
}

/** 문서 삭제(→ 휴지통, 204 → `undefined`). */
function deleteDocument(id: number): Promise<void> {
  return apiClient.del<void>(`/documents/${id}`);
}

/** 워크스페이스 휴지통 묶음 목록(단일 페이지). `limit`/`offset` 은 쿼리로 전달된다. */
function listTrash(
  workspaceId: string,
  limit: number,
  offset: number,
): Promise<Page<TrashBundleRead>> {
  return apiClient.get<Page<TrashBundleRead>>(
    buildPagedPath(`/workspaces/${workspaceId}/trash`, limit, offset),
  );
}

/** 휴지통 묶음 복원(204 → `undefined`). */
function restoreBundle(bundleId: number): Promise<void> {
  return apiClient.post<void>(`/trash/${bundleId}/restore`);
}

/** 휴지통 묶음 영구삭제(204 → `undefined`). */
function purgeBundle(bundleId: number): Promise<void> {
  return apiClient.del<void>(`/trash/${bundleId}`);
}

/** 하위 훅·페이지 loader 가 소비하는 얇은 문서/휴지통 API. */
export const documentApi = {
  loadAllActiveDocuments,
  listDocuments,
  getDocument,
  createDocument,
  updateDocument,
  moveDocument,
  deleteDocument,
  listTrash,
  restoreBundle,
  purgeBundle,
};
