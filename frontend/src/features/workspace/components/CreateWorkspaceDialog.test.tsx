import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CreateWorkspaceDialog } from "./CreateWorkspaceDialog";
import { useWorkspaceActions } from "../hooks/useWorkspaceActions";
import type { WorkspaceRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// useWorkspaceActions 훅을 모킹하여 생성 폼의 클라이언트 가드·성공 초기화·오류 표시를
// 폼 단독 경계에서 검증한다.
vi.mock("../hooks/useWorkspaceActions", () => ({ useWorkspaceActions: vi.fn() }));

const createMock = vi.fn<(body: { name: string }) => Promise<WorkspaceRead | null>>();

function created(): WorkspaceRead {
  return {
    id: 3,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    name: "새 워크스페이스",
    is_shareable: false,
    trash_retention_days: 30,
  };
}

function setActions(overrides: { creating?: boolean; error?: ApiError | null }): void {
  vi.mocked(useWorkspaceActions).mockReturnValue({
    create: createMock,
    creating: overrides.creating ?? false,
    // task 5.1 에서 확장된 update·remove·saving 표면(이 다이얼로그는 create 만 소비).
    update: vi.fn().mockResolvedValue(null),
    remove: vi.fn().mockResolvedValue(false),
    saving: false,
    error: overrides.error ?? null,
  });
}

beforeEach(() => {
  createMock.mockReset();
  createMock.mockResolvedValue(created());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CreateWorkspaceDialog — 생성 폼 (Req 2.1, 2.2, 2.4)", () => {
  it("이름 입력과 생성 컨트롤을 렌더한다 (Req 2.1)", () => {
    setActions({});
    render(<CreateWorkspaceDialog />);

    expect(screen.getByLabelText("워크스페이스 이름")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "워크스페이스 생성" })).toBeInTheDocument();
  });

  it("이름이 비었으면 생성 버튼이 비활성화된다 (Req 2.2 클라이언트 가드)", () => {
    setActions({});
    render(<CreateWorkspaceDialog />);

    expect(screen.getByRole("button", { name: "워크스페이스 생성" })).toBeDisabled();
  });

  it("공백만 입력한 이름으로 폼을 제출해도 create 를 호출하지 않는다 (Req 2.2 클라이언트 가드)", () => {
    setActions({});
    render(<CreateWorkspaceDialog />);

    const input = screen.getByLabelText("워크스페이스 이름");
    fireEvent.change(input, { target: { value: "   " } });
    // 버튼 비활성화 우회를 위해 폼 제출을 직접 발동한다.
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(createMock).not.toHaveBeenCalled();
  });

  it("유효한 이름으로 제출하면 create({ name }) 를 트림된 값으로 호출한다 (Req 2.1)", async () => {
    setActions({});
    render(<CreateWorkspaceDialog />);

    await userEvent.type(screen.getByLabelText("워크스페이스 이름"), "  마케팅  ");
    await userEvent.click(screen.getByRole("button", { name: "워크스페이스 생성" }));

    expect(createMock).toHaveBeenCalledTimes(1);
    expect(createMock).toHaveBeenCalledWith({ name: "마케팅" });
  });

  it("생성 성공 시 입력을 초기화한다 (성공 신호)", async () => {
    setActions({});
    createMock.mockResolvedValueOnce(created());
    render(<CreateWorkspaceDialog />);

    const input = screen.getByLabelText("워크스페이스 이름") as HTMLInputElement;
    await userEvent.type(input, "마케팅");
    await userEvent.click(screen.getByRole("button", { name: "워크스페이스 생성" }));

    await waitFor(() => expect(input.value).toBe(""));
  });

  it("생성 실패 시 입력을 초기화하지 않는다 (성공 신호 부재)", async () => {
    setActions({});
    createMock.mockResolvedValueOnce(null);
    render(<CreateWorkspaceDialog />);

    const input = screen.getByLabelText("워크스페이스 이름") as HTMLInputElement;
    await userEvent.type(input, "마케팅");
    await userEvent.click(screen.getByRole("button", { name: "워크스페이스 생성" }));

    await waitFor(() => expect(createMock).toHaveBeenCalled());
    expect(input.value).toBe("마케팅");
  });

  it("error 가 있으면 ErrorMessage(role=alert)로 서버 422 를 표시한다 (Req 2.4)", () => {
    const error = new ApiError({
      status: 422,
      code: "validation_error",
      message: "이름은 공백일 수 없습니다",
    });
    setActions({ error });
    render(<CreateWorkspaceDialog />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("이름은 공백일 수 없습니다");
  });

  it("creating 중에는 입력·제출이 비활성화되고 Spinner(role=status)를 표시한다", () => {
    setActions({ creating: true });
    render(<CreateWorkspaceDialog />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByLabelText("워크스페이스 이름")).toBeDisabled();
  });
});
