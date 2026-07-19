import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PasswordResetDialog } from "./PasswordResetDialog";
import { adminApi } from "../api/adminApi";
import type { UserRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

vi.mock("../api/adminApi", () => ({
  adminApi: {
    listUsers: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    resetPassword: vi.fn(),
    changeOwner: vi.fn(),
  },
}));

function user(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: 7,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    login_id: "bob",
    name: "밥",
    email: null,
    is_admin: false,
    is_active: true,
    is_deleted: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(adminApi.resetPassword).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PasswordResetDialog — 비밀번호 재설정(Req 5.4)", () => {
  it("제출 시 resetPassword(id, {new_password})를 호출한다 (Req 5.4)", async () => {
    vi.mocked(adminApi.resetPassword).mockResolvedValue(undefined);

    render(<PasswordResetDialog user={user({ id: 7 })} onClose={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("새 비밀번호"), "newpw123456");
    await userEvent.click(screen.getByRole("button", { name: "재설정" }));

    await waitFor(() => expect(adminApi.resetPassword).toHaveBeenCalledTimes(1));
    expect(adminApi.resetPassword).toHaveBeenCalledWith(7, { new_password: "newpw123456" });
  });

  it("성공(204) 시 재설정 완료를 사용자에게 확인한다 (Req 5.4)", async () => {
    vi.mocked(adminApi.resetPassword).mockResolvedValue(undefined);

    render(<PasswordResetDialog user={user({ id: 7 })} onClose={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("새 비밀번호"), "newpw123456");
    await userEvent.click(screen.getByRole("button", { name: "재설정" }));

    expect(await screen.findByText(/재설정되었습니다/)).toBeInTheDocument();
  });

  it("성공 후 비밀번호를 화면에 보존하지 않는다 (비밀번호 미보존)", async () => {
    vi.mocked(adminApi.resetPassword).mockResolvedValue(undefined);

    render(<PasswordResetDialog user={user({ id: 7 })} onClose={vi.fn()} />);

    const pw = screen.getByLabelText("새 비밀번호") as HTMLInputElement;
    await userEvent.type(pw, "newpw123456");
    await userEvent.click(screen.getByRole("button", { name: "재설정" }));

    await waitFor(() => expect(pw.value).toBe(""));
  });

  it("검증 422 는 ErrorMessage(role=alert)로 표시한다 (Req 5.7)", async () => {
    vi.mocked(adminApi.resetPassword).mockRejectedValue(
      new ApiError({
        status: 422,
        code: "validation_error",
        message: "검증에 실패했습니다.",
        fieldErrors: [{ field: "new_password", message: "너무 짧습니다." }],
      }),
    );

    render(<PasswordResetDialog user={user({ id: 7 })} onClose={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("새 비밀번호"), "x");
    await userEvent.click(screen.getByRole("button", { name: "재설정" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("너무 짧습니다.");
  });

  it("닫기 버튼은 onClose 를 호출한다", async () => {
    const onClose = vi.fn();
    render(<PasswordResetDialog user={user({ id: 7 })} onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: "닫기" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
