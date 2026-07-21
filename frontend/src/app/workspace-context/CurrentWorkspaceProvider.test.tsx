import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  CurrentWorkspaceProvider,
  CURRENT_WORKSPACE_STORAGE_KEY,
} from "@/app/workspace-context/CurrentWorkspaceProvider";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { apiClient } from "@/shared/api/client";
import { useSession } from "@/app/session/useSession";
import { Role } from "@/shared/auth/roles";
import type { WorkspaceRead } from "@/shared/types/workspace";
import type { Page } from "@/shared/types/page";

// 앰비언트 컨텍스트 통합 테스트는 실제 HTTP 대신 apiClient 를 모킹하고, 인증 게이팅을 통제하기 위해
// useSession 도 모킹한다. 이로써 목록 로드·선택 영속/복원·유효하지 않은 저장 id·refresh 재조회를 관찰한다.
vi.mock("@/shared/api/client", () => ({ apiClient: { get: vi.fn(), patch: vi.fn() } }));
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

const getMock = apiClient.get as unknown as Mock;
const patchMock = apiClient.patch as unknown as Mock;
const useSessionMock = useSession as unknown as Mock;

const ws1: WorkspaceRead = {
  id: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  name: "WS One",
  is_shareable: true,
  trash_retention_days: 30,
};

const ws2: WorkspaceRead = {
  id: 2,
  created_at: "2026-01-02T00:00:00Z",
  updated_at: null,
  name: "WS Two",
  is_shareable: false,
  trash_retention_days: 30,
};

/** role="owner" 를 담은 WS(멤버십 role 파생 관찰용). */
const wsOwner: WorkspaceRead = {
  id: 3,
  created_at: "2026-01-03T00:00:00Z",
  updated_at: null,
  name: "WS Owner",
  is_shareable: true,
  trash_retention_days: 30,
  role: "owner",
};

/** role="member" 를 담은 WS(전환 시 재파생 관찰용). */
const wsMember: WorkspaceRead = {
  id: 4,
  created_at: "2026-01-04T00:00:00Z",
  updated_at: null,
  name: "WS Member",
  is_shareable: false,
  trash_retention_days: 30,
  role: "member",
};

/** role=null 을 명시한 WS(비멤버/미시드 → provider-role null 관찰용). */
const wsNullRole: WorkspaceRead = {
  id: 5,
  created_at: "2026-01-05T00:00:00Z",
  updated_at: null,
  name: "WS Null Role",
  is_shareable: false,
  trash_retention_days: 30,
  role: null,
};

/** apiClient.get("/workspaces") 가 반환할 Page<WorkspaceRead> 를 구성한다. */
function page(items: WorkspaceRead[]): Page<WorkspaceRead> {
  return { items, total: items.length };
}

/**
 * useSession 이 authenticated 를 반환하도록 설정(provider 의 로드 게이팅 통과).
 * `lastSelectedWorkspaceId` 를 주면 서버 설정(교차 브라우저 복원 소스)을 실은 settings 를 노출한다.
 */
function mockAuthenticated(lastSelectedWorkspaceId: number | null = null): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings:
      lastSelectedWorkspaceId === null
        ? null
        : {
            autosave_enabled: false,
            last_selected_workspace_id: lastSelectedWorkspaceId,
          },
    refresh: vi.fn(),
  });
}

/** useSession 이 unauthenticated 를 반환하도록 설정(provider 유휴). */
function mockUnauthenticated(): void {
  useSessionMock.mockReturnValue({ status: "unauthenticated", refresh: vi.fn() });
}

/** useCurrentWorkspace() 를 소비해 단일 형태를 노출하는 최소 프로브. */
function Probe() {
  const ws = useCurrentWorkspace();
  return (
    <div>
      <span data-testid="status">{ws.status}</span>
      <span data-testid="count">{String(ws.workspaces.length)}</span>
      <span data-testid="current-name">{ws.currentWorkspace?.name ?? "null"}</span>
      <span data-testid="workspace-id">{ws.workspaceId ?? "null"}</span>
      <span data-testid="shareable">{String(ws.isShareable)}</span>
      <span data-testid="role">{ws.role === null ? "null" : String(ws.role)}</span>
      <button type="button" onClick={() => ws.selectWorkspace(String(ws2.id))}>
        select-ws2
      </button>
      <button type="button" onClick={() => ws.selectWorkspace(String(wsMember.id))}>
        select-member
      </button>
      <button
        type="button"
        onClick={() => {
          void ws.refresh();
        }}
      >
        refresh
      </button>
    </div>
  );
}

function renderWithProvider(): void {
  render(
    <CurrentWorkspaceProvider>
      <Probe />
    </CurrentWorkspaceProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  patchMock.mockReset();
  // 설정 영속 PATCH 는 fire-and-forget: 항상 resolve 하도록 기본 스텁.
  patchMock.mockResolvedValue({ autosave_enabled: false, last_selected_workspace_id: null });
  useSessionMock.mockReset();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("CurrentWorkspaceProvider ambient context", () => {
  it("인증 + 목록 존재 → ready, 첫 WS 기본 선택, 파생 접근자·role=null (AC 9.2, 9.3)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([ws1, ws2]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("count")).toHaveTextContent("2");
    expect(screen.getByTestId("current-name")).toHaveTextContent("WS One");
    expect(screen.getByTestId("workspace-id")).toHaveTextContent(String(ws1.id));
    expect(screen.getByTestId("shareable")).toHaveTextContent(String(ws1.is_shareable));
    expect(screen.getByTestId("role")).toHaveTextContent("null");
    expect(getMock).toHaveBeenCalledWith("/workspaces");
  });

  it("인증 + 빈 목록 → empty, currentWorkspace/workspaceId null, isShareable false (AC 9.4)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("empty"));
    expect(screen.getByTestId("current-name")).toHaveTextContent("null");
    expect(screen.getByTestId("workspace-id")).toHaveTextContent("null");
    expect(screen.getByTestId("shareable")).toHaveTextContent("false");
  });

  it("selectWorkspace 가 현재 WS 를 바꾸고 localStorage 에 영속한다 (AC 9.4)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([ws1, ws2]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS One"));

    await userEvent.click(screen.getByRole("button", { name: "select-ws2" }));

    expect(screen.getByTestId("current-name")).toHaveTextContent("WS Two");
    expect(screen.getByTestId("workspace-id")).toHaveTextContent(String(ws2.id));
    expect(screen.getByTestId("shareable")).toHaveTextContent(String(ws2.is_shareable));
    expect(localStorage.getItem(CURRENT_WORKSPACE_STORAGE_KEY)).toBe(String(ws2.id));
  });

  it("selectWorkspace 가 마지막 선택을 서버에 영속한다: PATCH /me/settings (교차 브라우저 복원)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([ws1, ws2]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS One"));

    await userEvent.click(screen.getByRole("button", { name: "select-ws2" }));

    // 서버에 숫자 id 로 영속(백엔드 last_selected_workspace_id: int).
    expect(patchMock).toHaveBeenCalledWith("/me/settings", {
      last_selected_workspace_id: ws2.id,
    });
  });

  it("서버 설정의 last_selected_workspace_id 를 복원한다: localStorage 없이도 그 WS 선택 (교차 브라우저)", async () => {
    // 다른 브라우저에서 test2(ws2)를 마지막 선택한 상태를 서버가 보유. 현재 브라우저 localStorage 는 비어 있다.
    mockAuthenticated(ws2.id);
    getMock.mockResolvedValue(page([ws1, ws2]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS Two"));
    expect(screen.getByTestId("workspace-id")).toHaveTextContent(String(ws2.id));
  });

  it("서버 설정이 localStorage 보다 우선한다: 서버=ws2, localStorage=ws1 → ws2 선택", async () => {
    mockAuthenticated(ws2.id);
    getMock.mockResolvedValue(page([ws1, ws2]));
    localStorage.setItem(CURRENT_WORKSPACE_STORAGE_KEY, String(ws1.id));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS Two"));
  });

  it("서버의 stale id(목록에 없음)는 무시하고 첫 WS 로 폴백한다", async () => {
    mockAuthenticated(999);
    getMock.mockResolvedValue(page([ws1, ws2]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("current-name")).toHaveTextContent("WS One");
  });

  it("재로드 시 영속된 선택을 복원한다: 저장된 id 가 첫 WS 가 아니어도 그 WS 를 선택 (AC 9.4)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([ws1, ws2]));
    localStorage.setItem(CURRENT_WORKSPACE_STORAGE_KEY, String(ws2.id));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS Two"));
    expect(screen.getByTestId("workspace-id")).toHaveTextContent(String(ws2.id));
  });

  it("유효하지 않은 저장 id 는 무시하고 첫 WS 로 폴백(크래시 없음) (AC 9.4)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([ws1, ws2]));
    localStorage.setItem(CURRENT_WORKSPACE_STORAGE_KEY, "999");

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("current-name")).toHaveTextContent("WS One");
  });

  it("미인증이면 provider 는 유휴: /workspaces 를 호출하지 않고 status 는 loading 유지 (postcondition)", async () => {
    mockUnauthenticated();

    renderWithProvider();

    // 미인증에서는 목록 로드가 트리거되지 않는다.
    await Promise.resolve();
    expect(getMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("status")).toHaveTextContent("loading");
  });

  it("refresh() 가 /workspaces 를 재조회하고 현재 선택을 유지하며 목록을 조정한다 (AC 9.5)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValueOnce(page([ws1]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("count")).toHaveTextContent("1"));
    expect(screen.getByTestId("current-name")).toHaveTextContent("WS One");

    // 목록이 늘어난 상태로 재조회.
    getMock.mockResolvedValueOnce(page([ws1, ws2]));
    await userEvent.click(screen.getByRole("button", { name: "refresh" }));

    await waitFor(() => expect(screen.getByTestId("count")).toHaveTextContent("2"));
    // 여전히 존재하는 현재 선택(ws1)은 유지된다.
    expect(screen.getByTestId("current-name")).toHaveTextContent("WS One");
    expect(getMock).toHaveBeenCalledTimes(2);
  });

  it("role 있는 WS 선택 시 provider-role 이 멤버십 role 로 파생된다 (Req 2.2)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([wsOwner, wsMember]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS Owner"));
    // owner WS 가 첫 선택 → provider-role 은 비-null 실값(Role.OWNER).
    expect(screen.getByTestId("role")).toHaveTextContent(String(Role.OWNER));
  });

  it("워크스페이스 전환 시 전환 WS 의 멤버십 role 로 재파생된다 (Req 2.3)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([wsOwner, wsMember]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("role")).toHaveTextContent(String(Role.OWNER)));

    await userEvent.click(screen.getByRole("button", { name: "select-member" }));

    expect(screen.getByTestId("current-name")).toHaveTextContent("WS Member");
    // 전환된 WS(member)의 role 로 재파생.
    expect(screen.getByTestId("role")).toHaveTextContent(String(Role.MEMBER));
  });

  it("role 부재 WS 선택 시 provider-role 은 null 이다 (Req 2.4)", async () => {
    mockAuthenticated();
    // ws1 은 role 필드가 없다(부재) → provider-role null.
    getMock.mockResolvedValue(page([ws1]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS One"));
    expect(screen.getByTestId("role")).toHaveTextContent("null");
  });

  it("role=null 명시 WS 선택 시 provider-role 은 null 이다 (Req 2.4)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([wsNullRole]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("current-name")).toHaveTextContent("WS Null Role"));
    expect(screen.getByTestId("role")).toHaveTextContent("null");
  });

  it("워크스페이스 미선택(빈 목록)이면 provider-role 은 null 이다 (Req 2.4)", async () => {
    mockAuthenticated();
    getMock.mockResolvedValue(page([]));

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("empty"));
    expect(screen.getByTestId("current-name")).toHaveTextContent("null");
    expect(screen.getByTestId("role")).toHaveTextContent("null");
  });

  it("useCurrentWorkspace() 를 provider 밖에서 쓰면 명확한 오류를 던진다 (AC 9.1)", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/CurrentWorkspaceProvider/);
    spy.mockRestore();
  });
});
