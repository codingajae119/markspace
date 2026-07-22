/**
 * 공용 읽기 전용 prose 컨테이너 (s16 단일 소유, Requirements 12.1·12.2).
 *
 * 신뢰된(=이미 sanitize 된) `content_html` 또는 `children` 을 공용 prose 스타일
 * (`prose.css` 의 `.readonly-prose`)로 감싼다. 인증 읽기 뷰
 * (`EditorWrapper(mode:'read')`, task 6.1)와 s22 게스트 공개 `content_html` 뷰가
 * 이 동일한 컨테이너를 소비하여 동일한 시각 언어로 렌더된다(에디터 인스턴스 부재는
 * 허용된 예외이며 렌더 경로 포크가 아니다 — 공용 prose CSS 공유로 동일 렌더 보장).
 *
 * SECURITY — sanitize 경계:
 *   `html` 은 **이미 sanitize 된 신뢰 HTML** 이라고 가정한다. 이 컴포넌트는 스타일
 *   컨테이너만 제공하며 **sanitize 하지 않는다**. sanitize 책임과 `content_html`
 *   조달은 s22(게스트 뷰) 소유다. 호출자는 sanitize 되지 않은 사용자 입력을 절대
 *   `html` 로 전달해서는 안 된다(XSS). 신뢰할 수 없는 콘텐츠라면 `children` 경로로
 *   React 가 이스케이프하도록 넘길 것.
 */

import { useLayoutEffect, useRef, type ReactElement, type ReactNode } from "react";

import { renderMathIn } from "./renderMath";
import "./prose.css";

/** 공용 prose 컨테이너 클래스 — 두 렌더 경로가 동일하게 공유하는 단일 시각 언어. */
const PROSE_CLASS = "readonly-prose";

export interface ReadOnlyProseProps {
  /**
   * 렌더할 신뢰된(sanitized) HTML 문자열. 제공되면 이 값이 컨테이너 안에
   * `dangerouslySetInnerHTML` 로 렌더된다. **호출자가 반드시 sanitize** 해야 한다.
   */
  html?: string;
  /** `html` 이 없을 때 컨테이너 안에 렌더할 React 노드. */
  children?: ReactNode;
}

/**
 * `html`(신뢰된 sanitized HTML) 또는 `children` 을 공용 prose 스타일로 감싼다.
 * 두 경로 모두 동일한 `.readonly-prose` 컨테이너를 사용한다.
 */
export function ReadOnlyProse({ html, children }: ReadOnlyProseProps): ReactElement {
  const htmlRef = useRef<HTMLDivElement | null>(null);

  // html(게스트 content_html) 경로: 렌더된 DOM 에 남은 `$$…$$`·`$…$` 텍스트를 KaTeX 로
  // 렌더한다. children 경로는 EditorWrapper(read) 가 Toast 뷰어 DOM 에 직접 수식 패스를
  // 태우므로 여기서 처리하지 않는다(이중 처리·Toast 채우기 전 실행 방지).
  useLayoutEffect(() => {
    if (html !== undefined) {
      renderMathIn(htmlRef.current);
    }
  }, [html]);

  if (html !== undefined) {
    // 신뢰된 sanitized HTML — sanitize 는 호출자(s22) 책임. 여기서는 스타일 래핑 + 수식 패스만.
    return (
      <div
        ref={htmlRef}
        className={PROSE_CLASS}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  return <div className={PROSE_CLASS}>{children}</div>;
}
