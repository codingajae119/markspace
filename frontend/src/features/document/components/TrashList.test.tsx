import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, fireEvent, within } from "@testing-library/react";

import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";
import { useSession } from "@/app/session/useSession";
import type { TrashBundleRead } from "../types";
import type { UseTrashResult } from "../hooks/useTrash";
import { useTrash } from "../hooks/useTrash";
import { TrashList } from "./TrashList";

// TrashList 는 휴지통 화면 전체를 RequireRole(minimum=MEMBER)로 게이팅한다(Req 8.6). 게이트
// 통과 시에만 내부 body 가 useTrash 를 호출해 목록/복구/완전삭제를 렌더한다(Req 8.1·8.5).
// RequireRole 은 isAdmin 을 useSession() 에서만 취득하므로(admin override) 세션 훅을 모킹하고,
// 목록 상태를 관찰하기 위해 useTrash 훅을 모킹해 제어 가능한 가짜 상태를 주입한다.
// Requirements: 8.1, 8.5, 8.6, 8.7

vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("../hooks/useTrash", () => ({ useTrash: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;
const useTrashMock = useTrash as unknown as Mock;

/** useSession 이 non-admin authenticated 를 반환하도록 설정(admin override 미적용). */
function mockNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 admin authenticated 를 반환하도록 설정(INV-3 admin override). */
function mockAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** 제어 가능한 가짜 useTrash 결과(status/bundles/total/error + 변이 vi.fn). */
function mockTrash(partial: Partial<UseTrashResult> = {}): UseTrashResult {
  const state: UseTrashResult = {
    status: "ready",
    bundles: [],
    total: 0,
    error: null,
    reload: vi.fn().mockResolvedValue(undefined),
    restore: vi.fn().mockResolvedValue(true),
    purge: vi.fn().mockResolvedValue(true),
    loadPage: vi.fn().mockResolvedValue(undefined),
    ...partial,
  };
  useTrashMock.mockReturnValue(state);
  return state;
}

/** TrashBundleRead 샘플. */
function sampleBundle(partial: Partial<TrashBundleRead> = {}): TrashBundleRead {
  return {
    bundle_id: 42,
    root_document_id: 42,
    root_title: "프로젝트 계획",
    workspace_id: 7,
    trashed_at: "2026-07-01T09:00:00Z",
    expires_at: "2026-07-31T09:00:00Z",
    member_count: 1,
    members: [{ id: 42, parent_id: null, title: "프로젝트 계획" }],
    ...partial,
  };
}

beforeEach(() => {
  useSessionMock.mockReset();
  useTrashMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("TrashList — 화면 전체 RequireRole(MEMBER) 게이팅", () => {
  it("비멤버(null, non-admin) → 휴지통 화면 미노출·useTrash body 미실행 (Req 8.6)", () => {
    mockNonAdmin();
    mockTrash({ bundles: [sampleBundle()] });

    render(<TrashList workspaceId="7" currentRole={null} />);

    // 게이팅된 콘텐츠(제목·묶음) 미노출
    expect(screen.queryByRole("heading", { name: /휴지통/ })).not.toBeInTheDocument();
    expect(screen.queryByText("프로젝트 계획")).not.toBeInTheDocument();
    // body 가 렌더되지 않았으므로 useTrash 훅도 호출되지 않는다(비멤버는 트래시 로드 미유발).
    expect(useTrashMock).not.toHaveBeenCalled();
  });

  it("member + loading → Spinner 노출 (Req 8.1)", () => {
    mockNonAdmin();
    mockTrash({ status: "loading" });

    render(<TrashList workspaceId="7" currentRole={Role.MEMBER} />);

    expect(useTrashMock).toHaveBeenCalledWith("7");
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("member + ready(2 bundles) → TrashBundleItem 2행 렌더 (Req 8.1)", () => {
    mockNonAdmin();
    mockTrash({
      status: "ready",
      total: 2,
      bundles: [
        sampleBundle({ bundle_id: 1, root_title: "묶음 A" }),
        sampleBundle({ bundle_id: 2, root_title: "묶음 B" }),
      ],
    });

    render(<TrashList workspaceId="7" currentRole={Role.MEMBER} />);

    expect(screen.getByRole("heading", { name: "묶음 A" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "묶음 B" })).toBeInTheDocument();
  });

  it("member + ready(empty) → EmptyState 노출 (Req 8.1)", () => {
    mockNonAdmin();
    mockTrash({ status: "ready", bundles: [], total: 0 });

    render(<TrashList workspaceId="7" currentRole={Role.MEMBER} />);

    expect(screen.getByText(/비어 있/)).toBeInTheDocument();
  });

  it("member + error → ErrorMessage 노출 (Req 8.1)", () => {
    mockNonAdmin();
    mockTrash({
      status: "error",
      error: new ApiError({ status: 403, code: "forbidden", message: "권한이 없습니다." }),
    });

    render(<TrashList workspaceId="7" currentRole={Role.MEMBER} />);

    expect(screen.getByRole("alert")).toHaveTextContent("권한이 없습니다.");
  });

  it("복구 클릭 시 trash.restore(bundle_id) 호출 (Req 8.5)", () => {
    mockNonAdmin();
    const trash = mockTrash({
      status: "ready",
      total: 1,
      bundles: [sampleBundle({ bundle_id: 99 })],
    });

    render(<TrashList workspaceId="7" currentRole={Role.MEMBER} />);

    fireEvent.click(screen.getByRole("button", { name: "복구" }));
    expect(trash.restore).toHaveBeenCalledTimes(1);
    expect(trash.restore).toHaveBeenCalledWith(99);
  });

  it("완전삭제 확인 시 trash.purge(bundle_id) 호출 (Req 8.5)", () => {
    mockNonAdmin();
    const trash = mockTrash({
      status: "ready",
      total: 1,
      bundles: [sampleBundle({ bundle_id: 55 })],
    });

    render(<TrashList workspaceId="7" currentRole={Role.MEMBER} />);

    fireEvent.click(screen.getByRole("button", { name: "완전삭제" }));
    const dialog = screen.getByRole("alertdialog");
    expect(trash.purge).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "완전삭제" }));
    expect(trash.purge).toHaveBeenCalledTimes(1);
    expect(trash.purge).toHaveBeenCalledWith(55);
  });

  it("변이 후 error(예: 404)는 목록과 함께 표면화된다 (Req 8.5)", () => {
    mockNonAdmin();
    mockTrash({
      status: "ready",
      total: 1,
      bundles: [sampleBundle({ bundle_id: 7, root_title: "잔존 묶음" })],
      error: new ApiError({ status: 404, code: "not_found", message: "이미 없습니다." }),
    });

    render(<TrashList workspaceId="7" currentRole={Role.MEMBER} />);

    expect(screen.getByRole("heading", { name: "잔존 묶음" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("이미 없습니다.");
  });

  it("admin bypass: currentRole=null + is_admin true → 화면 렌더·useTrash 실행 (Req 8.6)", () => {
    mockAdmin();
    mockTrash({
      status: "ready",
      total: 1,
      bundles: [sampleBundle({ bundle_id: 3, root_title: "관리자 열람" })],
    });

    render(<TrashList workspaceId="9" currentRole={null} />);

    expect(useTrashMock).toHaveBeenCalledWith("9");
    expect(screen.getByRole("heading", { name: "관리자 열람" })).toBeInTheDocument();
  });
});
