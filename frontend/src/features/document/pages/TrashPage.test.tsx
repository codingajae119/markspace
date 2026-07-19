import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { Role } from "@/shared/auth/roles";
import type { UseTrashResult } from "../hooks/useTrash";

/**
 * TrashPage 조립 테스트: 현재 워크스페이스 스코프(workspaceId·role)를 TrashList 로 위임함을
 * 관측한다. TrashList 는 자체 RequireRole(EDITOR) 게이트를 소유하므로, 게이트 통과(role EDITOR)
 * 시 useTrash 로드 body 가 workspaceId 로 결선됨을 확인한다. useTrash 를 모킹해 네트워크를 회피한다.
 */

const useTrashMock = vi.fn<(workspaceId: string) => UseTrashResult>();
vi.mock("../hooks/useTrash", () => ({
  useTrash: (workspaceId: string): UseTrashResult => useTrashMock(workspaceId),
}));

vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useSession } from "@/app/session/useSession";
import { TrashPage } from "./TrashPage";

const useCurrentWorkspaceMock = useCurrentWorkspace as unknown as Mock;
const useSessionMock = useSession as unknown as Mock;

beforeEach(() => {
  useTrashMock.mockReset();
  useCurrentWorkspaceMock.mockReset();
  useSessionMock.mockReset();

  useCurrentWorkspaceMock.mockReturnValue({
    status: "ready",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: "7",
    role: Role.EDITOR,
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
  });
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
  useTrashMock.mockReturnValue({
    status: "ready",
    bundles: [],
    total: 0,
    error: null,
    reload: vi.fn(),
    restore: vi.fn(),
    purge: vi.fn(),
    loadPage: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
});

describe("TrashPage 조립 (TrashList 위임)", () => {
  it("현재 WS 스코프를 TrashList 로 위임하고 editor 게이트 통과 시 휴지통 body 를 렌더한다 (Req 8.1)", () => {
    render(<TrashPage />);

    // TrashList 위임 결과: 휴지통 heading 이 노출되고 useTrash 가 현재 workspaceId 로 결선된다.
    expect(screen.getByRole("heading", { name: "휴지통" })).toBeInTheDocument();
    expect(useTrashMock).toHaveBeenCalledWith("7");
  });
});
