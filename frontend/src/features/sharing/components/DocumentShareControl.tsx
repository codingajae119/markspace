/**
 * 문서 표면 공유 컨트롤 (design.md §Frontend `DocumentShareControl` (신규),
 * Req 2.2·2.3·4.1·4.2·4.3·4.4·5.1·5.4·5.5·6.1·6.2).
 *
 * 문서 화면(편집·삭제 컨트롤 옆)에 마운트되는 자기완결 단일 토글 컨트롤이다. 현재 공유 상태에
 * 따라 하나의 버튼 라벨("공유"/"공유 해제")과 클릭 동작(발급/재활성/해제)을 전환하고, 공유
 * 중일 때만 게스트 프론트 링크 복사 버튼을 곁들인다. 공유 링크 도메인 로직(발급·토글·초기 조회·
 * INV-8·복사·폴백)은 재구현하지 않고 `useShareManager`·`CopyLinkButton` 에 전량 위임한다.
 *
 * **노출 게이트 비소유**: 이 컴포넌트는 owner/admin·공유가능·active 게이트를 스스로 판단하지
 * 않는다. 툴바(DocumentToolbar)가 마운트 여부를 결정하므로, 마운트되면 그대로 렌더한다
 * (ShareLinkPanel 의 자기완결 계약 미러 — `{ documentId, documentStatus }` prop 만으로 동작).
 *
 * - loading(초기 조회 in-flight): 버튼을 확정 라벨로 단정하지 않고 비활성으로 잠정 표기한다
 *   (Req 2.2). 조회 실패는 error 로 표면화하되 이전 로컬 상태를 침범하지 않는다(Req 2.3·6.1).
 * - shared = link !== null && link.is_enabled → 라벨 "공유 해제", 아니면 "공유"(Req 4.1·4.2).
 * - onClick 동작 매핑(Req 4.3·4.4, design "단일 버튼 동작 매핑" 플로우차트):
 *     shared → toggle(false)(공개 차단·토큰 유지)
 *     미공유·링크 없음 → issue()(새 토큰 발급·활성)
 *     미공유·비활성 링크 → toggle(true)(같은 URL 재활성)
 * - pending(조작 중) → 버튼 비활성으로 중복 실행 방지(Req 6.2). loading 과 함께 비활성 조건 결합.
 * - 공유 중일 때만 `<CopyLinkButton frontShareUrl={frontShareUrl} />` 노출(Req 5.1·5.5). 복사
 *   대상은 게스트 프론트 링크(`frontShareUrl`)뿐이며 백엔드 공개 API 경로(`share_url`)를 쓰지
 *   않는다(Req 5.4). 복사 완료 피드백·클립보드 실패 폴백은 CopyLinkButton 이 소유(재구현 금지).
 * - error → `<ErrorMessage error={error} />` 로 초기 조회·조작 실패를 단일 sink 로 표면화
 *   (Req 6.1). 실패 시 로컬 링크 상태 불침범은 훅이 이미 보장한다.
 *
 * 경계: s19 뷰어·트리를 import 하지 않는다(sharing 전용). 이 컴포넌트는 배럴(index.ts)에서
 * 공개되어 document feature 가 교차-feature import(선례)로 마운트한다.
 */

import type { ReactElement } from "react";

import { Button, ErrorMessage } from "@/shared/ui";

import { useShareManager } from "../hooks/useShareManager";
import { CopyLinkButton } from "./CopyLinkButton";

/**
 * DocumentShareControl props — ShareLinkPanel 의 자기완결 계약 미러.
 * 노출 게이트는 툴바가 소유하므로 이 컴포넌트는 대상 문서 신호만 받는다.
 */
export interface DocumentShareControlProps {
  documentId: number;
  /** s19 관찰 신호(문서 active-ness). useShareManager 로 전달된다. */
  documentStatus: string;
}

/** 상태 기반 단일 토글 + 공유 중 복사. 도메인 로직은 useShareManager·CopyLinkButton 에 위임. */
export function DocumentShareControl({
  documentId,
  documentStatus,
}: DocumentShareControlProps): ReactElement {
  const { link, frontShareUrl, loading, pending, error, issue, toggle } =
    useShareManager({ documentId, documentStatus });

  // 공유 중 = 링크가 존재하고 활성. 라벨·동작·복사 노출의 단일 파생 신호(Req 4.1·4.2).
  const shared = link !== null && link.is_enabled;
  // 조회·조작 진행 중이면 비활성(잠정 표기·중복 실행 방지, Req 2.2·6.2).
  const disabled = loading || pending;

  // 동작 매핑(Req 4.3·4.4): 공유 중 → 해제 / 링크 없음 → 발급 / 비활성 링크 → 재활성.
  function handleClick(): void {
    if (shared) {
      void toggle(false);
      return;
    }
    if (link !== null) {
      void toggle(true);
      return;
    }
    void issue();
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="secondary" onClick={handleClick} disabled={disabled}>
        {shared ? "공유 해제" : "공유"}
      </Button>

      {/* 공유 중일 때만 게스트 프론트 링크 복사 버튼을 노출한다(Req 5.1·5.5). */}
      {shared ? <CopyLinkButton frontShareUrl={frontShareUrl} /> : null}

      {/* 초기 조회·조작 실패 공통 단일 sink(Req 6.1). 로컬 상태 불침범은 훅이 보장. */}
      <ErrorMessage error={error} />
    </div>
  );
}
