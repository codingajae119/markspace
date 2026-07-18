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
