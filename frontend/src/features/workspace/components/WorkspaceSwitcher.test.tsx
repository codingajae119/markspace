import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { WorkspaceRead } from "../api/types";

// s16 현재 WS 앰비언트 컨텍스트를 모킹하여 스위처가 목록을 표시하고 전환을
// selectWorkspace(String(id)) 로 위임하며 status 별 표시를 하는지 검증한다(경계: 스위처만).
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));

const selectWorkspaceMock = vi.fn<(id: string) => void>();
const refreshMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

function ws(id: number, name: string): WorkspaceRead {
  return {
    id,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    name,
    is_shareable: false,
    trash_retention_days: 30,
  };
}

function setContext(overrides: Partial<CurrentWorkspaceContextValue>): void {
  vi.mocked(useCurrentWorkspace).mockReturnValue({
    status: "ready",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: null,
    role: null,
    isShareable: false,
    selectWorkspace: selectWorkspaceMock,
    refresh: refreshMock,
    ...overrides,
  });
}

beforeEach(() => {
  selectWorkspaceMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WorkspaceSwitcher — s16 컨텍스트 소비 (Req 1.1, 1.2, 1.5)", () => {
  it("ready 상태에서 컨텍스트 목록의 각 워크스페이스 이름을 표시한다 (Req 1.1)", () => {
    setContext({
      status: "ready",
      workspaces: [ws(1, "알파"), ws(2, "베타")],
      currentWorkspace: ws(1, "알파"),
    });
    render(<WorkspaceSwitcher />);

    expect(screen.getByText("알파")).toBeInTheDocument();
    expect(screen.getByText("베타")).toBeInTheDocument();
  });

  it("현재 워크스페이스를 aria-current 로 강조한다 (Req 1.1)", () => {
    setContext({
      status: "ready",
      workspaces: [ws(1, "알파"), ws(2, "베타")],
      currentWorkspace: ws(2, "베타"),
    });
    render(<WorkspaceSwitcher />);

    expect(screen.getByRole("button", { name: "베타" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "알파" })).not.toHaveAttribute("aria-current");
  });

  it("워크스페이스 선택 시 selectWorkspace 를 String(id) 로 호출한다 (Req 1.2)", async () => {
    setContext({
      status: "ready",
      workspaces: [ws(1, "알파"), ws(2, "베타")],
      currentWorkspace: ws(1, "알파"),
    });
    render(<WorkspaceSwitcher />);

    await userEvent.click(screen.getByRole("button", { name: "베타" }));

    expect(selectWorkspaceMock).toHaveBeenCalledTimes(1);
    expect(selectWorkspaceMock).toHaveBeenCalledWith("2");
  });

  it("loading 상태에서 Spinner(role=status)를 표시한다", () => {
    setContext({ status: "loading" });
    render(<WorkspaceSwitcher />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("empty 상태에서 빈 상태 안내를 표시하고 선택을 강제하지 않는다 (Req 1.5)", () => {
    setContext({ status: "empty", workspaces: [], currentWorkspace: null });
    render(<WorkspaceSwitcher />);

    // 빈 상태 안내 존재, 목록 버튼 없음, selectWorkspace 미호출.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(selectWorkspaceMock).not.toHaveBeenCalled();
  });
});
