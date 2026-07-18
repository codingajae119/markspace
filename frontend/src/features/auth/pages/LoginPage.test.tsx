import { describe, it, expect, afterEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { LoginPage } from "./LoginPage";
import { useLogin } from "../hooks/useLogin";

// LoginForm 이 소비하는 useLogin 을 모킹(경계: 페이지는 LoginForm 배치만 검증).
vi.mock("../hooks/useLogin", () => ({ useLogin: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LoginPage — 게스트 프레임 대상 element (1.1)", () => {
  it("LoginForm 을 배치하여 login_id·password 입력을 렌더한다 (Req 1.1)", () => {
    vi.mocked(useLogin).mockReturnValue({
      submit: vi.fn(),
      submitting: false,
      error: null,
    });

    render(<LoginPage />);

    expect(screen.getByLabelText("아이디")).toBeInTheDocument();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "로그인" })).toBeInTheDocument();
  });
});
