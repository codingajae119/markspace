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
import { useAssignableUsers } from "../hooks/useAssignableUsers";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { AssignableUser, MemberRead, WorkspaceRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// 진짜 RequireRole 게이트를 관통시키기 위해 게이트가 읽는 세션과 role 조달 leaf 만 모킹한다.
// RequireRole 자체는 모킹하지 않는다(게이트 의미를 실제로 검증). RoleSelect·ErrorMessage 도 실물.
// AssignableUserSelect 도 실물(선택 UI 결선을 실제로 검증) — 데이터 소스인 useAssignableUsers 만 모킹.
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({ useCurrentWorkspace: vi.fn() }));
vi.mock("../context/membershipRoleSource", () => ({ useMembershipRoleSource: vi.fn() }));
vi.mock("../hooks/useMemberActions", () => ({ useMemberActions: vi.fn() }));
vi.mock("../hooks/useAssignableUsers", () => ({ useAssignableUsers: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;

const WS_ID = 42;

const addMock = vi.fn<(...args: unknown[]) => Promise<void>>().mockResolvedValue(undefined);
const changeRoleMock = vi.fn<(...args: unknown[]) => Promise<void>>().mockResolvedValue(undefined);
const removeMock = vi.fn<(...args: unknown[]) => Promise<void>>().mockResolvedValue(undefined);
const reloadMock = vi.fn<(...args: unknown[]) => Promise<void>>().mockResolvedValue(undefined);

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

/** useAssignableUsers 반환값 제어(status·users·error). reload 는 공용 reloadMock. */
function setAssignableUsers(
  overrides: { status?: "loading" | "ready" | "error"; users?: AssignableUser[]; error?: ApiError | null } = {},
): void {
  const users = overrides.users ?? [];
  vi.mocked(useAssignableUsers).mockReturnValue({
    status: overrides.status ?? "ready",
    users,
    total: users.length,
    error: overrides.error ?? null,
    reload: reloadMock,
  });
}

function member(userId: number, role: MemberRead["role"]): MemberRead {
  return { id: userId * 10, workspace_id: WS_ID, user_id: userId, role };
}

function assignable(id: number, name: string, email: string | null = null): AssignableUser {
  return { id, name, email };
}

/** 실물 AssignableUserSelect 가 렌더한 사용자 선택 <select>(placeholder 옵션으로 특정). */
function getUserSelect(): HTMLSelectElement {
  return screen.getByRole("option", { name: "사용자 선택" }).closest("select") as HTMLSelectElement;
}

beforeEach(() => {
  useSessionMock.mockReset();
  addMock.mockClear();
  changeRoleMock.mockClear();
  removeMock.mockClear();
  reloadMock.mockClear();
  // 렌더하는 테스트가 공통으로 의존하는 기본 조회 상태(ready·빈 목록). 필요 시 각 테스트가 재설정.
  setAssignableUsers();
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

    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeInTheDocument();
  });

  it("non-admin + roleFor→VIEWER → 패널 은닉 (INV-2, Req 7.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.VIEWER);
    setMemberActions();

    const { container } = render(<MemberManagementPanel />);

    expect(screen.queryByRole("button", { name: "멤버 추가" })).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("non-admin + roleFor→EDITOR → 패널 은닉 (owner 미만, Req 7.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.EDITOR);
    setMemberActions();

    render(<MemberManagementPanel />);

    expect(screen.queryByRole("button", { name: "멤버 추가" })).not.toBeInTheDocument();
  });

  it("admin 세션 + roleFor→null → 패널 노출 (admin override, INV-3, Req 7.3)", () => {
    mockAuthenticatedAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(null);
    setMemberActions();

    render(<MemberManagementPanel />);

    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeInTheDocument();
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

  it("사용자 선택 + 역할 선택 후 추가 → 선택된 user_id·role 로 add 호출, 이후 reload (Req 3.2·3.3·4.3)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();
    setAssignableUsers({ status: "ready", users: [assignable(7, "그레이스", "grace@example.com")] });

    render(<MemberManagementPanel />);

    await userEvent.selectOptions(getUserSelect(), "7");
    await userEvent.selectOptions(screen.getByLabelText("역할"), "editor");
    await userEvent.click(screen.getByRole("button", { name: "멤버 추가" }));

    expect(addMock).toHaveBeenCalledTimes(1);
    expect(addMock).toHaveBeenCalledWith(WS_ID, { user_id: 7, role: "editor" });
    // 단일 경로: 추가 시도 완료 후 항상 reload.
    expect(reloadMock).toHaveBeenCalledTimes(1);
  });

  it("추가 실패(단일 경로)에도 reload 를 호출한다 — add 는 항상 void resolve (Req 4.2·4.3)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    // add 가 실패를 error 로 삼켜 void resolve 하는 계약을 재현(그래도 reload 호출돼야 함).
    setMemberActions({ error: new ApiError({ status: 409, code: "conflict", message: "이미 멤버입니다." }) });
    setAssignableUsers({ status: "ready", users: [assignable(9, "헨리")] });

    render(<MemberManagementPanel />);

    await userEvent.selectOptions(getUserSelect(), "9");
    await userEvent.click(screen.getByRole("button", { name: "멤버 추가" }));

    expect(addMock).toHaveBeenCalledWith(WS_ID, { user_id: 9, role: "viewer" });
    expect(reloadMock).toHaveBeenCalledTimes(1);
    // 조회 실패가 아닌 뮤테이션 실패는 useMemberActions.error → ErrorMessage 로 표시.
    expect(screen.getByRole("alert")).toHaveTextContent("이미 멤버입니다.");
  });

  it("사용자 미선택이면 추가 버튼 비활성(선택 전) (Req 3.2)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();
    setAssignableUsers({ status: "ready", users: [assignable(7, "그레이스")] });

    render(<MemberManagementPanel />);

    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeDisabled();
  });

  it("조회 로딩 중이면 추가 버튼 비활성 (Req 3.6)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();
    setAssignableUsers({ status: "loading", users: [] });

    render(<MemberManagementPanel />);

    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeDisabled();
  });

  it("배정 가능 0명이면 추가 버튼 비활성 (Req 3.5)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();
    setAssignableUsers({ status: "ready", users: [] });

    render(<MemberManagementPanel />);

    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeDisabled();
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
