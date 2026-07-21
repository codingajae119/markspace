import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WorkspaceSettingsPanel } from "./WorkspaceSettingsPanel";
import { Role } from "@/shared/auth/roles";
import { useSession } from "@/app/session/useSession";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { useWorkspaceActions } from "../hooks/useWorkspaceActions";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { WorkspaceRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// 진짜 RequireRole 게이트를 관통시키기 위해 게이트가 읽는 세션과 role 조달 leaf 만 모킹한다.
// RequireRole·ErrorMessage·Button 은 실물. 뮤테이션은 useWorkspaceActions 를 모킹해 결선을 관찰.
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({ useCurrentWorkspace: vi.fn() }));
vi.mock("../context/membershipRoleSource", () => ({ useMembershipRoleSource: vi.fn() }));
vi.mock("../hooks/useWorkspaceActions", () => ({ useWorkspaceActions: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;

const WS_ID = 42;

const updateMock = vi
  .fn<(...args: unknown[]) => Promise<WorkspaceRead | null>>()
  .mockResolvedValue(null);
const removeMock = vi.fn<(...args: unknown[]) => Promise<boolean>>().mockResolvedValue(true);

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

function ws(overrides: Partial<WorkspaceRead> = {}): WorkspaceRead {
  return {
    id: WS_ID,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    name: "알파",
    is_shareable: false,
    trash_retention_days: 30,
    ...overrides,
  };
}

/** 현재 WS 컨텍스트 모킹(currentWorkspace·isShareable 제공). */
function setWorkspace(current: WorkspaceRead | null): void {
  vi.mocked(useCurrentWorkspace).mockReturnValue({
    status: "ready",
    workspaces: current ? [current] : [],
    currentWorkspace: current,
    workspaceId: current ? String(current.id) : null,
    role: null, // D-1: 패널은 이 값을 사용하지 않는다(항상 하드코딩 null).
    isShareable: current ? current.is_shareable : false,
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

/** useWorkspaceActions 반환값 제어(error·saving). */
function setActions(overrides: { error?: ApiError | null } = {}): void {
  vi.mocked(useWorkspaceActions).mockReturnValue({
    create: vi.fn().mockResolvedValue(null),
    creating: false,
    update: updateMock,
    remove: removeMock,
    saving: false,
    error: overrides.error ?? null,
  });
}

beforeEach(() => {
  useSessionMock.mockReset();
  updateMock.mockClear().mockResolvedValue(null);
  removeMock.mockClear().mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WorkspaceSettingsPanel — owner 게이팅(실 RequireRole)·설정 뮤테이션 결선(Req 4.x·7.x)", () => {
  it("non-admin + roleFor→OWNER → 패널 콘텐츠(이름·is_shareable·삭제) 노출 (Req 4.5)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws());
    setRoleFor(Role.OWNER);
    setActions();

    render(<WorkspaceSettingsPanel />);

    expect(screen.getByLabelText("워크스페이스 이름")).toBeInTheDocument();
    expect(screen.getByLabelText("공유 허용 (is_shareable)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "워크스페이스 삭제" })).toBeInTheDocument();
  });

  it("non-admin + roleFor→MEMBER → 패널 은닉 (owner 미만, INV-2, Req 7.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws());
    setRoleFor(Role.MEMBER);
    setActions();

    const { container } = render(<WorkspaceSettingsPanel />);

    expect(screen.queryByLabelText("워크스페이스 이름")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("non-admin + roleFor→null(비멤버) → 패널 은닉 (owner 미만, Req 7.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws());
    setRoleFor(null);
    setActions();

    render(<WorkspaceSettingsPanel />);

    expect(screen.queryByLabelText("워크스페이스 이름")).not.toBeInTheDocument();
  });

  it("admin 세션 + roleFor→null → 패널 노출 (admin override, INV-3, Req 7.3)", () => {
    mockAuthenticatedAdmin();
    setWorkspace(ws());
    setRoleFor(null);
    setActions();

    render(<WorkspaceSettingsPanel />);

    expect(screen.getByLabelText("워크스페이스 이름")).toBeInTheDocument();
  });

  it("is_shareable 토글 시 update(id, {is_shareable}) 를 즉시 호출한다 (Req 4.2, 단독 소유)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws({ is_shareable: false }));
    setRoleFor(Role.OWNER);
    setActions();

    render(<WorkspaceSettingsPanel />);

    await userEvent.click(screen.getByLabelText("공유 허용 (is_shareable)"));

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(updateMock).toHaveBeenCalledWith(WS_ID, { is_shareable: true });
  });

  it("is_shareable 체크 상태는 현재 컨텍스트 값(isShareable)을 반영한다 (Req 4.2, 즉시 반영)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws({ is_shareable: true }));
    setRoleFor(Role.OWNER);
    setActions();

    render(<WorkspaceSettingsPanel />);

    expect(screen.getByLabelText("공유 허용 (is_shareable)")).toBeChecked();
  });

  it("이름 저장 시 update(id, {name}) 를 호출한다 (Req 4.1)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws({ name: "알파" }));
    setRoleFor(Role.OWNER);
    setActions();

    render(<WorkspaceSettingsPanel />);

    const nameInput = screen.getByLabelText("워크스페이스 이름");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "베타");
    await userEvent.click(screen.getByRole("button", { name: "이름 저장" }));

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(updateMock).toHaveBeenCalledWith(WS_ID, { name: "베타" });
  });

  it("보관 기간 저장 시 update(id, {trash_retention_days}) 를 호출한다 (Req 4.1)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws({ trash_retention_days: 30 }));
    setRoleFor(Role.OWNER);
    setActions();

    render(<WorkspaceSettingsPanel />);

    const input = screen.getByLabelText("휴지통 보관 기간(일)");
    await userEvent.clear(input);
    await userEvent.type(input, "14");
    await userEvent.click(screen.getByRole("button", { name: "보관 기간 저장" }));

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(updateMock).toHaveBeenCalledWith(WS_ID, { trash_retention_days: 14 });
  });

  it("보관 기간이 0(비양수)이면 요청 전에 막고 update 를 호출하지 않으며 클라이언트 오류를 표시한다 (Req 4.3, 클라 가드)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws({ trash_retention_days: 30 }));
    setRoleFor(Role.OWNER);
    setActions();

    render(<WorkspaceSettingsPanel />);

    const input = screen.getByLabelText("휴지통 보관 기간(일)");
    await userEvent.clear(input);
    await userEvent.type(input, "0");
    await userEvent.click(screen.getByRole("button", { name: "보관 기간 저장" }));

    expect(updateMock).not.toHaveBeenCalled();
    expect(screen.getByText(/양의 정수/)).toBeInTheDocument();
  });

  it("서버 422(retention 검증 실패)는 ErrorMessage 로 표시한다 (Req 4.3, 서버 422 표면화)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws());
    setRoleFor(Role.OWNER);
    setActions({
      error: new ApiError({
        status: 422,
        code: "validation_error",
        message: "보관 기간이 올바르지 않습니다.",
      }),
    });

    render(<WorkspaceSettingsPanel />);

    expect(screen.getByRole("alert")).toHaveTextContent("보관 기간이 올바르지 않습니다.");
  });

  it("삭제 요청 시 remove(id) 를 호출한다 (Req 4.4)", async () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws());
    setRoleFor(Role.OWNER);
    setActions();

    render(<WorkspaceSettingsPanel />);

    await userEvent.click(screen.getByRole("button", { name: "워크스페이스 삭제" }));

    expect(removeMock).toHaveBeenCalledTimes(1);
    expect(removeMock).toHaveBeenCalledWith(WS_ID);
  });

  it("비-empty 삭제 409(conflict) 시 '빈 워크스페이스만 삭제 가능' 안내를 표시한다 (Req 4.4)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws());
    setRoleFor(Role.OWNER);
    setActions({
      error: new ApiError({ status: 409, code: "conflict", message: "비어 있지 않습니다." }),
    });

    render(<WorkspaceSettingsPanel />);

    expect(screen.getByText(/빈 워크스페이스만 삭제/)).toBeInTheDocument();
  });

  it("서버 403(권한) 오류는 게이팅과 무관하게 항상 ErrorMessage 로 표시한다 (Req 4.6, 7.5)", () => {
    mockAuthenticatedNonAdmin();
    setWorkspace(ws());
    setRoleFor(Role.OWNER);
    setActions({
      error: new ApiError({ status: 403, code: "forbidden", message: "권한이 없습니다." }),
    });

    render(<WorkspaceSettingsPanel />);

    expect(screen.getByRole("alert")).toHaveTextContent("권한이 없습니다.");
  });
});
