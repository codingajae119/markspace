import { describe, it, expect } from "vitest";

// 실제 Toast(모킹 아님) Viewer 로 렌더한 뒤 수식 패스를 태워, 두 마크다운 엔진의
// 서로 다른 DOM 청킹(특히 여러 줄 `$$` 블록의 `<br>` 분리)까지 실제로 렌더되는지 검증한다.
// 단위테스트(renderMath.test.ts)는 이상적 HTML 을 쓰지만, 이 스위트는 Toast 가 실제로
// 만드는 DOM 형태를 회귀 방어한다(과거 여러 줄 `$$` 미렌더 버그의 원인).
// @toast-ui/editor 는 exports 맵에 types 컨디션이 없어 값 import 가 타입지정 불가(TS7016).
// EditorWrapper 와 동일 idiom 으로 값만 받고 테스트에서 최소 형태로 캐스팅한다.
// @ts-expect-error — exports 맵의 types 컨디션 부재로 값 import 는 타입지정 불가(TS7016).
import EditorRuntime from "@toast-ui/editor";

import { renderMathIn } from "@/shared/editor/renderMath";

const Editor = EditorRuntime as {
  factory(options: Record<string, unknown>): unknown;
};

/** 실제 Toast Viewer 로 markdown 을 렌더하고 컨테이너 요소를 돌려준다. */
function renderViewer(markdown: string): HTMLElement {
  const el = document.createElement("div");
  document.body.appendChild(el);
  Editor.factory({ el, viewer: true, initialValue: markdown });
  return el;
}

describe("renderMathIn — 실제 Toast Viewer 출력에 대한 수식 렌더 (회귀)", () => {
  it("인라인 $…$ 를 렌더한다", () => {
    const el = renderViewer("본문 $a+b$ 끝\n");
    renderMathIn(el);
    expect(el.querySelectorAll(".katex").length).toBeGreaterThan(0);
  });

  it("단일 라인 $$…$$ 를 display 로 렌더한다", () => {
    const el = renderViewer("$$E = mc^2$$\n");
    renderMathIn(el);
    expect(el.querySelector(".katex-display")).not.toBeNull();
  });

  it("여러 줄 블록 $$ (Toast 가 <br> 로 쪼개는 형태)를 display 로 렌더한다", () => {
    // 과거 버그: `<p>$$<br>E = mc^2<br>$$</p>` 로 분리되어 auto-render 가 매칭 실패했다.
    const el = renderViewer("문단\n\n$$\nE = mc^2\n$$\n\n끝\n");
    renderMathIn(el);
    expect(el.querySelector(".katex-display")).not.toBeNull();
    // 원문 구분자가 텍스트로 남아있지 않아야 한다(렌더로 대체됨).
    expect(el.textContent).not.toContain("$$");
  });

  it("빈 줄로 쪼개진 블록 $$ (여는 $$ 와 내용/닫는 $$ 가 다른 문단)를 렌더한다", () => {
    // Toast/백엔드 모두 `<p>$$</p><p>x+y=1$$</p>` 로 문단이 나뉜다(과거 미렌더 버그).
    const el = renderViewer("$$\n\nx+y=1$$\n");
    renderMathIn(el);
    expect(el.querySelector(".katex-display")).not.toBeNull();
    expect(el.textContent).not.toContain("$$");
  });

  it("여닫이 $$ 가 모두 빈 줄로 분리된 3문단 블록을 렌더한다", () => {
    // `<p>$$</p><p>x+y=1</p><p>$$</p>` — 형제 누적으로 하나의 display 로 합친다.
    const el = renderViewer("$$\n\nx+y=1\n\n$$\n");
    renderMathIn(el);
    expect(el.querySelector(".katex-display")).not.toBeNull();
    expect(el.textContent).not.toContain("$$");
  });

  it("```math 코드펜스를 display 로 렌더한다", () => {
    const el = renderViewer("```math\nE = mc^2\n```\n");
    renderMathIn(el);
    expect(el.querySelector(".katex-display")).not.toBeNull();
  });

  it("일반 텍스트/인라인 코드의 $ 는 수식으로 오인하지 않는다", () => {
    const el = renderViewer("가격은 `$5` 와 $10 입니다\n");
    renderMathIn(el);
    // 인라인 코드 안의 $5 는 건드리지 않는다.
    expect(el.textContent).toContain("$5");
  });
});
