/**
 * 편집 표면 컴포넌트 (design.md "features/editor — 화면 컴포넌트 → EditorPane").
 *
 * s16 단일 `EditorWrapper(mode:"edit", initialContent=document.content)`를 렌더하고
 * `onReady` 로 받은 `EditorHandle` 을 `useEditSession.bindHandle` 에 결선한다(저장 시
 * `getMarkdown` 소스). 자체 Toast 에디터 인스턴스를 만들지 않으며(이원화 금지, Req 7.5),
 * 편집 표면의 s21 seam(`onImagePaste`/`onFileDrop` 슬롯 + `EditorHandle.insert`/
 * `replaceRange`)은 s16 래퍼 계약을 **그대로 통과 노출**한다 — s20 은 자체 표면 API 를
 * 발명하지 않고 업로드 동작도 구현하지 않는다(Req 7.7).
 *
 * 저장은 세션 이탈 시 1회 자동저장(`useEditSession` cleanup)이 소유하므로 명시적 저장
 * 버튼을 두지 않는다(Req 3.1). 취소 컨트롤만 노출하여 저장 없이 잠금을 해제한다(Req 4.1).
 *
 * `session.document` 가 null(획득 중·차단·오류·로딩)이면 EditorWrapper 를 마운트하지 않는다
 * (콘텐츠 없이 편집 인스턴스 생성 금지 — Req 7.5). blocked/error/loading 상태 표면화는
 * 상위 페이지/배너가 소유한다.
 *
 * 초기 콘텐츠는 `content`(markdown)만 사용하며 `content_html` 을 쓰지 않는다(읽기 뷰와
 * 렌더 경로 단일화, Req 1.3).
 *
 * Requirements: 1.2, 1.3, 3.1, 4.1, 7.5, 7.7.
 */
import type { ReactElement } from "react";

import { Button } from "@/shared/ui";
import { EditorWrapper } from "@/shared/editor/EditorWrapper";
import type { UseEditSession } from "../hooks/useEditSession";

export interface EditorPaneProps {
  /** 편집 세션(잠금·초기 콘텐츠·핸들 결선·취소). design 계약. */
  session: UseEditSession;
  /**
   * 붙여넣기 이미지 구독 슬롯 — EditorWrapper 로 그대로 통과 노출한다(s21 소비, s20 미구현).
   */
  onImagePaste?: (file: File) => void;
  /**
   * 드롭 파일 구독 슬롯 — EditorWrapper 로 그대로 통과 노출한다(s21 소비, s20 미구현).
   */
  onFileDrop?: (file: File) => void;
}

/**
 * 편집 표면 pane. 잠금 보유(self)로 초기 콘텐츠가 확보된 경우에만 s16 EditorWrapper 를
 * 단일 마운트하고, 취소 컨트롤과 s21 seam 슬롯을 노출한다.
 */
export function EditorPane({
  session,
  onImagePaste,
  onFileDrop,
}: EditorPaneProps): ReactElement | null {
  const { document } = session;

  // 콘텐츠 없이 편집 인스턴스를 마운트하지 않는다(Req 7.5). 상위가 상태를 표면화한다.
  if (document === null) {
    return null;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        {/* 명시적 저장 버튼 없음 — 저장은 세션 이탈 시 1회 자동저장(Req 3.1). */}
        <Button
          variant="secondary"
          onClick={() => {
            void session.cancel();
          }}
        >
          취소
        </Button>
      </div>
      <EditorWrapper
        mode="edit"
        initialContent={document.content}
        onReady={session.bindHandle}
        onImagePaste={onImagePaste}
        onFileDrop={onFileDrop}
      />
    </div>
  );
}
