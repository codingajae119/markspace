import { describe, it, expect, afterEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LogoutButton } from "./LogoutButton";
import { useLogout } from "../hooks/useLogout";

// s16 useLogout 훅을 모킹하여 제출/진행 상태를 테스트가 제어한다(경계: LogoutButton 만 검증).
vi.mock("../hooks/useLogout", () => ({ useLogout: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LogoutButton — 로그아웃 트리거·진행 중 비활성 (3.1, 3.4)", () => {
  it("클릭 시 useLogout().submit 를 한 번 호출한다 (Req 3.1)", async () => {
    const submitMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
    vi.mocked(useLogout).mockReturnValue({ submit: submitMock, submitting: false });

    render(<LogoutButton />);
    await userEvent.click(screen.getByRole("button", { name: /로그아웃/ }));

    expect(submitMock).toHaveBeenCalledTimes(1);
  });

  it("submitting 중에는 버튼을 비활성화한다 (Req 3.4)", () => {
    vi.mocked(useLogout).mockReturnValue({ submit: vi.fn(), submitting: true });

    render(<LogoutButton />);

    expect(screen.getByRole("button", { name: /로그아웃/ })).toBeDisabled();
  });

  it("className 을 하위 Button 으로 전달한다", () => {
    vi.mocked(useLogout).mockReturnValue({ submit: vi.fn(), submitting: false });

    render(<LogoutButton className="custom-cls" />);

    expect(screen.getByRole("button", { name: /로그아웃/ })).toHaveClass("custom-cls");
  });
});
