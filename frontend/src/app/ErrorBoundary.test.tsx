import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";

import { ErrorBoundary } from "@/app/ErrorBoundary";

/** 렌더 중 예외를 던지는 자식 — 에러 경계 포착 경로를 강제한다. */
function Boom(): ReactElement {
  throw new Error("boom-during-render");
}

afterEach(() => {
  cleanup();
});

describe("ErrorBoundary — 전역 렌더 에러 경계 (7.3)", () => {
  beforeEach(() => {
    // React 는 포착된 에러도 console.error 로 로깅한다(예상된 노이즈). 테스트 출력을 조용히 유지.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("자식 렌더 예외를 포착하고 앱 크래시 대신 복구 화면을 표시한다", () => {
    // 예외가 경계 밖으로 전파되면 이 render 호출 자체가 throw 하여 테스트가 깨진다.
    expect(() =>
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      ),
    ).not.toThrow();

    // 복구 화면(사용자 대면 fallback)이 보인다.
    expect(screen.getByRole("alert")).toBeInTheDocument();
    // 복구 어포던스(다시 시도 버튼)가 존재한다.
    expect(screen.getByRole("button", { name: /다시 시도/ })).toBeInTheDocument();
  });

  it("componentDidCatch 에서 콘솔로 로깅한다(개발 관측)", () => {
    const errorSpy = console.error as unknown as ReturnType<typeof vi.fn>;
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(errorSpy).toHaveBeenCalled();
  });

  it("예외가 없으면 자식을 그대로 통과시킨다(fallback 미표시)", () => {
    render(
      <ErrorBoundary>
        <p>정상 콘텐츠</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("정상 콘텐츠")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("다시 시도 버튼 클릭 시 경계 상태를 리셋해 재렌더를 시도한다", async () => {
    let shouldThrow = true;
    function Flaky(): ReactElement {
      if (shouldThrow) {
        throw new Error("flaky");
      }
      return <p>회복된 콘텐츠</p>;
    }

    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );

    // 처음엔 fallback.
    expect(screen.getByRole("alert")).toBeInTheDocument();

    // 다음 렌더는 성공하도록 전환한 뒤 리셋.
    shouldThrow = false;
    await userEvent.click(screen.getByRole("button", { name: /다시 시도/ }));

    expect(screen.getByText("회복된 콘텐츠")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
