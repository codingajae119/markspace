import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CopyLinkButton } from "./CopyLinkButton";

const LINK = "https://app.example.com/share/tok-abc123";

/**
 * jsdom 은 실제 클립보드가 없으므로 `navigator.clipboard` 를 테스트마다 명시적으로
 * 주입/해제하여 성공·실패·부재 경로를 결정적으로 검증한다.
 */
function setClipboard(writeText: ((text: string) => Promise<void>) | undefined): void {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: writeText === undefined ? undefined : { writeText },
  });
}

beforeEach(() => {
  setClipboard(vi.fn().mockResolvedValue(undefined));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CopyLinkButton — 링크 복사 (Req 4.1, 4.2, 4.3, 4.4)", () => {
  it("링크가 있으면 클릭 시 정확한 절대 링크를 클립보드에 복사하고 성공 피드백을 표시한다 (Req 4.1, 4.2)", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    // userEvent.setup() 이 자체 클립보드 스텁을 설치하므로, 그 뒤에 우리 모의를 덮어써야
    // 컴포넌트가 클릭 시 우리 spy 를 읽는다.
    const user = userEvent.setup();
    setClipboard(writeText);

    render(<CopyLinkButton frontShareUrl={LINK} />);

    await user.click(screen.getByRole("button", { name: /복사/ }));

    // 정확히 전달받은 절대 링크를 클립보드에 기록한다.
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(LINK);
    // 즉각적인 성공 피드백("복사됨")이 사용자에게 보인다.
    expect(await screen.findByText(/복사됨/)).toBeInTheDocument();
  });

  it("writeText 가 거부되면 폴백으로 선택·복사 가능한 링크 문자열을 표시한다 (Req 4.3)", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const user = userEvent.setup();
    setClipboard(writeText);

    render(<CopyLinkButton frontShareUrl={LINK} />);

    await user.click(screen.getByRole("button", { name: /복사/ }));

    // 오류가 사용자에게 던져지지 않고, 폴백 입력이 링크 문자열을 담아 표시된다.
    const fallback = await screen.findByLabelText(/공유 링크/);
    expect(fallback).toHaveValue(LINK);
    expect(fallback).toHaveAttribute("readonly");
  });

  it("navigator.clipboard 가 없으면 크래시 없이 동일한 폴백을 제공한다 (Req 4.3)", async () => {
    setClipboard(undefined);

    render(<CopyLinkButton frontShareUrl={LINK} />);

    // userEvent 의 클립보드 스텁 개입을 피하기 위해 fireEvent 로 직접 클릭한다.
    fireEvent.click(screen.getByRole("button", { name: /복사/ }));

    const fallback = await screen.findByLabelText(/공유 링크/);
    expect(fallback).toHaveValue(LINK);
  });

  it("링크가 null 이면 버튼이 비활성화되고 클릭해도 복사하지 않는다 (Req 4.4)", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    setClipboard(writeText);

    render(<CopyLinkButton frontShareUrl={null} />);

    const button = screen.getByRole("button", { name: /복사/ });
    expect(button).toBeDisabled();

    await user.click(button);
    expect(writeText).not.toHaveBeenCalled();
  });

  it("링크가 null 이면 폴백/성공 피드백을 표시하지 않는다 (Req 4.4)", () => {
    render(<CopyLinkButton frontShareUrl={null} />);

    expect(screen.queryByText(/복사됨/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/공유 링크/)).not.toBeInTheDocument();
  });
});
