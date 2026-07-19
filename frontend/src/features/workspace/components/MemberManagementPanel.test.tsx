import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MemberManagementPanel } from "./MemberManagementPanel";
import { Role } from "@/shared/auth/roles";
import { useSession } from "@/app/session/useSession";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { useMemberActions } from "../hooks/useMemberActions";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { MemberRead, WorkspaceRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// 진짜 RequireRole 게이트를 관통시키기 위해 게이트가 읽는 세션과 role 조달 leaf 만 모킹한다.
// RequireRole 자체는 모킹하지 않는다(게이트 의미를 실제로 검증). RoleSelect·ErrorMessage 도 실물.
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({ useCurrentWorkspace: vi.fn() }));
vi.mock("../context/membershipRoleSource", () => ({ useMembershipRoleSource: vi.fn() }));
vi.mock("../hooks/useMemberActions", () => ({ useMemberActions: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;

const WS_ID = 42;

const addMock = vi.fn<(...args: unknown[]) => Promise<void>>().mockResolvedValue(undefined);
const changeRoleMock = vi.fn<(...args: unknown[]) => Promise<void>>().mockResolvedValue(undefined);
const removeMock = vi.fn<(...args: unknown[]) => Promise<void>>().mockResolvedValue(undefined);

/** 세션: non-admin 인증(admin override 없음). */
function mockAuthenticatedNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** 세션: admin 인증(INV-3 admin override). */
function mockAuthenticatedAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

function ws(id: number): WorkspaceRead {
  return {
    id,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    name: "알파",
    is_shareable: false,
    trash_retention_days: 30,
  };
}

/** 현재 WS 컨텍스트 모킹(currentWorkspace 제공). */
function setWorkspace(current: WorkspaceRead | null): void {
  vi.mocked(useCurrentWorkspace).mockReturnValue({
    status: "ready",
    workspaces: current ? [current] : [],
    currentWorkspace: current,
    workspaceId: current ? String(current.id) : null,
    role: null, // D-1: 패널은 이 값을 사용하지 않는다(항상 하드코딩 null).
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
  } satisfies CurrentWorkspaceContextValue);
}

/** MembershipRoleSource.roleFor 반환값 제어(OWNER/EDITOR/VIEWER/null). */
function setRoleFor(role: Role | null): void {
  vi.mocked(useMembershipRoleSource).mockReturnValue({
    roleFor: () => role,
    recordOwner: vi.fn(),
    recordSelfRole: vi.fn(),
  });
}

/** useMemberActions 반환값 제어(members·error·pending). */
function setMemberActions(overrides: { members?: MemberRead[]; error?: ApiError | null } = {}): void {
  vi.mocked(useMemberActions).mockReturnValue({
    members: overrides.members ?? [],
    add: addMock,
    changeRole: changeRoleMock,
    remove: removeMock,
    pending: false,
    error: overrides.error ?? null,
  });
}

function member(userId: number, role: MemberRead["role"]): MemberRead {
  return { id: userId * 10, workspace_id: WS_ID, user_id: userId, role };
}

beforeEach(() => {
  useSessionMock.mockReset();
  addMock.mockClear();
  changeRoleMock.mockClear();
  removeMock.mockClear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MemberManagementPanel — owner 게이팅(실 RequireRole)·뮤테이션 결선(Req 3.x·7.x)", () => {
  it("non-admin + roleFor→OWNER → 패널 콘텐츠(추가 폼) 노출 (Req 3.5)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();

    render(<MemberManagementPanel />);

    expect(screen.getByLabelText("사용자 ID")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeInTheDocument();
  });

  it("non-admin + roleFor→VIEWER → 패널 은닉 (INV-2, Req 7.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.VIEWER);
    setMemberActions();

    const { container } = render(<MemberManagementPanel />);

    expect(screen.queryByLabelText("사용자 ID")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("non-admin + roleFor→EDITOR → 패널 은닉 (owner 미만, Req 7.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.EDITOR);
    setMemberActions();

    render(<MemberManagementPanel />);

    expect(screen.queryByLabelText("사용자 ID")).not.toBeInTheDocument();
  });

  it("admin 세션 + roleFor→null → 패널 노출 (admin override, INV-3, Req 7.3)", () => {
    mockAuthenticatedAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(null);
    setMemberActions();

    render(<MemberManagementPanel />);

    expect(screen.getByLabelText("사용자 ID")).toBeInTheDocument();
  });

  it("S1 열거 한계(전체 멤버 목록 아님)를 UI 에 명시한다 (Req 3.7)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();

    render(<MemberManagementPanel />);

    expect(screen.getByText(/전체 멤버 목록이 아닙니다/)).toBeInTheDocument();
  });

  it("추가할 역할 선택은 owner/editor/viewer 3값만 노출한다 (Req 3.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();

    render(<MemberManagementPanel />);

    const roleSelect = screen.getByLabelText("역할") as HTMLSelectElement;
    const options = within(roleSelect).getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((o) => o.value)).toEqual(["owner", "editor", "viewer"]);
  });

  it("추가 제출 시 현재 WS id 로 add(user_id·role) 를 호출한다 (Req 3.1)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();

    render(<MemberManagementPanel />);

    await userEvent.type(screen.getByLabelText("사용자 ID"), "7");
    await userEvent.selectOptions(screen.getByLabelText("역할"), "editor");
    await userEvent.click(screen.getByRole("button", { name: "멤버 추가" }));

    expect(addMock).toHaveBeenCalledTimes(1);
    expect(addMock).toHaveBeenCalledWith(WS_ID, { user_id: 7, role: "editor" });
  });

  it("멤버 role 변경 시 현재 WS id·user_id 로 changeRole 을 호출한다 (Req 3.1)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions({ members: [member(7, "viewer")] });

    render(<MemberManagementPanel />);

    await userEvent.selectOptions(screen.getByLabelText("사용자 7 역할"), "owner");

    expect(changeRoleMock).toHaveBeenCalledTimes(1);
    expect(changeRoleMock).toHaveBeenCalledWith(WS_ID, 7, { role: "owner" });
  });

  it("멤버 제거 시 현재 WS id·user_id 로 remove 를 호출한다 (Req 3.1)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions({ members: [member(7, "viewer")] });

    render(<MemberManagementPanel />);

    await userEvent.click(screen.getByRole("button", { name: "사용자 7 제거" }));

    expect(removeMock).toHaveBeenCalledTimes(1);
    expect(removeMock).toHaveBeenCalledWith(WS_ID, 7);
  });

  it("error 가 있으면(서버 403 포함) ErrorMessage(role=alert)로 항상 표시한다 (Req 7.5)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions({
      error: new ApiError({ status: 403, code: "forbidden", message: "권한이 없습니다." }),
    });

    render(<MemberManagementPanel />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("권한이 없습니다.");
  });
});
