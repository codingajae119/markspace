/**
 * 공유 링크 관리(발급·토글) 엔드포인트의 얇은 타입 래퍼
 * (design.md "features/sharing/api → shareApi").
 *
 * s16 공용 `apiClient` 위에 공유 링크 발급(`POST /documents/{documentId}/share`)과
 * 토글(`PATCH /documents/{documentId}/share`) 호출만 타입 안전하게 얹는다. fetch·base URL·
 * credentials·에러 파싱(`ApiError`)·전역 401 인터셉터는 s16 단일 지점(apiClient)이 소유하므로
 * 여기서 재구현하지 않고 위임한다. 어댑터는 비즈니스 로직 없이 경로·메서드·타입만 결선한다.
 *
 * Requirements:
 * - 2.1 공유 링크 발급(`POST /documents/{documentId}/share` → 200 `ShareLinkRead`)
 * - 3.1 공유 링크 토글(`PATCH /documents/{documentId}/share`, body=`ShareLinkUpdate` → 200 `ShareLinkRead`)
 * - 8.1 소비 경계(교차 관심사 재구현 금지, s16 `apiClient`·`../types` 타입만 소비, 오류는 `ApiError` 전파)
 *
 * 계약 경계: 응답 타입(`ShareLinkRead`)과 요청 본문 타입(`ShareLinkUpdate`)은 `./types`
 * (task 1.1, 백엔드 `app/sharing/schemas.py` 미러)를 import 재사용하며 로컬 재선언하지 않는다(drift 방지).
 */

import { apiClient } from "@/shared/api/client";
import type { ShareLinkRead, ShareLinkUpdate } from "./types";

/**
 * 대상 문서의 공유 링크를 발급(재발급)한다(Req 2.1).
 *
 * 요청 본문 없이 `POST` 하며(재발급은 상태 무관·INV-8), 성공(200) 시 서버가 준
 * `ShareLinkRead`(token·share_url 포함) 를 그대로 반환한다. 오류(401/403/404/409)는
 * apiClient 가 정규화한 `ApiError` 로 throw 되며 여기서 잡지 않고 그대로 전파한다.
 */
function issueLink(documentId: number): Promise<ShareLinkRead> {
  return apiClient.post<ShareLinkRead>(`/documents/${documentId}/share`);
}

/**
 * 대상 문서의 공유 링크 활성 상태를 토글한다(Req 3.1).
 *
 * `ShareLinkUpdate`(`{ is_enabled }`) 본문을 `PATCH` 로 전송한다. 토큰은 유지되고 상태만
 * 전환된다(서비스 소관). 성공(200) 시 갱신된 `ShareLinkRead` 를 반환하며, 오류는 apiClient
 * 정규화 `ApiError` 로 그대로 전파한다.
 */
function toggleLink(
  documentId: number,
  body: ShareLinkUpdate,
): Promise<ShareLinkRead> {
  return apiClient.patch<ShareLinkRead>(`/documents/${documentId}/share`, body);
}

/**
 * 대상 문서의 현재 공유 링크 상태를 조회한다(읽기 전용, Req 2.1).
 *
 * `GET` 으로 조회하며 상태를 발급·전환·무효화하지 않는다(읽기 전용). 링크가 없는 문서는
 * 서버가 `200 + null` 로 응답하고, apiClient 의 본문 파서가 `JSON.parse("null")=null` 로
 * 환원하므로 별도 "링크 없음" 분기 없이 `null` 을 그대로 반환한다. 오류(401/403/404)는
 * apiClient 정규화 `ApiError` 로 throw 되며 여기서 잡지 않고 그대로 전파한다(Req 6.3 위임).
 */
function getLink(documentId: number): Promise<ShareLinkRead | null> {
  return apiClient.get<ShareLinkRead | null>(`/documents/${documentId}/share`);
}

/** 공유 링크 관리(조회·발급·토글) 훅이 소비하는 얇은 공유 API. */
export const shareApi = {
  issueLink,
  toggleLink,
  getLink,
};
