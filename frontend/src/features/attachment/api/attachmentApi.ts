/**
 * 첨부 업로드(multipart)·서빙(blob) 엔드포인트의 얇은 타입 래퍼
 * (design.md "features/attachment/api → AttachmentApi").
 *
 * s16 공용 `apiClient` 위에 첨부 업로드(`POST /documents/{documentId}/attachments`)와
 * 서빙(`GET /attachments/{id}`) 호출만 타입 안전하게 얹는다. fetch·base URL·credentials·
 * 에러 파싱(`ApiError`)·전역 401 인터셉터는 s16 단일 지점(apiClient)이 소유하므로 여기서
 * 재구현하지 않고 위임한다. 업로드는 `FormData`(multipart) 조립만, 서빙은 `responseType:"blob"`
 * 지정만 담당한다.
 *
 * Requirements:
 * - 1.1 소비 경계(교차 관심사 재구현 금지, s16 `apiClient`·`../types` 타입만 소비)
 * - 3.1 첨부 서빙(`GET /attachments/{id}` → `Blob`, blob 응답 타입)
 * - 4.1 첨부 업로드(`POST /documents/{documentId}/attachments` multipart → 201 `AttachmentRead`)
 * - 6.1 오류는 `apiClient` 정규화 `ApiError` 로 그대로 전파(catch/재파싱 금지)
 * - 6.2 서빙 404/403 등 오류도 `ApiError` 로 throw(소비 훅이 상태 판정)
 *
 * 계약 경계: 응답 타입(`AttachmentRead`)과 종류 유니온(`AttachmentKind`)은 `../types`
 * (task 1.1, 백엔드 스키마 미러)를 import 재사용하며 로컬 재선언하지 않는다(drift 방지).
 */

import { apiClient } from "@/shared/api/client";
import type { AttachmentKind, AttachmentRead } from "../types";

/**
 * 대상 문서에 첨부를 업로드한다(Req 4.1).
 *
 * `file`(바이너리)과 선택 `kind` 를 `FormData` 로 조립해 multipart 로 전송한다. Content-Type
 * multipart 경계는 브라우저가 설정하므로(apiClient 가 FormData 를 그대로 통과) 여기서 헤더를
 * 지정하지 않는다. `kind` 미지정 시 필드를 붙이지 않아 백엔드가 content-type 으로 추론한다.
 * 성공(201) 시 서버가 준 `AttachmentRead`(url 포함) 를 그대로 반환한다.
 */
function uploadAttachment(
  documentId: number,
  file: File | Blob,
  fileName: string,
  kind?: AttachmentKind,
): Promise<AttachmentRead> {
  const form = new FormData();
  form.append("file", file, fileName);
  if (kind !== undefined) {
    form.append("kind", kind);
  }
  return apiClient.post<AttachmentRead>(
    `/documents/${documentId}/attachments`,
    form,
  );
}

/**
 * 첨부 바이너리를 인증 서빙으로 받아온다(Req 3.1·6.2).
 *
 * `responseType:"blob"` 로 호출해 `Blob` 을 수신한다. 404/403 등 오류는 apiClient 가 정규화한
 * `ApiError` 로 throw 되며 여기서 잡지 않고 그대로 전파한다(소비 훅이 상태를 판정).
 */
function fetchAttachmentBlob(attachmentId: number): Promise<Blob> {
  return apiClient.get<Blob>(`/attachments/${attachmentId}`, {
    responseType: "blob",
  });
}

/** 첨부 업로드·서빙 훅이 소비하는 얇은 첨부 API. */
export const attachmentApi = {
  uploadAttachment,
  fetchAttachmentBlob,
};
