import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LoginForm } from "./LoginForm";
import { useLogin } from "../hooks/useLogin";
import { ApiError } from "@/shared/api/errors";

// s16 useLogin 훅을 모킹하여 제출/진행/오류 상태를 테스트가 제어한다(경계: LoginForm 만 검증).
vi.mock("../hooks/useLogin", () => ({ useLogin: vi.fn() }));

const submitMock = vi.fn<(credentials: { login_id: string; password: string }) => Promise<void>>();

function setUseLogin(overrides: {
  submitting?: boolean;
  error?: ApiError | null;
}): void {
  vi.mocked(useLogin).mockReturnValue({
    submit: submitMock,
    submitting: overrides.submitting ?? false,
    error: overrides.error ?? null,
  });
}

beforeEach(() => {
  submitMock.mockReset();
  submitMock.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LoginForm — 자격 입력·인라인 에러·로딩 (1.1, 1.4, 2.1, 2.4)", () => {
  it("login_id·password 입력과 제출 컨트롤을 렌더한다 (Req 1.1)", () => {
    setUseLogin({});
    render(<LoginForm />);

    expect(screen.getByLabelText("아이디")).toBeInTheDocument();
    const password = screen.getByLabelText("비밀번호");
    expect(password).toBeInTheDocument();
    expect(password).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "로그인" })).toBeInTheDocument();
  });

  it("제출 시 preventDefault 후 useLogin().submit 를 { login_id, password } 로 호출한다 (Req 1.1)", async () => {
    setUseLogin({});
    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText("아이디"), "alice");
    await userEvent.type(screen.getByLabelText("비밀번호"), "s3cret-pass");
    await userEvent.click(screen.getByRole("button", { name: "로그인" }));

    expect(submitMock).toHaveBeenCalledTimes(1);
    expect(submitMock).toHaveBeenCalledWith({ login_id: "alice", password: "s3cret-pass" });
  });

  it("submitting 중에는 제출·입력 컨트롤이 비활성화되고 Spinner(role=status)를 표시한다 (Req 1.4)", () => {
    setUseLogin({ submitting: true });
    render(<LoginForm />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByLabelText("아이디")).toBeDisabled();
    expect(screen.getByLabelText("비밀번호")).toBeDisabled();
  });

  it("error 가 있으면 ErrorMessage(role=alert)로 백엔드 메시지를 인라인 표시한다 (Req 2.1, 2.4)", () => {
    const error = new ApiError({
      status: 401,
      code: "unauthenticated",
      message: "Invalid credentials",
    });
    setUseLogin({ error });
    render(<LoginForm />);

    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent("Invalid credentials");
  });

  it("error 가 null 이면 오류 영역(role=alert)을 렌더하지 않는다 (Req 2.5)", () => {
    setUseLogin({ error: null });
    render(<LoginForm />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
