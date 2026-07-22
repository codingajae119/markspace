/**
 * DocumentViewer — 문서 상세 읽기 뷰 + 편집 진입 seam
 * (design.md "화면 컴포넌트 → DocumentViewer" ~597-599).
 *
 * 마운트/`documentId` 변경 시 `documentApi.getDocument(documentId)` 로 상세를 조회하고
 * (Req 7.1), 로딩 중에는 s16 `Spinner` 를 표시한다. 성공 시 본문은 s16 **단일** 래퍼
 * `EditorWrapper` 를 `mode="read"`·`initialContent={doc.content}`(markdown 본문)로 렌더한다
 * (Req 7.2, 7.3). `content_html` 은 사용하지 않으며 자체 Toast/Editor 인스턴스를 만들지
 * 않는다 — 편집·읽기 렌더 경로를 단일화한다(렌더 경로 이원화 금지).
 *
 * 편집 진입 seam(Req 7.4, 7.5): `canEdit`(editor+) 일 때만 "편집" 버튼을 노출하고 클릭 시
 * `onEnterEdit?.(documentId)` 를 호출한다. 실제 편집 모드 동작(lock/자동저장/버전)은 s20 이
 * 소유하며 본 컴포넌트는 진입점(seam)만 노출한다. `canEdit=false`(뷰어)는 읽기 전용으로
 * 편집 버튼을 렌더하지 않는다.
 *
 * 삭제 seam(Req 5.1): 편집 버튼과 동일하게 `canEdit` 게이트로 "삭제" 버튼을 편집 버튼 옆에
 * 노출한다. 클릭 시 로컬 `ConfirmDialog`(irreversible=false, 휴지통행이라 복구 가능)로 확인받고,
 * 확인되면 `onDelete?.(documentId)` seam 을 호출한다. 확인 UX(제목이 담긴 안내 문구)는 상세를
 * 이미 로드해 `doc.title` 을 가진 이 컴포넌트가 소유하고, 실제 삭제 변이(휴지통 이동·트리 반영·
 * 오류 표면화)는 상위 페이지의 `useDocumentMutations` 가 소유한다 — 편집 seam 과 동일한 분리다.
 *
 * 조회 실패(404/403 등)는 `documentApi`(apiClient) 가 던진 원본 `ApiError` 를
 * `<ErrorMessage error={apiError} />` 로 표시하고 본문은 렌더하지 않는다(Req 7.6).
 *
 * 동시성: `useDocumentTree` 와 동일한 mountedRef/runId(latest-wins) idiom 으로 언마운트 후
 * setState 와 `documentId` 변경 시 stale-fetch 경합을 방지한다.
 *
 * Requirements: 5.1, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
 */

import { useEffect, useRef, useState, type ReactElement } from "react";

import { ApiError } from "@/shared/api/errors";
import { EditorWrapper } from "@/shared/editor/EditorWrapper";
import { Button, ErrorMessage, Spinner } from "@/shared/ui";

import { documentApi } from "../api/documentApi";
import type { DocumentRead } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";

export interface DocumentViewerProps {
  /** 표시할 문서 id. 변경 시 재조회한다. */
  documentId: number;
  /** editor+ 여부(상위 페이지의 role 게이트). 편집 진입·삭제 seam 노출 여부를 결정한다. */
  canEdit: boolean;
  /** s20 편집 진입 seam — 편집 버튼 클릭 시 호출(동작은 s20 소유). */
  onEnterEdit?: (documentId: number) => void;
  /** 삭제 seam — 삭제 확인 후 호출(실제 휴지통 이동 변이는 상위 페이지 소유, Req 5.1). */
  onDelete?: (documentId: number) => void;
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

/** 문서 상세를 조회해 read 뷰어로 렌더하고, editor+ 에게 편집 진입 seam 을 노출한다. */
export function DocumentViewer({
  documentId,
  canEdit,
  onEnterEdit,
  onDelete,
}: DocumentViewerProps): ReactElement {
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [doc, setDoc] = useState<DocumentRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  // 삭제 확인 모달 개폐(로컬 UI 상태). 문서 전환/재조회 시 열려 있던 모달을 닫아 stale 확인을 막는다.
  const [confirmOpen, setConfirmOpen] = useState(false);

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
    // 다른 문서로 전환되면 이전 문서의 열린 삭제 확인 모달을 닫는다(stale 확인 방지).
    setConfirmOpen(false);

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

  // 조회 실패: ErrorMessage 만 표시하고 본문/편집 seam 은 렌더하지 않는다(Req 7.6).
  if (status === "error" || doc === null) {
    return (
      <div className="p-4">
        <ErrorMessage error={error} />
      </div>
    );
  }

  return (
    <article className="flex flex-col gap-3 p-4">
      <header className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-gray-900">{doc.title}</h1>
        {/* 편집·삭제 진입 seam: 동일한 canEdit 게이트로 편집 버튼 옆에 삭제 버튼을 함께 노출한다. */}
        {canEdit ? (
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="primary" onClick={() => onEnterEdit?.(documentId)}>
              편집
            </Button>
            <Button
              variant="secondary"
              onClick={() => setConfirmOpen(true)}
              className="border-red-300 text-red-700 hover:bg-red-50 focus-visible:ring-red-400"
            >
              삭제
            </Button>
          </div>
        ) : null}
      </header>
      {/* 단일 EditorWrapper(read) — content(markdown)만 사용, content_html 미사용(Req 7.2, 7.3). */}
      <EditorWrapper mode="read" initialContent={doc.content} />

      {/* 삭제 확인 모달(휴지통행이라 복구 가능 → irreversible=false). 확인 시 삭제 seam 호출. */}
      <ConfirmDialog
        open={confirmOpen}
        irreversible={false}
        title="문서 삭제"
        message={`"${doc.title}" 문서와 하위 문서 묶음이 함께 휴지통으로 이동합니다. 휴지통에서 복구할 수 있습니다.`}
        confirmLabel="휴지통으로 이동"
        cancelLabel="취소"
        onConfirm={() => {
          onDelete?.(documentId);
          setConfirmOpen(false);
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </article>
  );
}
