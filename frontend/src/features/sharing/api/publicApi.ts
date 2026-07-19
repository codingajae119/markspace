/**
 * 공개(무가드) 렌더·첨부 서빙 엔드포인트의 얇은 어댑터
 * (design.md "features/sharing/api → publicApi").
 *
 * s16 공용 `apiClient` 위에 공개 렌더(`GET /public/{token}`) 호출만 타입 안전하게 얹고,
 * 첨부 서빙(`GET /public/{token}/attachments/{aid}`)은 브라우저가 직접 로딩하는 절대 URL
 * 헬퍼로만 제공한다. fetch·credentials·에러 파싱(`ApiError`)·전역 401 인터셉터는 s16 단일
 * 지점(apiClient)이 소유하므로 여기서 재구현하지 않고 위임한다. base URL 은 s16 단일 설정
 * (`apiConfig.baseUrl`)만 소비하며 하드코딩하지 않는다.
 *
 * 공개 경로 규약: `getPublicDocument` 는 게스트(무인증) 경로이므로 `apiClient.get` 에
 * `skipAuthRedirect: true` 를 지정해 전역 401 리다이렉트를 유발하지 않는다(미인증 상태에서도
 * 로그인으로 튕기지 않고 404 등 오류를 그대로 표면화). 관리(인증) 경로는 `shareApi` 소관이다.
 *
 * Requirements:
 * - 6.2 공개 렌더 응답(`GET /public/{token}` → 200 `PublicDocumentRead`)
 * - 7.1 첨부 서빙 절대 URL(브라우저 직접 로딩용 `/public/{token}/attachments/{aid}`)
 * - 8.1 소비 경계(교차 관심사 재구현 금지, s16 `apiClient`·`apiConfig`·`./types` 만 소비)
 * - 8.3 공개 호출 무리다이렉트(`skipAuthRedirect` 로 전역 401 제외)
 *
 * 계약 경계: 응답 타입(`PublicDocumentRead`)은 `./types`(task 1.1, 백엔드
 * `app/sharing/schemas.py` 미러)를 import 재사용하며 로컬 재선언하지 않는다(drift 방지).
 */

import { apiConfig } from "@/config";
import { apiClient } from "@/shared/api/client";
import type { PublicDocumentRead } from "./types";

/**
 * 공유 토큰으로 공개 문서 트리를 로드한다(Req 6.2·8.3).
 *
 * 게스트(무인증) 경로이므로 `skipAuthRedirect: true` 로 호출해 미인증이어도 전역 401
 * 리다이렉트를 유발하지 않는다. 성공(200) 시 서버가 산정한 `PublicDocumentRead`(안전 HTML·
 * active 하위 트리 포함)를 그대로 반환하며, 404 등 오류는 apiClient 가 정규화한 `ApiError` 로
 * throw 되어 여기서 잡지 않고 그대로 전파한다(소비 훅이 무효 판정).
 */
function getPublicDocument(token: string): Promise<PublicDocumentRead> {
  return apiClient.get<PublicDocumentRead>(`/public/${token}`, {
    skipAuthRedirect: true,
  });
}

/**
 * 공개 첨부 서빙의 절대 URL 을 구성한다(Req 7.1).
 *
 * 첨부 바이너리는 apiClient(fetch)가 아니라 브라우저가 `<img>`/앵커로 직접 로딩하므로 상대
 * 경로가 아닌 s16 단일 설정(`apiConfig.baseUrl`) 기준 절대 URL 이 필요하다. base URL 의 후행
 * 슬래시는 제거해 `//public` 이중 슬래시가 생기지 않도록 한다.
 */
function buildAttachmentUrl(token: string, attachmentId: number): string {
  const base = apiConfig.baseUrl.replace(/\/+$/, "");
  return `${base}/public/${token}/attachments/${attachmentId}`;
}

/** 공개 렌더·첨부 서빙 훅/컴포넌트가 소비하는 얇은 공개 API. */
export const publicApi = {
  getPublicDocument,
  buildAttachmentUrl,
};
