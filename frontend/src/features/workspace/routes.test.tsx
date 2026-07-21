import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import type { ReactElement } from "react";
import { MemoryRouter, useRoutes } from "react-router-dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import {
  workspaceRoutes,
  WORKSPACE_PATH,
  ADMIN_CONSOLE_PATH,
} from "./routes";
import { AdminConsolePage } from "./admin/AdminConsolePage";
import { MembershipRoleProvider } from "./context/membershipRoleSource";
import { createAppRoutes } from "@/app/router";
import { collectRoutesByScope } from "@/app/routeModule";
import { useSession } from "@/app/session/useSession";
import type { SessionContextValue, SessionState } from "@/app/session/SessionProvider";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { WorkspaceRead } from "./api/types";

// s18 등록 결선 통합 테스트: workspaceRoutes(보호 슬롯 RouteModule[])가 s16 실제 compose 경로
// (collectRoutesByScope → createAppRoutes)로 취합되어 워크스페이스 관리 화면과 admin 서브트리를
// 보호 프레임 하위에 결선함을 관찰한다. 세션·현재 WS 훅만 모킹하고(렌더 시점 fetch 없음), admin
// 패널의 마운트 fetch 를 막기 위해 apiClient 는 no-op 로 모킹한다.
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));
// admin 콘솔 하위 패널(AdminUserPanel)이 마운트 시 adminApi.listUsers()로 fetch 하므로 apiClient
// 를 no-op 로 모킹해 jsdom 네트워크 호출을 회피한다(라우팅 결선만 검증).
vi.mock("@/shared/api/client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    post: vi.fn().mockResolvedValue(undefined),
    patch: vi.fn().mockResolvedValue(undefined),
    del: vi.fn().mockResolvedValue(undefined),
  },
}));

const useSessionMock = useSession as unknown as Mock;
const useCurrentWorkspaceMock = useCurrentWorkspace as unknown as Mock;

const workspaceFixture: WorkspaceRead = {
  id: 7,
  created_at: "2026-07-19T00:00:00Z",
  updated_at: null,
  name: "Acme",
  is_shareable: false,
  trash_retention_days: 30,
};

/** 세션 훅 반환값을 고정한다(refresh 는 계약상 항상 노출되므로 no-op 로 채운다). */
function setSession(state: SessionState): void {
  useSessionMock.mockReturnValue({ ...state, refresh: vi.fn() } as SessionContextValue);
}

/** 현재 WS 컨텍스트를 ready 상태로 고정한다(목록·현재 WS 표시용). role 은 s16 계약대로 항상 null. */
function setReadyWorkspace(): void {
  useCurrentWorkspaceMock.mockReturnValue({
    status: "ready",
    workspaces: [workspaceFixture],
    currentWorkspace: workspaceFixture,
    workspaceId: String(workspaceFixture.id),
    role: null,
    isShareable: workspaceFixture.is_shareable,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
  } as CurrentWorkspaceContextValue);
}

/** 현재 WS 컨텍스트를 "선택된 WS 없음"(empty) 상태로 고정한다(빈 상태 안내 검증용). */
function setNoWorkspace(): void {
  useCurrentWorkspaceMock.mockReturnValue({
    status: "empty",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: null,
    role: null,
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
  } as CurrentWorkspaceContextValue);
}

/** workspaceRoutes 를 s16 실제 compose 경로로 취합·프레임에 주입하고 role 소스 provider 로 감싼다. */
function RoutesView(): ReactElement | null {
  return useRoutes(createAppRoutes(collectRoutesByScope(workspaceRoutes)));
}

/** workspaceRoutes 로 결선한 프레임을 지정 진입 경로로 마운트한다(role 소스 provider 포함). */
function renderAt(initialEntries: string[]): void {
  render(
    <MemoryRouter initialEntries={initialEntries}>
      <MembershipRoleProvider>
        <RoutesView />
      </MembershipRoleProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useSessionMock.mockReset();
  useCurrentWorkspaceMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("workspaceRoutes 등록 결선 (보호 슬롯 워크스페이스 화면 + admin 서브트리)", () => {
  it("workspaceRoutes 는 보호 슬롯 RouteModule[] 이며 워크스페이스·admin 상대 경로를 노출한다 (Req 8.3, 8.5)", () => {
    // 모든 모듈은 유효한 RouteModule 형태(scope + routes 배열)여야 한다.
    for (const module of workspaceRoutes) {
      expect(["protected", "guest"]).toContain(module.scope);
      expect(Array.isArray(module.routes)).toBe(true);
    }

    const guarded = workspaceRoutes.find((module) => module.scope === "protected");
    expect(guarded).toBeDefined();

    const paths = guarded?.routes.map((route) => route.path) ?? [];
    // 보호 슬롯은 pathless 레이아웃 자식이라 상대 경로로 등록된다(절대 경로는 상수로 노출).
    expect(paths).toContain("workspace");
    expect(paths).toContain("admin");
    expect(WORKSPACE_PATH).toBe("/workspace");
    expect(ADMIN_CONSOLE_PATH).toBe("/admin");

    // 게스트 슬롯은 도입하지 않는다(워크스페이스·admin 모두 보호 대상).
    expect(workspaceRoutes.find((module) => module.scope === "guest")).toBeUndefined();
  });

  it("admin 라우트의 element 는 AdminConsolePage(자체 RequireAdmin 게이트) 다 (Req 8.5)", () => {
    const guarded = workspaceRoutes.find((module) => module.scope === "protected");
    const adminRoute = guarded?.routes.find((route) => route.path === "admin");
    expect(adminRoute).toBeDefined();
    // 라우트 대상은 self-gating AdminConsolePage 여야 한다 → admin 접근은 오직 RequireAdmin 경유.
    expect((adminRoute?.element as ReactElement).type).toBe(AdminConsolePage);
  });

  it("인증 + /workspace → 보호 프레임 하위에 워크스페이스 관리 화면이 렌더된다 (Req 8.3)", () => {
    setSession({
      status: "authenticated",
      user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
      settings: null,
    });
    setReadyWorkspace();

    renderAt([WORKSPACE_PATH]);

    // WorkspaceSwitcher(현재 WS 표시) + CreateWorkspaceDialog(이름 입력·생성)가 보호 프레임 안에 렌더된다.
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Acme" })).toBeInTheDocument();
    expect(screen.getByLabelText("워크스페이스 이름")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "워크스페이스 생성" })).toBeInTheDocument();
    // owner 패널은 role 소스가 owner 를 조달하지 않아(비-owner) 은닉된다(RequireRole 단일 소스).
    expect(screen.queryByRole("heading", { name: "워크스페이스 설정" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "멤버 관리" })).not.toBeInTheDocument();
  });

  it("admin 인증 + WS 미선택 → '선택된 워크스페이스가 없습니다' 안내가 페이지 단위로 정확히 1번만 렌더된다 (중복 제거)", () => {
    setSession({
      status: "authenticated",
      user: { id: 1, login_id: "root", name: "Root", email: null, is_admin: true },
      settings: null,
    });
    setNoWorkspace();

    renderAt([WORKSPACE_PATH]);

    // 과거엔 멤버/설정 두 패널이 각자 같은 문구를 렌더해 admin override 진입 시 2번 노출됐다.
    // 이제 페이지가 단일 소유하므로 정확히 1개만 존재한다.
    expect(screen.getAllByText("선택된 워크스페이스가 없습니다. 워크스페이스를 생성하거나 선택하세요."))
      .toHaveLength(1);
    // 대상 WS 가 없으므로 owner 패널 자체(멤버/설정 heading)는 마운트되지 않는다.
    expect(screen.queryByRole("heading", { name: "멤버 관리" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "워크스페이스 설정" })).not.toBeInTheDocument();
  });

  it("비-admin·비-owner 인증 + WS 미선택 → 빈 상태 안내는 은닉된다 (기존 동작 보존)", () => {
    setSession({
      status: "authenticated",
      user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
      settings: null,
    });
    setNoWorkspace();

    renderAt([WORKSPACE_PATH]);

    // owner 패널 접근권이 없는 사용자에게는(RequireRole 미통과) 안내를 노출하지 않는다.
    expect(screen.queryByText(/선택된 워크스페이스가 없습니다/)).not.toBeInTheDocument();
    // 생성 폼은 접근권과 무관하게 항상 노출된다(신규 사용자가 WS 를 만들 수 있어야 함).
    expect(screen.getByRole("button", { name: "워크스페이스 생성" })).toBeInTheDocument();
  });

  it("비-admin 인증 + /admin → RequireAdmin 이 admin 콘솔을 차단한다 (Req 8.5)", () => {
    setSession({
      status: "authenticated",
      user: { id: 1, login_id: "bob", name: "Bob", email: null, is_admin: false },
      settings: null,
    });
    setReadyWorkspace();

    renderAt([ADMIN_CONSOLE_PATH]);

    // 보호 프레임은 통과하지만 AdminConsolePage 의 RequireAdmin 이 비-admin 세션을 차단한다.
    expect(screen.queryByRole("heading", { name: "관리자 콘솔" })).not.toBeInTheDocument();
  });

  it("admin 인증 + /admin → RequireAdmin 통과로 admin 콘솔이 렌더된다 (Req 8.5)", async () => {
    setSession({
      status: "authenticated",
      user: { id: 1, login_id: "root", name: "Root", email: null, is_admin: true },
      settings: null,
    });
    setReadyWorkspace();

    renderAt([ADMIN_CONSOLE_PATH]);

    // admin 세션에서만 콘솔 셸(관리자 콘솔 heading)이 노출된다. 하위 AdminUserPanel 이 마운트 시
    // adminApi 로드(no-op mock)를 완료하며 발생하는 상태 갱신을 waitFor 로 흡수한다.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "관리자 콘솔" })).toBeInTheDocument(),
    );
  });
});
