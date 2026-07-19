/**
 * 낙관적 첨부 업로드 훅 — 자리표시자 삽입·업로드·성공 교체/실패 오류·동시 추적.
 *
 * 업로드 요청 1건마다 결정적 `uploadId` 를 생성하고 `attachmentReference.buildPlaceholderToken`
 * 으로 진행 자리표시자 토큰을 만든 뒤 `InsertContext.insertPlaceholder` 로 콘텐츠 삽입 지점에
 * 반영한다(Req 2.1). `attachmentApi.uploadAttachment` 성공(201) 시 응답을 `buildReferenceMarkdown`
 * 으로 실제 참조(이미지 참조/다운로드 링크)로 만들어 자리표시자를 치환하고(Req 1.3·2.2) 해당
 * `AttachmentRead` 를 반환한다. 실패 시 `buildErrorMarker` 로 안전한 오류 표시로 치환하고
 * (깨진 이미지/링크 방지, Req 2.3) `s16` `apiClient` 가 정규화한 `ApiError` 를 그대로 표면화하며
 * (자체 에러 형태 발명 금지, Req 2.5·6.4) `null` 을 반환한다.
 *
 * 여러 업로드는 `uploadId` 키의 `Map<string, UploadItem>` 으로 독립 추적한다(Req 2.4). 모든 맵
 * 갱신은 함수형(prev→next 복제)으로 수행하여 동시 진행 업로드가 서로의 항목을 덮어쓰지 않는다.
 * 종류 확정·크기 한도·WS 격리 저장 등 저장 판정은 백엔드에 위임하며 프론트에서 재판정하지
 * 않는다(Req 1.5). 이 훅은 에디터 인스턴스를 소유하지 않고 `InsertContext`(task 3.3 브리지가
 * s16 `EditorHandle` 위에 구현) 콜백만 호출한다.
 * (design.md "useAttachmentUpload"; Requirements 1.1·1.3·1.5·2.1·2.2·2.3·2.4·2.5·6.4)
 */
import { useCallback, useRef, useState } from "react";

import { attachmentApi } from "../api/attachmentApi";
import {
  buildErrorMarker,
  buildPlaceholderToken,
  buildReferenceMarkdown,
} from "../lib/attachmentReference";
import type { AttachmentKind, AttachmentRead, UploadItem } from "../types";
import { ApiError } from "@/shared/api/errors";

/**
 * 콘텐츠 자리표시자 삽입·치환 콜백 계약.
 *
 * task 3.3 `useEditorUploadBridge` 가 s16 `EditorHandle.insert(text)`/`replaceRange(from,to,text)`
 * 위에 구현하며, 이 훅은 **호출만** 한다(에디터 결선 미소유). `uploadId` 로 삽입 range 를 추적해
 * 동시 업로드를 구분한다.
 */
export interface InsertContext {
  /** `uploadId` 자리표시자 토큰을 삽입하고 그 range 를 추적한다(→ `EditorHandle.insert(token)`). */
  insertPlaceholder(uploadId: string, token: string): void;
  /** 추적된 `uploadId` range 를 `replacement` 로 치환한다(→ `EditorHandle.replaceRange(range, replacement)`). */
  replaceToken(uploadId: string, replacement: string): void;
}

/** `useAttachmentUpload` 반환 계약. */
interface UseAttachmentUploadResult {
  /**
   * 업로드 1건을 시작한다. 성공 시 `AttachmentRead` 를, 실패 시 `null` 을 반환한다.
   * (자리표시자 삽입→치환·상태 전이는 반환 전에 반영된다.)
   */
  startUpload(input: {
    file: File | Blob;
    fileName: string;
    kind?: AttachmentKind;
  }): Promise<AttachmentRead | null>;
  /** uploadId 키의 독립 업로드 추적 맵(진행/성공/실패). */
  uploads: Map<string, UploadItem>;
}

/**
 * 임의 throw 값을 `ApiError` 로 정규화한다(방어적, Req 6.4).
 *
 * `apiClient` 는 항상 `ApiError` 를 throw 하므로 정상 경로에선 그대로 통과시키고, 예외적
 * 비-`ApiError` throw(런타임 이상)만 내부 세부 노출 없는 안정적 `internal` 오류로 감싼다.
 */
function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  return new ApiError({
    status: 0,
    code: "internal",
    message: "예기치 못한 오류가 발생했습니다.",
  });
}

/**
 * 낙관적 첨부 업로드 훅.
 *
 * @param documentId 업로드 대상 문서 식별자(s19 문서 컨텍스트·s20 편집 표면에서 소비, Req 1.2).
 * @param insert 자리표시자 삽입·치환 콜백(task 3.3 브리지 제공).
 */
export function useAttachmentUpload(
  documentId: number,
  insert: InsertContext,
): UseAttachmentUploadResult {
  const [uploads, setUploads] = useState<Map<string, UploadItem>>(
    () => new Map(),
  );
  // uploadId 결정적 생성용 per-hook 증가 카운터(동시 업로드 고유성 보장).
  const counterRef = useRef(0);
  // 최신 documentId/insert 를 ref 로 잡아 startUpload 참조 안정성을 유지한다.
  const documentIdRef = useRef(documentId);
  documentIdRef.current = documentId;
  const insertRef = useRef(insert);
  insertRef.current = insert;

  /** uploadId 키 항목만 함수형으로 갱신(동시 업로드 비침범, Req 2.4). */
  const patchEntry = useCallback((entry: UploadItem): void => {
    setUploads((prev) => {
      const next = new Map(prev);
      next.set(entry.uploadId, entry);
      return next;
    });
  }, []);

  const startUpload = useCallback(
    async (input: {
      file: File | Blob;
      fileName: string;
      kind?: AttachmentKind;
    }): Promise<AttachmentRead | null> => {
      const { file, fileName, kind } = input;
      const uploadId = `upload-${++counterRef.current}`;
      const activeInsert = insertRef.current;

      // 1) 진행 자리표시자 삽입 + 추적 항목 등록(Req 2.1).
      const token = buildPlaceholderToken(uploadId);
      activeInsert.insertPlaceholder(uploadId, token);
      patchEntry({
        uploadId,
        status: "uploading",
        fileName,
        attachment: null,
        error: null,
      });

      // 2) 업로드(종류 확정·크기·저장 판정은 백엔드 위임, Req 1.5).
      try {
        const att = await attachmentApi.uploadAttachment(
          documentIdRef.current,
          file,
          fileName,
          kind,
        );
        // 성공: 자리표시자를 실제 참조로 치환하고 done 으로 전이(Req 2.2).
        activeInsert.replaceToken(uploadId, buildReferenceMarkdown(att));
        patchEntry({
          uploadId,
          status: "done",
          fileName,
          attachment: att,
          error: null,
        });
        return att;
      } catch (caught) {
        // 실패: 안전한 오류 표시로 치환하고 ApiError 를 그대로 표면화(Req 2.3·2.5·6.4).
        const apiError = toApiError(caught);
        activeInsert.replaceToken(uploadId, buildErrorMarker(uploadId));
        patchEntry({
          uploadId,
          status: "error",
          fileName,
          attachment: null,
          error: apiError,
        });
        return null;
      }
    },
    [patchEntry],
  );

  return { startUpload, uploads };
}
