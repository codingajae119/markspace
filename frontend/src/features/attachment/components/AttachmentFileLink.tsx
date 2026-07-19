/**
 * 인증·WS 격리 경유 파일 첨부 다운로드 링크 컴포넌트
 * (design.md "features/attachment — AttachmentFileLink" ~502-504·519, Requirements 4.1·4.2·4.3·4.4·5.1).
 *
 * 파일 첨부를 이미지가 아닌 **다운로드 가능한 링크(버튼)** 로 표시한다(Req 4.3). `<a href="/attachments/{id}">`
 * 같은 원시 경로 링크는 인증·WS 격리를 우회하므로 만들지 않고, 활성화(클릭) 시점에 lazy 하게
 * `attachmentApi.fetchAttachmentBlob(id)` 로 인증 blob 을 취득한 뒤 오브젝트 URL + `download=original_name`
 * 앵커로 다운로드를 트리거한다(Req 4.1·4.2). 오브젝트 URL 은 트리거 직후 즉시 해제해 누수를 막는다.
 *
 * 실패는 관측한 HTTP status 만 근거로 폴백하며(첨부 보관·소멸을 프론트에서 재판정하지 않음):
 * - 404/403 → 서빙 불가로 관측되므로 안전 {@link AttachmentPlaceholder}(`unavailable`)로 폴백해
 *   깨진 링크로 남기지 않는다(Req 4.4·5.1).
 * - 그 외(5xx·네트워크·401 등) → 일시 오류로 보고 {@link ErrorMessage} 로 표시하되, 링크는 그대로
 *   유지해 재시도 여지를 남긴다(Req 4.4, 서빙 불가와 구분).
 *
 * 오브젝트 URL 다운로드는 인증 blob 을 브라우저 다운로드로 넘기는 유일한 허용 경로다.
 */

import { useCallback, useState, type ReactElement } from "react";

import { ApiError } from "@/shared/api/errors";
import { ErrorMessage } from "@/shared/ui";

import { attachmentApi } from "../api/attachmentApi";
import { AttachmentPlaceholder } from "./AttachmentPlaceholder";

export interface AttachmentFileLinkProps {
  /** 다운로드할 첨부 식별자(문서 본문 참조 `/attachments/{id}` 에서 파싱된 값). */
  attachmentId: number;
  /** 다운로드 파일명으로 보존할 첨부 원본명(`original_name`). */
  fileName: string;
}

/** 다운로드 링크의 국소 상태(관측 HTTP 결과 기반). */
type DownloadStatus = "idle" | "downloading" | "error" | "unavailable";

/**
 * 취득한 blob 을 오브젝트 URL + `download=fileName` 앵커로 다운로드 트리거한다.
 *
 * 오브젝트 URL 생성/해제는 이 함수 내부에서 완결되며, 트리거 직후 즉시 revoke 해 누수를 막는다.
 */
function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** 인증 blob 을 lazy 취득해 원본 파일명으로 내려받는 파일 첨부 다운로드 링크. */
export function AttachmentFileLink({
  attachmentId,
  fileName,
}: AttachmentFileLinkProps): ReactElement {
  const [status, setStatus] = useState<DownloadStatus>("idle");
  const [error, setError] = useState<ApiError | null>(null);

  const handleDownload = useCallback(async () => {
    setStatus("downloading");
    setError(null);
    try {
      const blob = await attachmentApi.fetchAttachmentBlob(attachmentId);
      triggerBlobDownload(blob, fileName);
      setStatus("idle");
    } catch (err: unknown) {
      // 서빙 관측 결과(404/403)만 근거로 폴백하고 보관·소멸을 재판정하지 않는다(Req 5.3).
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
        setStatus("unavailable");
        return;
      }
      // 그 외(5xx·네트워크·401 등)는 일시 오류로 표시하고 링크는 유지한다.
      const normalized =
        err instanceof ApiError
          ? err
          : new ApiError({
              status: 0,
              code: "internal",
              message: "예기치 못한 오류가 발생했습니다.",
            });
      setError(normalized);
      setStatus("error");
    }
  }, [attachmentId, fileName]);

  // 404/403 관측 → 깨진 링크 대신 안전 placeholder(Req 4.4·5.1).
  if (status === "unavailable") {
    return <AttachmentPlaceholder variant="unavailable" />;
  }

  return (
    <span className="inline-flex flex-col gap-1">
      <button
        type="button"
        onClick={() => void handleDownload()}
        disabled={status === "downloading"}
        className={
          "inline-flex items-center gap-2 rounded-md border border-slate-300 " +
          "bg-white px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 " +
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
          "disabled:cursor-not-allowed disabled:opacity-50"
        }
      >
        <span aria-hidden="true">⬇</span>
        <span>{fileName}</span>
      </button>
      {status === "error" ? <ErrorMessage error={error} /> : null}
    </span>
  );
}
