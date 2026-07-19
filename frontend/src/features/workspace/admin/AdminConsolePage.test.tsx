import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { AdminConsolePage } from "./AdminConsolePage";
import { adminApi } from "../api/adminApi";
import { useSession } from "@/app/session/useSession";

// admin 게이팅은 실제 s16 `RequireAdmin` 이 수행한다(재구현/모킹 금지). RequireAdmin 은 판정을
// useSession() 의 is_admin(INV-3)으로만 하므로 세션 훅을 모킹해 상태를 주입한다.
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
// AdminUserPanel 이 마운트 시 listUsers() 를 호출하므로 어댑터를 모킹한다(네트워크 격리).
vi.mock("../api/adminApi", () => ({
  adminApi: {
    listUsers: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    resetPassword: vi.fn(),
    changeOwner: vi.fn(),
  },
}));

const useSessionMock = useSession as unknown as Mock;

/** useSession 이 admin authenticated 를 반환하도록 설정(INV-3 admin). */
function mockAuthenticatedAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 non-admin authenticated 를 반환하도록 설정. */
function mockAuthenticatedNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 unauthenticated 를 반환하도록 설정(is_admin 취득 불가 → 거부). */
function mockUnauthenticated(): void {
  useSessionMock.mockReturnValue({ status: "unauthenticated", refresh: vi.fn() });
}

beforeEach(() => {
  useSessionMock.mockReset();
  vi.mocked(adminApi.listUsers).mockReset();
  // AdminUserPanel 마운트 시 목록 로드가 성공하도록 빈 페이지를 반환한다.
  vi.mocked(adminApi.listUsers).mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  cleanup();
});

describe("AdminConsolePage — s16 RequireAdmin 하위 라우트 셸(admin 세션 게이팅, INV-3)", () => {
  it("authenticated + is_admin=true → 사용자 콘솔·소유권 변경 패널이 게이트 하위에 렌더된다", async () => {
    mockAuthenticatedAdmin();
    render(<AdminConsolePage />);

    // AdminUserPanel 마커: 목록 로드 후 "사용자 콘솔" 헤딩 노출.
    expect(await screen.findByRole("heading", { name: "사용자 콘솔" })).toBeInTheDocument();
    // AdminOwnerChangePanel 마커: "워크스페이스 소유권 변경" 헤딩.
    expect(
      screen.getByRole("heading", { name: "워크스페이스 소유권 변경" }),
    ).toBeInTheDocument();
  });

  it("authenticated + is_admin=false → RequireAdmin 이 차단(콘솔 미렌더)", async () => {
    mockAuthenticatedNonAdmin();
    render(<AdminConsolePage />);

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "사용자 콘솔" })).not.toBeInTheDocument();
    });
    expect(
      screen.queryByRole("heading", { name: "워크스페이스 소유권 변경" }),
    ).not.toBeInTheDocument();
    // 게이트가 차단하므로 하위 패널이 마운트되지 않아 목록 로드도 호출되지 않는다.
    expect(vi.mocked(adminApi.listUsers)).not.toHaveBeenCalled();
  });

  it("unauthenticated → RequireAdmin 이 차단(콘솔 미렌더)", async () => {
    mockUnauthenticated();
    render(<AdminConsolePage />);

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "사용자 콘솔" })).not.toBeInTheDocument();
    });
    expect(
      screen.queryByRole("heading", { name: "워크스페이스 소유권 변경" }),
    ).not.toBeInTheDocument();
    expect(vi.mocked(adminApi.listUsers)).not.toHaveBeenCalled();
  });
});
