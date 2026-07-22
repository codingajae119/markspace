import { describe, it, expect } from "vitest";

import { renderMathIn } from "@/shared/editor/renderMath";

/**
 * KaTeX 공용 수식 렌더 패스 단위 테스트.
 *
 * 두 읽기 경로(Toast 뷰어 · 게스트 content_html)가 렌더한 DOM 에 남는 LaTeX 구분자를
 * 제자리에서 KaTeX 로 치환하는지, 오탐/실패 상황에서 본문을 깨지 않는지 검증한다.
 */
describe("renderMathIn — KaTeX 수식 렌더 패스", () => {
  it("인라인 $…$ 를 KaTeX 로 렌더한다", () => {
    const el = document.createElement("div");
    el.innerHTML = "<p>공식 $E = mc^2$ 끝</p>";

    renderMathIn(el);

    expect(el.querySelector(".katex")).not.toBeNull();
    // 인라인은 display 컨테이너가 아니다.
    expect(el.querySelector(".katex-display")).toBeNull();
  });

  it("블록 $$…$$ 를 display 모드로 렌더한다", () => {
    const el = document.createElement("div");
    el.innerHTML = "<p>$$\\int_0^1 x\\,dx$$</p>";

    renderMathIn(el);

    expect(el.querySelector(".katex-display")).not.toBeNull();
  });

  it("게스트 content_html 형태의 여러 줄 블록 $$(개행 포함)를 display 로 렌더한다", () => {
    // 백엔드(markdown-it-py)는 여러 줄 블록을 `<p>$$\nE = mc^2\n$$</p>` 로 만든다.
    const el = document.createElement("div");
    el.innerHTML = "<p>$$\nE = mc^2\n$$</p>";

    renderMathIn(el);

    expect(el.querySelector(".katex-display")).not.toBeNull();
    expect(el.textContent).not.toContain("$$");
  });

  it("code/pre 안의 $ 는 수식으로 오인하지 않는다(오탐 방지)", () => {
    const el = document.createElement("div");
    el.innerHTML = "<pre><code>비용 $5 와 $10</code></pre>";

    renderMathIn(el);

    expect(el.querySelector(".katex")).toBeNull();
    expect(el.textContent).toContain("$5 와 $10");
  });

  it("잘못된 수식이 있어도 throw 하지 않는다(원문 보존)", () => {
    const el = document.createElement("div");
    el.innerHTML = "<p>$\\frac{1}{$</p>";

    expect(() => renderMathIn(el)).not.toThrow();
  });

  it("null/undefined 엘리먼트는 무해하게 무시한다", () => {
    expect(() => renderMathIn(null)).not.toThrow();
    expect(() => renderMathIn(undefined)).not.toThrow();
  });
});
