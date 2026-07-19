/**
 * 편집 잠금/저장/취소/강제해제/버전 + 편집용 문서 상세 엔드포인트의 얇은 타입 래퍼
 * (design.md "features/editor/api → LockVersionApi").
 *
 * s16 공용 `apiClient` 위에 5개 잠금/버전 호출과 편집 초기 콘텐츠 조회(`GET /documents/{id}`)
 * 만 타입 안전하게 얹는다. fetch·base URL·credentials·에러 파싱(`ApiError`)·전역 401
 * 인터셉터는 s16 단일 지점(apiClient)이 소유하므로 여기서 재구현하지 않고 위임한다(오류는
 * catch/re-wrap 없이 그대로 전파). `apiClient` 에는 쿼리 파라미터 전용 옵션이 없으므로
 * 버전 목록의 `limit`/`offset` 은 여기서 `URLSearchParams` 로 path 쿼리에 직접 조립한다.
 *
 * Requirements:
 * - 1.1 소비 경계(교차 관심사 재구현 금지, s16 `apiClient`·`../types` 타입만 소비)
 * - 1.3 편집 초기 콘텐츠 조회(`GET /documents/{id}` → EditableDocument)
 * - 3.1 편집 잠금 획득(`POST /documents/{id}/lock` → DocumentLockRead, 200)
 * - 4.1 저장(`POST /documents/{id}/save` → DocumentVersionRead, 200)
 * - 5.2 강제 해제(`POST /documents/{id}/force-unlock` → 204)
 * - 6.1 버전 목록(`GET /documents/{id}/versions?limit=&offset=` → Page<DocumentVersionRead>)
 * - 6.2 편집 취소(`POST /documents/{id}/cancel` → 204)
 * - 7.5 204 무본문 응답은 `Promise<void>`(apiClient 가 `undefined` 반환)
 *
 * 계약 경계: 요청 본문(`DocumentSaveRequest`)·응답·엔벨로프 타입(`DocumentLockRead`·
 * `DocumentVersionRead`·`EditableDocument`·`Page`)은 `../types`(task 1.1, 백엔드 스키마
 * 미러)를 import 재사용하며 로컬 재선언하지 않는다(drift 방지).
 */

import { apiClient } from "@/shared/api/client";
import type {
  Page,
  DocumentLockRead,
  DocumentVersionRead,
  DocumentSaveRequest,
  EditableDocument,
} from "../types";

/** `limit`/`offset` 을 쿼리 문자열로 조립(`URLSearchParams` 로 인코딩 정확성 보장). */
function buildPagedPath(base: string, limit: number, offset: number): string {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return `${base}?${params.toString()}`;
}

/** 편집 잠금 획득(멱등 재획득 포함). 성공 시 `DocumentLockRead`(200). 본문 없음. */
function lockDocument(id: number): Promise<DocumentLockRead> {
  return apiClient.post<DocumentLockRead>(`/documents/${id}/lock`);
}

/**
 * 편집 초기 콘텐츠 조회. 백엔드 `DocumentRead` 를 편집에 필요한 부분집합
 * {@link EditableDocument} 으로 소비한다.
 */
function getDocument(id: number): Promise<EditableDocument> {
  return apiClient.get<EditableDocument>(`/documents/${id}`);
}

/** 잠금 보유자의 저장. 성공 시 저장 버전 메타 `DocumentVersionRead`(200) 반환. */
function saveDocument(
  id: number,
  body: DocumentSaveRequest,
): Promise<DocumentVersionRead> {
  return apiClient.post<DocumentVersionRead>(`/documents/${id}/save`, body);
}

/** 편집 취소(자기 잠금 해제, 204 → `undefined`). 본문 없음. */
function cancelEdit(id: number): Promise<void> {
  return apiClient.post<void>(`/documents/${id}/cancel`);
}

/** 강제 해제(owner/admin, 204 → `undefined`). 본문 없음. */
function forceUnlock(id: number): Promise<void> {
  return apiClient.post<void>(`/documents/${id}/force-unlock`);
}

/** 버전 이력 목록(단일 페이지). `limit`/`offset` 은 쿼리로 전달된다. */
function listVersions(
  id: number,
  limit: number,
  offset: number,
): Promise<Page<DocumentVersionRead>> {
  return apiClient.get<Page<DocumentVersionRead>>(
    buildPagedPath(`/documents/${id}/versions`, limit, offset),
  );
}

/** 편집 세션·강제해제·버전 이력 훅이 소비하는 얇은 잠금/버전 API. */
export const lockVersionApi = {
  lockDocument,
  getDocument,
  saveDocument,
  cancelEdit,
  forceUnlock,
  listVersions,
};
