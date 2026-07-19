import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import type { PublicDocumentNode } from "../api/types";
import { PublicDocumentNodeView } from "./PublicDocumentNodeView";

afterEach(() => {
  cleanup();
});

/** 테스트 픽스처 생성 헬퍼 — content_html 은 이미 절대 경로로 재작성된 안전 HTML 가정. */
function makeNode(overrides: Partial<PublicDocumentNode> = {}): PublicDocumentNode {
  return {
    id: 1,
    title: "루트 문서",
    content_html: "<p>hello</p>",
    children: [],
    ...overrides,
  };
}

describe("PublicDocumentNodeView — 공개 문서 재귀 노드 (Req 6.6, 7.2, 7.3)", () => {
  it("노드의 title 을 표시한다 (Req 6.6)", () => {
    render(<PublicDocumentNodeView node={makeNode({ title: "제목입니다" })} />);
    expect(screen.getByText("제목입니다")).toBeInTheDocument();
  });

  it("content_html 을 DOM 으로 렌더한다 (ReadOnlyProse dangerouslySetInnerHTML)", () => {
    render(
      <PublicDocumentNodeView
        node={makeNode({ content_html: "<p>hello <strong>world</strong></p>" })}
      />,
    );
    // dangerouslySetInnerHTML 로 렌더된 실제 요소가 존재해야 한다.
    expect(screen.getByText("world").tagName).toBe("STRONG");
  });

  it("자식·손자를 재귀로 중첩 렌더한다 (Req 6.6 — 중첩 트리)", () => {
    const node = makeNode({
      title: "루트",
      content_html: "<p>루트본문</p>",
      children: [
        makeNode({
          id: 2,
          title: "자식",
          content_html: "<p>자식본문</p>",
          children: [
            makeNode({
              id: 3,
              title: "손자",
              content_html: "<p>손자본문</p>",
              children: [],
            }),
          ],
        }),
      ],
    });
    render(<PublicDocumentNodeView node={node} />);

    // 모든 계층의 제목·본문이 렌더된다.
    expect(screen.getByText("루트")).toBeInTheDocument();
    expect(screen.getByText("자식")).toBeInTheDocument();
    expect(screen.getByText("손자")).toBeInTheDocument();
    expect(screen.getByText("루트본문")).toBeInTheDocument();
    expect(screen.getByText("자식본문")).toBeInTheDocument();
    expect(screen.getByText("손자본문")).toBeInTheDocument();
  });

  it("자식이 시각적 중첩(래퍼) 안에 렌더된다 (Req 6.6)", () => {
    const node = makeNode({
      title: "루트",
      children: [makeNode({ id: 2, title: "중첩자식", children: [] })],
    });
    const { container } = render(<PublicDocumentNodeView node={node} />);

    // 자식 제목은 루트 노드의 최상위가 아니라 하위 중첩 컨테이너 안에 위치한다.
    const rootArticle = container.firstElementChild as HTMLElement;
    expect(rootArticle).not.toBeNull();
    // 루트 article 내부의 어딘가에 자식 제목이 포함된다(재귀 중첩).
    expect(within(rootArticle).getByText("중첩자식")).toBeInTheDocument();
    // 자식은 루트 article 의 직접 자식이 아닌 더 깊은 곳에 있다.
    expect(rootArticle.querySelectorAll("article").length).toBeGreaterThanOrEqual(1);
  });

  it("content_html 안의 이미지가 절대 공개 경로 src 로 그대로 렌더된다 (Req 7.2)", () => {
    const node = makeNode({
      content_html:
        '<p><img src="http://localhost:8000/public/tok/attachments/5" alt="첨부이미지" /></p>',
    });
    const { container } = render(<PublicDocumentNodeView node={node} />);

    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    const src = img!.getAttribute("src") ?? "";
    // 이미 절대화된 참조가 재작성 없이 그대로 렌더된다.
    expect(src.startsWith("http")).toBe(true);
    expect(src).toBe("http://localhost:8000/public/tok/attachments/5");
  });

  it("content_html 안의 다운로드 링크가 절대 공개 경로 href 로 그대로 렌더된다 (Req 7.3)", () => {
    const node = makeNode({
      content_html:
        '<p><a href="http://localhost:8000/public/tok/attachments/7">file.pdf</a></p>',
    });
    const { container } = render(<PublicDocumentNodeView node={node} />);

    const link = screen.getByText("file.pdf") as HTMLAnchorElement;
    expect(link.tagName).toBe("A");
    const href = link.getAttribute("href") ?? "";
    expect(href.startsWith("http")).toBe(true);
    expect(href).toBe("http://localhost:8000/public/tok/attachments/7");
    // 컨테이너 스코프로도 동일 앵커 확인.
    expect(container.querySelector('a[href^="http"]')).not.toBeNull();
  });
});
