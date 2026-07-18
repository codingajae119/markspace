import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChangePasswordPage } from "./ChangePasswordPage";
import { useChangePassword } from "../hooks/useChangePassword";
import { ApiError } from "@/shared/api/errors";

// s16 useChangePassword 훅을 모킹하여 제출/진행/성공/오류 상태를 테스트가 제어한다(경계: ChangePasswordPage 만 검증).
vi.mock("../hooks/useChangePassword", () => ({ useChangePassword: vi.fn() }));

const submitMock =
  vi.fn<(input: { current_password: string; new_password: string }) => Promise<void>>();

function setUseChangePassword(overrides: {
  submitting?: boolean;
  succeeded?: boolean;
  error?: ApiError | null;
}): void {
  vi.mocked(useChangePassword).mockReturnValue({
    submit: submitMock,
    submitting: overrides.submitting ?? false,
    succeeded: overrides.succeeded ?? false,
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

describe("ChangePasswordPage — 현재/새 비밀번호·성공/오류 표면화 (4.1, 4.3, 4.4, 4.5, 4.6)", () => {
  it("현재/새 비밀번호 입력(type=password)과 제출 컨트롤만 렌더한다 — 타인 대상 지정 입력 없음 (Req 4.1)", () => {
    setUseChangePassword({});
    render(<ChangePasswordPage />);

    const current = screen.getByLabelText("현재 비밀번호");
    const next = screen.getByLabelText("새 비밀번호");
    expect(current).toBeInTheDocument();
    expect(current).toHaveAttribute("type", "password");
    expect(next).toBeInTheDocument();
    expect(next).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "비밀번호 변경" })).toBeInTheDocument();

    // 대상은 항상 현재 사용자: 다른 사용자를 지정하는 필드(예: login_id/user)가 없어야 한다.
    expect(screen.queryByLabelText(/아이디|사용자|user/i)).not.toBeInTheDocument();
  });

  it("제출 시 preventDefault 후 submit 을 { current_password, new_password } 로 호출한다 (Req 4.2)", async () => {
    setUseChangePassword({});
    render(<ChangePasswordPage />);

    await userEvent.type(screen.getByLabelText("현재 비밀번호"), "old-pass-123");
    await userEvent.type(screen.getByLabelText("새 비밀번호"), "new-pass-4567");
    await userEvent.click(screen.getByRole("button", { name: "비밀번호 변경" }));

    expect(submitMock).toHaveBeenCalledTimes(1);
    expect(submitMock).toHaveBeenCalledWith({
      current_password: "old-pass-123",
      new_password: "new-pass-4567",
    });
  });

  it("succeeded=false→true 전이 시 성공 메시지를 표시하고 채워진 입력을 안전한 초기 상태로 정리한다 (Req 4.3)", async () => {
    // 초기: 성공 이전. 실제 비어있지 않은 값을 입력해 clear-on-success 를 진짜로 검증한다
    // (정적 succeeded=true + 이미 빈 입력이면 assertion 이 trivially 통과하는 NO-OP 를 피한다).
    setUseChangePassword({ succeeded: false });
    const { rerender } = render(<ChangePasswordPage />);

    const current = screen.getByLabelText("현재 비밀번호");
    const next = screen.getByLabelText("새 비밀번호");
    await userEvent.type(current, "old-pass-123");
    await userEvent.type(next, "new-pass-4567");

    // 전제: 입력이 실제로 채워져 있다(성공 전).
    expect(current).toHaveValue("old-pass-123");
    expect(next).toHaveValue("new-pass-4567");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    // 성공 신호 전이 후 재렌더 → useEffect([succeeded]) 가 입력을 초기화해야 한다.
    setUseChangePassword({ succeeded: true });
    rerender(<ChangePasswordPage />);

    // 성공 표시(role=status)와 실제 성공 문구.
    expect(screen.getByRole("status")).toHaveTextContent("비밀번호가 변경되었습니다.");
    // 채워졌던 입력이 clear-on-success effect 로 빈 값이 되어야 한다(effect 제거 시 이 두 줄이 실패).
    expect(current).toHaveValue("");
    expect(next).toHaveValue("");
  });

  it("422 unprocessable 시 ErrorMessage(role=alert)로 현재 비밀번호 불일치 message 를 표시한다 (Req 4.4)", () => {
    const error = new ApiError({
      status: 422,
      code: "unprocessable",
      message: "Current password does not match",
    });
    setUseChangePassword({ error });
    render(<ChangePasswordPage />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Current password does not match");
  });

  it("422 validation_error 시 ErrorMessage 로 새 비밀번호 정책 field_errors 를 동일 유틸로 표시한다 (Req 4.5)", () => {
    const error = new ApiError({
      status: 422,
      code: "validation_error",
      message: "Validation failed",
      fieldErrors: [{ field: "new_password", message: "at least 8 characters" }],
    });
    setUseChangePassword({ error });
    render(<ChangePasswordPage />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("new_password");
    expect(alert).toHaveTextContent("at least 8 characters");
  });

  it("error 가 null 이면 오류 영역(role=alert)을 렌더하지 않는다", () => {
    setUseChangePassword({ error: null });
    render(<ChangePasswordPage />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("submitting 중에는 제출·입력 컨트롤이 비활성화되고 Spinner(role=status)를 표시한다", () => {
    setUseChangePassword({ submitting: true });
    render(<ChangePasswordPage />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByLabelText("현재 비밀번호")).toBeDisabled();
    expect(screen.getByLabelText("새 비밀번호")).toBeDisabled();
  });
});
