/**
 * 게스트 공개 문서 뷰 컨테이너 (design.md §화면 컴포넌트 `PublicDocumentView`,
 * Req 6.1·6.4·6.5·6.6).
 *
 * 공유 토큰(`token`)으로 `usePublicDocument` 를 구독하고, 그 판별 유니온 상태를
 * 표면 프리미티브로 매핑하는 순수 뷰어다:
 *   - `loading`     → s16 `Spinner`.
 *   - `unavailable` → s16 `EmptyState`("링크 사용 불가"). 사유(무효 토큰·삭제·보관·게이트
 *                     off)를 구분하지 않는 단일 표면으로 존재 추정을 차단한다(Req 6.5).
 *   - `error`       → s16 `ErrorMessage`(정규화된 `ApiError` 표면화, Req 6.1).
 *   - `ready`       → `PublicDocumentNodeView` 로 `root` 트리를 재귀 렌더(Req 6.6).
 *
 * 읽기 전용(Req 6.4): 편집·이동·삭제·발급·저장 등 어떤 상태 변경 어포던스(버튼·입력)도
 * 노출하지 않는다. 본문 스타일은 `PublicDocumentNodeView` 가 소비하는 s16 `ReadOnlyProse`
 * 를 그대로 따르며(Req 6.6 시각 일관성) 여기서 자체 prose 스타일을 정의하지 않는다.
 */

import type { ReactElement } from "react";

import { EmptyState } from "@/shared/ui/EmptyState";
import { ErrorMessage } from "@/shared/ui/ErrorMessage";
import { Spinner } from "@/shared/ui/Spinner";

import { usePublicDocument } from "../hooks/usePublicDocument";
import { PublicDocumentNodeView } from "./PublicDocumentNodeView";

export interface PublicDocumentViewProps {
  /** 게스트가 연 공유 링크의 토큰(`/share/:token`). */
  token: string;
}

/** 공유 토큰의 공개 문서를 상태별 표면으로 렌더하는 게스트 컨테이너. */
export function PublicDocumentView({ token }: PublicDocumentViewProps): ReactElement {
  const state = usePublicDocument(token);

  switch (state.status) {
    case "loading":
      return (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      );
    case "unavailable":
      // 사유 미구분 — 존재 추정 차단(Req 6.5).
      return (
        <EmptyState
          title="링크 사용 불가"
          message="이 공유 링크는 사용할 수 없습니다."
        />
      );
    case "error":
      return (
        <div className="mx-auto max-w-3xl px-4 py-8">
          <ErrorMessage error={state.error} />
        </div>
      );
    case "ready":
      // 읽기 전용 트리 렌더(Req 6.6) — 변경 컨트롤 없음(Req 6.4).
      return (
        <div className="mx-auto max-w-3xl px-4 py-8">
          <PublicDocumentNodeView node={state.root} />
        </div>
      );
  }
}
