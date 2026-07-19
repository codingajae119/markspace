/**
 * 공개 문서 재귀 노드 뷰 (design.md §화면 컴포넌트 `PublicDocumentNodeView`,
 * Req 6.6·7.2·7.3).
 *
 * 게스트 공개 렌더 경로의 순수 표시(presentational) 컴포넌트. 한 `PublicDocumentNode`
 * 의 `title`(제목)과 서버 산정 안전 HTML(`content_html`)을 s16 공용 `ReadOnlyProse`
 * 컨테이너로 렌더하고, `children` 을 재귀로 중첩 렌더하여 트리 계층을 시각적으로
 * 보존한다(Req 6.6).
 *
 * 렌더 경로 단일화(S2): 여기서 에디터 인스턴스를 만들지 않으며 자체 prose 스타일도
 * 정의하지 않는다. 본문 스타일은 s16 `ReadOnlyProse`(`prose.css`)를 재사용한다
 * (에디터 없는 표시는 허용된 예외이며 렌더 경로 포크가 아니다).
 *
 * SECURITY — sanitize 경계:
 *   `content_html` 은 **백엔드(nh3)가 이미 sanitize** 하고 첨부 참조를 절대 공개 경로로
 *   **재작성한 신뢰 HTML** 이다(usePublicDocument, task 4.1). 이 컴포넌트는 재-sanitize
 *   하지 않고, 새 raw HTML 을 생성하지 않으며, 참조를 재작성하지 않는다. `content_html`
 *   을 `ReadOnlyProse` 의 `html` 프롭으로 그대로 전달할 뿐이다. 이미지(Req 7.2)·파일
 *   다운로드 링크(Req 7.3)는 절대 경로가 박힌 채 렌더되어 브라우저가 공개 서빙
 *   엔드포인트에서 직접 로드한다.
 */

import type { ReactElement } from "react";

import { ReadOnlyProse } from "@/shared/editor/ReadOnlyProse";

import type { PublicDocumentNode } from "../api/types";

export interface PublicDocumentNodeViewProps {
  /** 렌더할 공개 문서 트리 노드(자신 + 재귀 하위). */
  node: PublicDocumentNode;
}

/**
 * 단일 공개 문서 노드를 렌더하고 `children` 을 재귀로 중첩 렌더한다.
 * 본문은 s16 `ReadOnlyProse` 로 렌더하며(서버 산정 안전 HTML), 하위는 좌측 들여쓰기
 * 래퍼로 시각적 중첩을 보존한다.
 */
export function PublicDocumentNodeView({
  node,
}: PublicDocumentNodeViewProps): ReactElement {
  return (
    <article className="space-y-3">
      <h2 className="text-xl font-semibold text-slate-900">{node.title}</h2>
      {/* 서버 산정 안전 HTML — 공용 prose 컨테이너로 렌더(재-sanitize/재작성 없음). */}
      <ReadOnlyProse html={node.content_html} />
      {node.children.length > 0 ? (
        <div className="space-y-6 border-l border-slate-200 pl-4 md:pl-6">
          {node.children.map((child) => (
            <PublicDocumentNodeView key={child.id} node={child} />
          ))}
        </div>
      ) : null}
    </article>
  );
}
