import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AdminOwnerChangePanel } from "./AdminOwnerChangePanel";
import { adminApi } from "../api/adminApi";
import type { WorkspaceRead } from "../api/types";
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

function workspace(overrides: Partial<WorkspaceRead> = {}): WorkspaceRead {
  return {
    id: 42,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    name: "이관된 워크스페이스",
    is_shareable: false,
    trash_retention_days: 30,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(adminApi.changeOwner).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdminOwnerChangePanel — admin WS 소유권 변경(Req 6.1·6.2·6.3)", () => {
  it("유효 입력 제출 시 changeOwner(wsId, {new_owner_user_id})를 호출한다 (Req 6.1)", async () => {
    vi.mocked(adminApi.changeOwner).mockResolvedValue(workspace({ id: 42 }));

    render(<AdminOwnerChangePanel />);

    await userEvent.type(screen.getByLabelText("워크스페이스 ID"), "42");
    await userEvent.type(screen.getByLabelText("새 소유자 사용자 ID"), "99");
    await userEvent.click(screen.getByRole("button", { name: "소유권 변경" }));

    await waitFor(() => expect(adminApi.changeOwner).toHaveBeenCalledTimes(1));
    expect(adminApi.changeOwner).toHaveBeenCalledWith(42, { new_owner_user_id: 99 });
  });

  it("성공(200) 시 반환된 WorkspaceRead를 확인으로 반영한다 (Req 6.1)", async () => {
    vi.mocked(adminApi.changeOwner).mockResolvedValue(
      workspace({ id: 42, name: "이관된 워크스페이스" }),
    );

    render(<AdminOwnerChangePanel />);

    await userEvent.type(screen.getByLabelText("워크스페이스 ID"), "42");
    await userEvent.type(screen.getByLabelText("새 소유자 사용자 ID"), "99");
    await userEvent.click(screen.getByRole("button", { name: "소유권 변경" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("이관된 워크스페이스");
    expect(status).toHaveTextContent("99");
  });

  it("새 소유자 사용자 ID 누락 시 요청 전에 막는다(changeOwner 미호출) (Req 6.3)", async () => {
    render(<AdminOwnerChangePanel />);

    await userEvent.type(screen.getByLabelText("워크스페이스 ID"), "42");
    await userEvent.click(screen.getByRole("button", { name: "소유권 변경" }));

    // 클라이언트 가드: 누락 입력은 요청 전에 차단된다.
    expect(adminApi.changeOwner).not.toHaveBeenCalled();
  });

  it("워크스페이스 ID 누락 시 요청 전에 막는다(changeOwner 미호출) (Req 6.3)", async () => {
    render(<AdminOwnerChangePanel />);

    await userEvent.type(screen.getByLabelText("새 소유자 사용자 ID"), "99");
    await userEvent.click(screen.getByRole("button", { name: "소유권 변경" }));

    expect(adminApi.changeOwner).not.toHaveBeenCalled();
  });

  it("404(대상 WS·사용자 미존재)를 ErrorMessage(role=alert)로 표시한다 (Req 6.3)", async () => {
    vi.mocked(adminApi.changeOwner).mockRejectedValue(
      new ApiError({
        status: 404,
        code: "not_found",
        message: "대상을 찾을 수 없습니다.",
      }),
    );

    render(<AdminOwnerChangePanel />);

    await userEvent.type(screen.getByLabelText("워크스페이스 ID"), "42");
    await userEvent.type(screen.getByLabelText("새 소유자 사용자 ID"), "99");
    await userEvent.click(screen.getByRole("button", { name: "소유권 변경" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("대상을 찾을 수 없습니다.");
  });

  it("403(권한 미충족)을 ErrorMessage(role=alert)로 표시한다 (Req 6.3)", async () => {
    vi.mocked(adminApi.changeOwner).mockRejectedValue(
      new ApiError({
        status: 403,
        code: "forbidden",
        message: "권한이 없습니다.",
      }),
    );

    render(<AdminOwnerChangePanel />);

    await userEvent.type(screen.getByLabelText("워크스페이스 ID"), "42");
    await userEvent.type(screen.getByLabelText("새 소유자 사용자 ID"), "99");
    await userEvent.click(screen.getByRole("button", { name: "소유권 변경" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("권한이 없습니다.");
  });
});
