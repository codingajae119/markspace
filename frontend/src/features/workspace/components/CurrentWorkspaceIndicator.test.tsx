import { describe, it, expect, afterEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import { Role } from "@/shared/auth/roles";
import { CurrentWorkspaceContext } from "@/app/workspace-context/CurrentWorkspaceProvider";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import type { WorkspaceRead } from "@/shared/types/workspace";

/**
 * CurrentWorkspaceIndicator 표시 테스트: 전역 헤더가 현재 WS 이름과 내 역할(owner/member)을
 * 항상 노출하는지, 선택 부재·역할 미확정·provider 부재를 정직하게 처리하는지 관찰한다.
 *
 * role 은 s18 MembershipRoleSource(best-effort)에서 오므로 옵셔널 접근자를 모킹해 roleFor 반환을
 * 제어하고, 현재 WS 는 s16 CurrentWorkspaceContext 를 직접 provider 로 주입해 status·선택을 고정한다.
 */

vi.mock("../context/membershipRoleSource", () => ({
  useMembershipRoleSourceOptional: vi.fn(),
}));

import { useMembershipRoleSourceOptional } from "../context/membershipRoleSource";
import { CurrentWorkspaceIndicator } from "./CurrentWorkspaceIndicator";

const roleSourceMock = useMembershipRoleSourceOptional as unknown as Mock;

/** roleFor 만 제어하는 최소 role 소스 스텁. */
function stubRoleSource(role: Role | null): void {
  roleSourceMock.mockReturnValue({
    roleFor: () => role,
    recordOwner: vi.fn(),
    recordSelfRole: vi.fn(),
  });
}

/** 최소 WorkspaceRead. 표시에 쓰는 id·name 만 의미가 있다. */
function workspace(id: number, name: string): WorkspaceRead {
  return {
    id,
    name,
    is_shareable: false,
    trash_retention_days: 30,
    created_at: "2026-07-21T00:00:00Z",
    updated_at: "2026-07-21T00:00:00Z",
  } as WorkspaceRead;
}

/** 지정 status·현재 WS 로 CurrentWorkspaceContext 를 주입한다. */
function withWorkspaceCtx(
  status: CurrentWorkspaceContextValue["status"],
  current: WorkspaceRead | null,
): (props: { children: ReactNode }) => ReactElement {
  const value: CurrentWorkspaceContextValue = {
    status,
    workspaces: current ? [current] : [],
    currentWorkspace: current,
    workspaceId: current ? String(current.id) : null,
    role: null,
    isShareable: false,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
  };
  return ({ children }) => (
    <CurrentWorkspaceContext.Provider value={value}>{children}</CurrentWorkspaceContext.Provider>
  );
}

afterEach(() => {
  cleanup();
  roleSourceMock.mockReset();
});

describe("CurrentWorkspaceIndicator", () => {
  it("현재 WS 이름과 owner 역할 배지를 표시한다(생성자=owner 신호)", () => {
    stubRoleSource(Role.OWNER);
    const Wrapper = withWorkspaceCtx("ready", workspace(1, "test1"));

    render(<CurrentWorkspaceIndicator />, { wrapper: Wrapper });

    expect(screen.getByText("test1")).toBeInTheDocument();
    expect(screen.getByText("owner")).toBeInTheDocument();
    expect(
      screen.getByLabelText("현재 워크스페이스: test1, 역할: owner"),
    ).toBeInTheDocument();
  });

  it("member 역할도 라벨로 표시한다", () => {
    stubRoleSource(Role.MEMBER);
    render(<CurrentWorkspaceIndicator />, {
      wrapper: withWorkspaceCtx("ready", workspace(2, "test2")),
    });
    expect(screen.getByText("member")).toBeInTheDocument();
  });

  it("멤버십 role 이 없으면(비멤버) 'viewer' 로 표시한다", () => {
    stubRoleSource(null);
    render(<CurrentWorkspaceIndicator />, {
      wrapper: withWorkspaceCtx("ready", workspace(1, "test1")),
    });

    expect(screen.getByText("test1")).toBeInTheDocument();
    expect(screen.getByText("viewer")).toBeInTheDocument();
    expect(screen.queryByText("역할 미확인")).not.toBeInTheDocument();
  });

  it("선택된 WS 가 없으면 '워크스페이스 미선택'을 명시한다(empty status)", () => {
    stubRoleSource(null);
    render(<CurrentWorkspaceIndicator />, {
      wrapper: withWorkspaceCtx("empty", null),
    });

    expect(screen.getByText("워크스페이스 미선택")).toBeInTheDocument();
  });

  it("목록 로드 중(loading)에는 표시를 보류한다(깜빡임 방지)", () => {
    stubRoleSource(null);
    const { container } = render(<CurrentWorkspaceIndicator />, {
      wrapper: withWorkspaceCtx("loading", null),
    });

    expect(container).toBeEmptyDOMElement();
  });

  it("CurrentWorkspaceProvider 밖에서는 아무것도 렌더하지 않는다(null-safe)", () => {
    stubRoleSource(Role.OWNER);
    const { container } = render(<CurrentWorkspaceIndicator />);

    expect(container).toBeEmptyDOMElement();
  });
});
