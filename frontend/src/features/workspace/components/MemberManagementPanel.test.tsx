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
    seedRoles: vi.fn(),
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

  it("추가한 멤버는 목록에 '{id} {name}' 으로 표시된다(배정 목록에서 이름 포착)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    // 추가 이후 확인된 멤버로 사용자 7 이 목록에 존재하는 상태를 재현(useMemberActions 는 모킹).
    setMemberActions({ members: [member(7, "editor")] });
    setAssignableUsers({ status: "ready", users: [assignable(7, "그레이스", "grace@example.com")] });

    render(<MemberManagementPanel />);

    // 이름 포착 전(직접 주입 상태)에는 방어적 폴백으로 "사용자 7" 이 보인다.
    expect(screen.getByText("사용자 7")).toBeInTheDocument();

    // 배정 목록에서 사용자 7 을 선택해 추가 → 이 시점의 이름("그레이스")이 포착된다.
    await userEvent.selectOptions(getUserSelect(), "7");
    await userEvent.click(screen.getByRole("button", { name: "멤버 추가" }));

    // 포착 이후에는 "{id} {name}" 형식으로 표시되고, role/제거 라벨도 동일 라벨을 따른다.
    expect(screen.getByText("7 그레이스")).toBeInTheDocument();
    expect(screen.queryByText("사용자 7")).not.toBeInTheDocument();
    expect(screen.getByLabelText("7 그레이스 역할")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "7 그레이스 제거" })).toBeInTheDocument();
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

  it("추가 성공 후 reload 로 목록이 갱신되면 추가된 사용자가 더는 선택지에 없다 (Req 3.1·3.4)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();

    // reload() 호출 시 배정 가능 목록이 줄어드는(추가 사용자 사라짐) 실동작을 재현하는 제어형 mock.
    // add→setState 재렌더 시점에 mock 이 갱신된 users 를 반환하도록 클로저 변수를 reload 가 변경한다.
    let assignableUsers: AssignableUser[] = [assignable(7, "그레이스", "grace@example.com")];
    const localReload = vi.fn(async () => {
      assignableUsers = [];
    });
    vi.mocked(useAssignableUsers).mockImplementation(() => ({
      status: "ready",
      users: assignableUsers,
      total: assignableUsers.length,
      error: null,
      reload: localReload,
    }));

    render(<MemberManagementPanel />);

    // 갱신 전에는 대상 사용자가 선택지에 존재한다.
    expect(screen.getByRole("option", { name: /그레이스/ })).toBeInTheDocument();

    await userEvent.selectOptions(getUserSelect(), "7");
    await userEvent.selectOptions(screen.getByLabelText("역할"), "owner");
    await userEvent.click(screen.getByRole("button", { name: "멤버 추가" }));

    expect(addMock).toHaveBeenCalledTimes(1);
    expect(addMock).toHaveBeenCalledWith(WS_ID, { user_id: 7, role: "owner" });
    expect(localReload).toHaveBeenCalledTimes(1);
    // reload 로 목록이 비면(추가 사용자 제외) 동일 사용자가 더는 선택지에 없고 빈 상태로 재평가된다(Req 3.4).
    expect(screen.queryByRole("option", { name: /그레이스/ })).not.toBeInTheDocument();
    expect(screen.getByText("배정 가능한 사용자가 없습니다")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeDisabled();
  });

  it("배정 가능 0명이면 EmptyState 안내 문구를 노출하고 추가를 비활성한다 (Req 3.5)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();
    setAssignableUsers({ status: "ready", users: [] });

    render(<MemberManagementPanel />);

    // AssignableUserSelect 의 empty 표면: EmptyState 문구 + select 부재.
    expect(screen.getByText("배정 가능한 사용자가 없습니다")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "사용자 선택" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeDisabled();
  });

  it("조회 로딩 중이면 Spinner 를 노출하고 선택·추가를 방지한다 (Req 3.6)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions();
    setAssignableUsers({ status: "loading", users: [] });

    render(<MemberManagementPanel />);

    // loading 표면: Spinner(role=status) 만 렌더되고 선택 <select> 는 존재하지 않는다(선택 불가).
    expect(screen.getByRole("status", { name: "배정 가능한 사용자 불러오는 중" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "사용자 선택" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeDisabled();
  });

  it("배정 가능 목록 조회 실패(403)는 AssignableUserSelect 오류 표면으로 표시된다 — 게이팅으로 억제하지 않음 (Req 4.1)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    setMemberActions(); // 뮤테이션 error 는 없음 → 유일한 alert 는 조회 오류 표면이어야 한다.
    setAssignableUsers({
      status: "error",
      users: [],
      error: new ApiError({ status: 403, code: "forbidden", message: "목록을 불러올 수 없습니다." }),
    });

    render(<MemberManagementPanel />);

    // 조회 실패는 assignable.error → AssignableUserSelect 의 ErrorMessage 로 인라인 표시.
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("목록을 불러올 수 없습니다.");
    expect(screen.queryByRole("option", { name: "사용자 선택" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "멤버 추가" })).toBeDisabled();
  });

  it("추가 실패 시 로컬 멤버 목록을 시도 이전과 동일하게 유지한다(비낙관·부분 반영 없음) (Req 4.2)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws(WS_ID));
    setRoleFor(Role.OWNER);
    // 시도 이전 확인된 멤버는 사용자 5 하나. add 는 409 로 실패(error 로 삼킴)하며 members 는 불변.
    setMemberActions({
      members: [member(5, "viewer")],
      error: new ApiError({ status: 409, code: "conflict", message: "이미 멤버입니다." }),
    });
    setAssignableUsers({ status: "ready", users: [assignable(9, "헨리")] });

    render(<MemberManagementPanel />);

    await userEvent.selectOptions(getUserSelect(), "9");
    await userEvent.click(screen.getByRole("button", { name: "멤버 추가" }));

    expect(addMock).toHaveBeenCalledWith(WS_ID, { user_id: 9, role: "viewer" });
    // 실패 후에도 패널은 스스로 멤버를 추가(낙관 반영)하지 않는다: 멤버 행은 mock 의 members 그대로.
    expect(screen.getByText("사용자 5")).toBeInTheDocument();
    expect(screen.queryByText("사용자 9")).not.toBeInTheDocument();
    // 그리고 실패 오류는 표시된다.
    expect(screen.getByRole("alert")).toHaveTextContent("이미 멤버입니다.");
  });
});
