/**
 * s24-role-persistence task 4.2 — 프론트 조립·시드 통합 및 배지·owner 패널 회귀.
 *
 * 이 파일은 **실제** provider 를 조립해(모킹하지 않음) 로드-시드가 배지·owner 게이팅을
 * 새로고침 후에도 복원하는지 통합 관점에서 검증한다. 단위 테스트(각 provider·컴포넌트)는
 * 이미 존재하며, 여기서는 그들을 **함께** 마운트했을 때의 계약을 못박는다:
 *
 * - 조립 순서: `CurrentWorkspaceProvider` (상위) → `MembershipRoleProvider` (하위). 이는 main.tsx
 *   실제 조립(`SessionProvider → CurrentWorkspaceProvider → composeProviders([MembershipRoleProvider])`)
 *   과 동형이며, MembershipRoleProvider 가 상위 CurrentWorkspaceContext 를 옵셔널로 읽어 시드한다.
 * - 시드-only 복원: in-session 기록(recordOwner/recordSelfRole) 없이 로드된 `workspaces[].role` 만으로
 *   roleFor·배지·owner 패널이 정확히 동작(Req 3.2·4.2·5.2).
 * - 마운트 순서 역전 회귀: MembershipRoleProvider 를 CurrentWorkspaceProvider **상위**로 뒤집으면
 *   옵셔널 읽기가 null → 시드 중단 → roleFor null·배지 "역할 미확인". 이 테스트가 실패하면 실제
 *   조립 순서가 뒤집혔다는 신호다(design.md Revalidation Triggers: 마운트 순서 규약).
 *
 * 실물: CurrentWorkspaceProvider, MembershipRoleProvider, CurrentWorkspaceIndicator,
 * MemberManagementPanel, RequireRole, useCurrentWorkspace, useMembershipRoleSource.
 * 모킹: apiClient(get) — 목록 응답 통제, useSession — 인증/admin 게이팅 통제, 그리고 owner 패널
 * 콘텐츠의 leaf 데이터 훅(useMemberActions·useAssignableUsers) — role 시드 경로와 무관하므로
 * 게이팅 관찰을 위해서만 최소 스텁한다.
 *
 * Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4.
 */

import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";

import { CurrentWorkspaceProvider } from "@/app/workspace-context/CurrentWorkspaceProvider";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { apiClient } from "@/shared/api/client";
import { useSession } from "@/app/session/useSession";
import { Role } from "@/shared/auth/roles";
import type { WorkspaceRead } from "@/shared/types/workspace";
import type { Page } from "@/shared/types/page";

import {
  MembershipRoleProvider,
  useMembershipRoleSource,
} from "./membershipRoleSource";
import { CurrentWorkspaceIndicator } from "../components/CurrentWorkspaceIndicator";
import { MemberManagementPanel } from "../components/MemberManagementPanel";
import { useMemberActions } from "../hooks/useMemberActions";
import { useAssignableUsers } from "../hooks/useAssignableUsers";

// 실제 HTTP 대신 목록 응답을 통제하고, 인증/admin 게이팅을 통제한다.
vi.mock("@/shared/api/client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
// owner 패널 콘텐츠의 leaf 데이터 훅(role 시드 경로와 무관) — 게이팅 관찰용 최소 스텁.
vi.mock("../hooks/useMemberActions", () => ({ useMemberActions: vi.fn() }));
vi.mock("../hooks/useAssignableUsers", () => ({ useAssignableUsers: vi.fn() }));

const getMock = apiClient.get as unknown as Mock;
const useSessionMock = useSession as unknown as Mock;
const useMemberActionsMock = useMemberActions as unknown as Mock;
const useAssignableUsersMock = useAssignableUsers as unknown as Mock;

/** WorkspaceRead 항목 빌더(role 포함/미포함 통제). */
function ws(id: number, role: WorkspaceRead["role"] = undefined): WorkspaceRead {
  return {
    id,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    name: `WS ${id}`,
    is_shareable: false,
    trash_retention_days: 30,
    ...(role !== undefined ? { role } : {}),
  };
}

function page(items: WorkspaceRead[]): Page<WorkspaceRead> {
  return { items, total: items.length };
}

/** 인증(non-admin) 세션. CurrentWorkspaceProvider 로드 게이팅 통과 + RequireRole admin=false. */
function mockNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** 인증(admin) 세션. RequireRole admin=true 세션 우회 경로 통제(INV-3). */
function mockAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** owner 패널 콘텐츠 leaf 훅의 기본 반환(빈 상태) — 게이트 통과 시 크래시 없이 렌더. */
function stubPanelLeaves(): void {
  useMemberActionsMock.mockReturnValue({
    members: [],
    add: vi.fn().mockResolvedValue(undefined),
    changeRole: vi.fn().mockResolvedValue(undefined),
    remove: vi.fn().mockResolvedValue(undefined),
    pending: false,
    error: null,
  });
  useAssignableUsersMock.mockReturnValue({
    status: "ready",
    users: [],
    total: 0,
    error: null,
    reload: vi.fn().mockResolvedValue(undefined),
  });
}

/**
 * 실제 조립(정방향): CurrentWorkspaceProvider(상위) → MembershipRoleProvider(하위).
 * MembershipRoleProvider 가 상위 CurrentWorkspaceContext 를 읽어 시드한다(main.tsx 동형).
 */
function Assembled({ children }: { children: ReactNode }): ReactElement {
  return (
    <CurrentWorkspaceProvider>
      <MembershipRoleProvider>{children}</MembershipRoleProvider>
    </CurrentWorkspaceProvider>
  );
}

/**
 * 마운트 순서 **역전**: MembershipRoleProvider(상위) → CurrentWorkspaceProvider(하위).
 * MembershipRoleProvider 의 옵셔널 CurrentWorkspaceContext 읽기가 null → 시드 중단.
 */
function ReversedAssembled({ children }: { children: ReactNode }): ReactElement {
  return (
    <MembershipRoleProvider>
      <CurrentWorkspaceProvider>{children}</CurrentWorkspaceProvider>
    </MembershipRoleProvider>
  );
}

/** roleFor(id) 를 노출하고 in-session 기록·refresh 를 트리거하는 프로브(두 컨텍스트 모두 소비). */
function RoleProbe({ ids }: { ids: number[] }): ReactElement {
  const source = useMembershipRoleSource();
  const wsCtx = useCurrentWorkspace();
  return (
    <div>
      <span data-testid="ws-status">{wsCtx.status}</span>
      {ids.map((id) => (
        <span key={id} data-testid={`role-${id}`}>
          {source.roleFor(id) === null ? "null" : String(source.roleFor(id))}
        </span>
      ))}
      <button type="button" onClick={() => source.recordOwner(99)}>
        record-owner-99
      </button>
      <button type="button" onClick={() => source.recordSelfRole(1, Role.VIEWER)}>
        record-self-1-viewer
      </button>
      <button type="button" onClick={() => void wsCtx.refresh()}>
        refresh
      </button>
    </div>
  );
}

beforeEach(() => {
  getMock.mockReset();
  useSessionMock.mockReset();
  useMemberActionsMock.mockReset();
  useAssignableUsersMock.mockReset();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("조립 시드: MembershipRoleProvider + CurrentWorkspaceProvider (Req 3.2·4.2·5.x)", () => {
  it("로드 후 roleFor 가 시드 role 을 반환하고 role=null 항목은 null 유지 — in-session 기록 없음 (Req 3.2·4.2·5.4·2.4)", async () => {
    mockNonAdmin();
    getMock.mockResolvedValue(page([ws(1, "owner"), ws(2, "editor"), ws(3, null)]));

    render(
      <Assembled>
        <RoleProbe ids={[1, 2, 3]} />
      </Assembled>,
    );

    // 로드-시드 정착 대기.
    await waitFor(() => expect(screen.getByTestId("ws-status")).toHaveTextContent("ready"));
    await waitFor(() =>
      expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.OWNER)),
    );
    // 시드-only 복원: 목록의 owner/editor 는 실제 role, role=null 항목은 null 유지(미시드).
    expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.OWNER));
    expect(screen.getByTestId("role-2")).toHaveTextContent(String(Role.EDITOR));
    expect(screen.getByTestId("role-3")).toHaveTextContent("null");
  });

  it("recordOwner(in-session) 후 목록 재조회로 서버값이 덮어써도 일관, 비목록 in-session 항목은 보존 (Req 5.1·5.2·5.3)", async () => {
    mockNonAdmin();
    // 1차 로드: id1=editor.
    getMock.mockResolvedValueOnce(page([ws(1, "editor"), ws(2, "viewer")]));

    render(
      <Assembled>
        <RoleProbe ids={[1, 2, 99]} />
      </Assembled>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.EDITOR)),
    );

    // in-session 기록: 목록에 없는 WS 99 를 owner 로, 목록에 있는 WS 1 을 viewer 로 기록.
    await userEvent.click(screen.getByRole("button", { name: "record-self-1-viewer" }));
    await userEvent.click(screen.getByRole("button", { name: "record-owner-99" }));
    expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.VIEWER));
    expect(screen.getByTestId("role-99")).toHaveTextContent(String(Role.OWNER));

    // 2차 로드(refresh): id1=owner. 서버 권위값이 in-session viewer 를 **덮어쓴다**(5.2).
    getMock.mockResolvedValueOnce(page([ws(1, "owner"), ws(2, "viewer")]));
    await userEvent.click(screen.getByRole("button", { name: "refresh" }));

    await waitFor(() =>
      expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.OWNER)),
    );
    // 목록에 없는 WS 99 의 in-session 기록은 재시드에도 보존된다(5.3).
    expect(screen.getByTestId("role-99")).toHaveTextContent(String(Role.OWNER));
    expect(screen.getByTestId("role-2")).toHaveTextContent(String(Role.VIEWER));
  });
});

describe("배지 회귀: CurrentWorkspaceIndicator in real assembly (Req 3.1·3.2·3.3)", () => {
  it("in-session 이력 없이 새로고침 시 배지가 실제 role(editor) 을 표시한다 (Req 3.1·3.2)", async () => {
    mockNonAdmin();
    getMock.mockResolvedValue(page([ws(1, "editor")]));

    render(
      <Assembled>
        <CurrentWorkspaceIndicator />
      </Assembled>,
    );

    await waitFor(() => expect(screen.getByText("editor")).toBeInTheDocument());
    expect(screen.queryByText("역할 미확인")).not.toBeInTheDocument();
  });

  it("현재 WS role 신호가 없으면(role=null) '역할 미확인' 을 유지한다 (Req 3.3)", async () => {
    mockNonAdmin();
    getMock.mockResolvedValue(page([ws(1, null)]));

    render(
      <Assembled>
        <CurrentWorkspaceIndicator />
      </Assembled>,
    );

    // 목록은 로드되되(현재 WS 이름 노출) role 신호는 부재 → 미확인.
    await waitFor(() => expect(screen.getByText("WS 1")).toBeInTheDocument());
    expect(screen.getByText("역할 미확인")).toBeInTheDocument();
    expect(screen.queryByText("owner")).not.toBeInTheDocument();
    expect(screen.queryByText("editor")).not.toBeInTheDocument();
    expect(screen.queryByText("viewer")).not.toBeInTheDocument();
  });
});

describe("owner 패널 회귀: MemberManagementPanel in real assembly (Req 4.1·4.2·4.3·4.4·5.4)", () => {
  it("non-admin owner 복원만으로 멤버 관리 패널이 노출된다 — in-session 없음 (Req 4.1·4.2)", async () => {
    mockNonAdmin();
    stubPanelLeaves();
    getMock.mockResolvedValue(page([ws(1, "owner")]));

    render(
      <Assembled>
        <MemberManagementPanel />
      </Assembled>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "멤버 추가" })).toBeInTheDocument(),
    );
  });

  it("non-admin editor 는 멤버 관리 패널이 차단된다 (Req 4.3)", async () => {
    mockNonAdmin();
    stubPanelLeaves();
    getMock.mockResolvedValue(page([ws(1, "editor")]));

    render(
      <Assembled>
        <RoleProbe ids={[1]} />
        <MemberManagementPanel />
      </Assembled>,
    );

    // 시드가 editor 로 정착했음을 확인한 뒤, 패널이 여전히 은닉인지 단언(게이팅 누수 회귀 방지).
    await waitFor(() =>
      expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.EDITOR)),
    );
    expect(screen.queryByRole("button", { name: "멤버 추가" })).not.toBeInTheDocument();
  });

  it("non-admin viewer 는 멤버 관리 패널이 차단된다 (Req 4.3)", async () => {
    mockNonAdmin();
    stubPanelLeaves();
    getMock.mockResolvedValue(page([ws(1, "viewer")]));

    render(
      <Assembled>
        <RoleProbe ids={[1]} />
        <MemberManagementPanel />
      </Assembled>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.VIEWER)),
    );
    expect(screen.queryByRole("button", { name: "멤버 추가" })).not.toBeInTheDocument();
  });

  it("admin 세션은 멤버십 role 이 viewer 여도 세션 경로로 패널 노출 — role 필드에 admin 미접합 (Req 4.4·5.4)", async () => {
    mockAdmin();
    stubPanelLeaves();
    // admin 이 멤버인 WS 의 멤버십 role 은 viewer(권위 있는 멤버십값). admin 상승은 role 에 담기지 않는다.
    getMock.mockResolvedValue(page([ws(1, "viewer")]));

    render(
      <Assembled>
        <RoleProbe ids={[1]} />
        <MemberManagementPanel />
      </Assembled>,
    );

    // 세션 우회로 패널은 노출된다.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "멤버 추가" })).toBeInTheDocument(),
    );
    // 그러나 role 신호 자체는 멤버십 role(viewer)만 담고 owner 로 상승되지 않는다(INV-3).
    // 패널 노출은 세션 우회(즉시)지만 role 신호는 시드 effect(커밋 후)로 채워지므로, 동기 읽기 대신
    // 시드 의존 신호를 waitFor 로 기다린다(부하 시 버튼 선노출→role 미시드 경합 방지).
    await waitFor(() =>
      expect(screen.getByTestId("role-1")).toHaveTextContent(String(Role.VIEWER)),
    );
    expect(screen.getByTestId("role-1")).not.toHaveTextContent(String(Role.OWNER));
  });
});

describe("마운트 순서 역전 회귀: 시드 중단 고정 (design Revalidation Triggers)", () => {
  it("MembershipRoleProvider 가 CurrentWorkspaceProvider 상위면 옵셔널 읽기 null → 시드 중단, roleFor null 유지", async () => {
    mockNonAdmin();
    // 목록은 owner role 을 담아 로드되지만, 역전 조립에서는 시드되지 않아야 한다.
    getMock.mockResolvedValue(page([ws(1, "owner")]));

    render(
      <ReversedAssembled>
        <RoleProbe ids={[1]} />
      </ReversedAssembled>,
    );

    // 목록 로드는 정상 정착(status ready)하지만 — 시드는 일어나지 않는다.
    await waitFor(() => expect(screen.getByTestId("ws-status")).toHaveTextContent("ready"));
    // 로드가 끝나도 roleFor 는 null: 마운트 순서 역전 → 시드 중단(회귀 포착 지점).
    expect(screen.getByTestId("role-1")).toHaveTextContent("null");
  });

  it("역전 조립에서는 배지가 실제 role 로드에도 '역할 미확인' 을 표시한다(시드 중단 회귀)", async () => {
    mockNonAdmin();
    getMock.mockResolvedValue(page([ws(1, "owner")]));

    render(
      <ReversedAssembled>
        <CurrentWorkspaceIndicator />
      </ReversedAssembled>,
    );

    // 현재 WS 이름은 로드되지만(status ready) role 시드 부재 → "역할 미확인".
    await waitFor(() => expect(screen.getByText("WS 1")).toBeInTheDocument());
    expect(screen.getByText("역할 미확인")).toBeInTheDocument();
    expect(screen.queryByText("owner")).not.toBeInTheDocument();
  });
});
