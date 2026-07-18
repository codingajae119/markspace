import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { AppLayout } from "@/app/AppLayout";

afterEach(() => {
  cleanup();
});

describe("AppLayout — 인증 영역 공통 레이아웃 프레임 (7.2)", () => {
  it("children 을 콘텐츠 영역(main) 안에 렌더한다", () => {
    render(
      <AppLayout>
        <p>feature 화면</p>
      </AppLayout>,
    );

    const main = screen.getByRole("main");
    expect(main).toBeInTheDocument();
    // 자식은 구조적 프레임의 main 영역 안에서 렌더된다.
    expect(within(main).getByText("feature 화면")).toBeInTheDocument();
  });

  it("구조적 프레임(header/banner 영역)을 제공한다", () => {
    render(
      <AppLayout>
        <span>x</span>
      </AppLayout>,
    );
    // 인증 영역 공통 프레임의 상단 영역(banner=header)이 존재한다.
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });
});
