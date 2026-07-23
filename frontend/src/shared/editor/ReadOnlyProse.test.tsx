import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ReadOnlyProse } from "@/shared/editor/ReadOnlyProse";

afterEach(() => {
  cleanup();
});

/** 컨테이너 요소(공용 prose 클래스를 가진 래퍼)를 찾는다. */
function getProseContainer(root: HTMLElement): HTMLElement {
  const container = root.querySelector(".readonly-prose");
  if (!(container instanceof HTMLElement)) {
    throw new Error("readonly-prose 컨테이너를 찾지 못했습니다.");
  }
  return container;
}

describe("ReadOnlyProse — 공용 읽기 전용 prose 컨테이너 (12.1, 12.2)", () => {
  it("html 을 공용 prose 컨테이너 안에 렌더한다 (인증 read 경로)", () => {
    const { container } = render(
      <ReadOnlyProse html="<h1>Title</h1><p>body</p>" />,
    );

    // sanitized html 이 실제 DOM 으로 렌더된다.
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();

    // 렌더는 공용 prose 컨테이너 안에서 일어난다.
    const prose = getProseContainer(container);
    expect(prose).toHaveClass("readonly-prose");
    expect(prose.querySelector("h1")?.textContent).toBe("Title");
  });

  it("children 을 동일한 공용 prose 컨테이너 안에 렌더한다 (게스트 content_html 대칭 경로)", () => {
    const { container } = render(
      <ReadOnlyProse>
        <span>child</span>
      </ReadOnlyProse>,
    );

    expect(screen.getByText("child")).toBeInTheDocument();

    const prose = getProseContainer(container);
    expect(prose).toHaveClass("readonly-prose");
    expect(prose.querySelector("span")?.textContent).toBe("child");
  });

  it("html 안의 LaTeX 구분자를 KaTeX 로 렌더한다 (게스트 content_html 수식 경로)", () => {
    // 백엔드(markdown-it-py + nh3)는 수식을 모르므로 `$$…$$` 가 content_html 에 텍스트로
    // 남는다 — ReadOnlyProse 가 렌더 직후 KaTeX 패스를 태워 게스트 뷰에서도 수식이 보인다.
    const { container } = render(
      <ReadOnlyProse html="<p>질량-에너지 $$E = mc^2$$</p>" />,
    );

    const prose = getProseContainer(container);
    expect(prose.querySelector(".katex")).not.toBeNull();
  });

  it("표 셀의 align 속성이 기본 좌측 정렬을 이긴다 (두 읽기 경로 공용 정렬 규칙)", () => {
    // 두 읽기 경로 모두 정렬을 표현 속성 `align` 으로 낸다(에디터=Toast Viewer, 게스트=백엔드
    // MarkdownRenderer). `align` 은 presentational hint 라 prose.css 의 기본
    // `text-align: left` 에 캐스케이드에서 밀리므로, 속성 선택자 규칙이 없으면 정렬이
    // 무시된다(회귀 가드).
    const { container } = render(
      <ReadOnlyProse
        html={
          "<table><tbody><tr>" +
          '<td align="left">L</td>' +
          '<td align="center">C</td>' +
          '<td align="right">R</td>' +
          "<td>D</td>" +
          "</tr></tbody></table>"
        }
      />,
    );

    const prose = getProseContainer(container);
    const cells = prose.querySelectorAll("td");
    expect(getComputedStyle(cells[0]).textAlign).toBe("left");
    expect(getComputedStyle(cells[1]).textAlign).toBe("center");
    expect(getComputedStyle(cells[2]).textAlign).toBe("right");
    // 정렬 지정이 없는 셀은 기본값(좌측)을 유지한다.
    expect(getComputedStyle(cells[3]).textAlign).toBe("left");
  });

  it("html 경로와 children 경로가 동일한 컨테이너 클래스를 사용한다 (동일 시각 언어 보장, 12.2)", () => {
    const htmlRender = render(<ReadOnlyProse html="<p>x</p>" />);
    const htmlClass = getProseContainer(htmlRender.container).className;
    cleanup();

    const childrenRender = render(
      <ReadOnlyProse>
        <p>x</p>
      </ReadOnlyProse>,
    );
    const childrenClass = getProseContainer(childrenRender.container).className;

    // 두 렌더 경로가 정확히 동일한 클래스명을 공유 → 단일 시각 언어.
    expect(htmlClass).toBe(childrenClass);
  });
});
