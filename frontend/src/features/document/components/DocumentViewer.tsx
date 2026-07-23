/**
 * DocumentViewer — 문서 상세 읽기 뷰
 * (design.md "화면 컴포넌트 → DocumentViewer" ~597-599).
 *
 * 마운트/`documentId` 변경 시 `documentApi.getDocument(documentId)` 로 상세를 조회하고
 * (Req 7.1), 로딩 중에는 s16 `Spinner` 를 표시한다. 성공 시 본문은 s16 **단일** 래퍼
 * `EditorWrapper` 를 `mode="read"`·`initialContent={doc.content}`(markdown 본문)로 렌더한다
 * (Req 7.2, 7.3). `content_html` 은 사용하지 않으며 자체 Toast/Editor 인스턴스를 만들지
 * 않는다 — 편집·읽기 렌더 경로를 단일화한다(렌더 경로 이원화 금지).
 *
 * 편집·삭제 진입 seam(Req 5.1, 7.4, 7.5)은 이 뷰어가 아니라 상단 `DocumentToolbar` 컨트롤 행이
 * 소유한다 — 뷰어는 순수 읽기 렌더만 담당하고 조작 버튼(편집·삭제)·확인 모달은 다루지 않는다.
 *
 * 조회 실패(404/403 등)는 `documentApi`(apiClient) 가 던진 원본 `ApiError` 를
 * `<ErrorMessage error={apiError} />` 로 표시하고 본문은 렌더하지 않는다(Req 7.6).
 *
 * 동시성: `useDocumentTree` 와 동일한 mountedRef/runId(latest-wins) idiom 으로 언마운트 후
 * setState 와 `documentId` 변경 시 stale-fetch 경합을 방지한다.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.6
 */

import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import { buildAttachmentRenderers } from "@/features/attachment";
import { ApiError } from "@/shared/api/errors";
import { EditorWrapper } from "@/shared/editor/EditorWrapper";
import { ErrorMessage, Spinner } from "@/shared/ui";

import { documentApi } from "../api/documentApi";
import type { DocumentRead } from "../types";

export interface DocumentViewerProps {
  /** 표시할 문서 id. 변경 시 재조회한다. */
  documentId: number;
}

/** 알 수 없는 throw 를 안정적 ApiError 로 정규화(내부 세부정보 미노출). */
function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) {
    return err;
  }
  return new ApiError({
    status: 0,
    code: "internal",
    message: "예기치 못한 오류가 발생했습니다.",
  });
}

/** 문서 상세를 조회해 read 뷰어로 렌더한다(편집·삭제 seam 은 상단 툴바가 소유). */
export function DocumentViewer({ documentId }: DocumentViewerProps): ReactElement {
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [doc, setDoc] = useState<DocumentRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  // 읽기 렌더도 편집 preview 와 동일한 첨부 렌더러를 소비한다 — `/attachments/{id}` 이미지는
  // 인증 blob 으로, 파일 링크는 다운로드 버튼으로 렌더된다(단일 렌더 경로). 안정 참조로 memo.
  const renderers = useMemo(() => buildAttachmentRenderers(), []);

  // 언마운트 후 setState 방지 + documentId 변경 경합 시 최신 실행만 반영(latest-wins).
  const mountedRef = useRef(true);
  const runIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    setStatus("loading");
    setError(null);

    void (async () => {
      try {
        const detail = await documentApi.getDocument(documentId);
        if (mountedRef.current && runIdRef.current === runId) {
          setDoc(detail);
          setError(null);
          setStatus("ready");
        }
      } catch (err) {
        if (mountedRef.current && runIdRef.current === runId) {
          setDoc(null);
          setError(toApiError(err));
          setStatus("error");
        }
      }
    })();
  }, [documentId]);

  if (status === "loading") {
    return (
      <div className="p-4">
        <Spinner label="문서 불러오는 중" />
      </div>
    );
  }

  // 조회 실패: ErrorMessage 만 표시하고 본문은 렌더하지 않는다(Req 7.6).
  if (status === "error" || doc === null) {
    return (
      <div className="p-4">
        <ErrorMessage error={error} />
      </div>
    );
  }

  return (
    <article className="flex flex-col gap-3 p-4">
      <header className="flex items-center gap-2">
        <h1 className="text-xl font-semibold text-gray-900">{doc.title}</h1>
      </header>
      {/* 단일 EditorWrapper(read) — content(markdown)만 사용, content_html 미사용(Req 7.2, 7.3). */}
      <EditorWrapper mode="read" initialContent={doc.content} renderers={renderers} />
    </article>
  );
}
