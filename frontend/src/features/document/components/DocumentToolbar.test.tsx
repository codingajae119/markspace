import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";

import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";
import { useSession } from "@/app/session/useSession";
import type { useDocumentMutations } from "../hooks/useDocumentMutations";
import { DocumentToolbar } from "./DocumentToolbar";

// DocumentToolbar 은 생성·이름변경·삭제 조작을 RequireRole(minimum=EDITOR) 단일 게이트로
// 감싸 viewer·비멤버에게 미노출한다(Req 3.6·4.5·5.6·9.2). RequireRole 은 isAdmin 을
// useSession() 에서만 취득하므로(admin override) 세션 훅을 모킹한다. mutations 는 주입된
// 의존을 그대로 소비하는 목으로 대체해 호출 인자를 관찰한다.
// Requirements: 3.1, 3.6, 4.1, 4.5, 5.1, 5.6, 9.2

vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;

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

/** create/rename/remove/move·state 를 갖춘 타입 안전 mutations 목(any 미사용). */
function makeMutations(
  state: { pending: boolean; error: ApiError | null } = { pending: false, error: null },
): ReturnType<typeof useDocumentMutations> {
  return {
    create: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    move: vi.fn(),
    state,
  };
}

beforeEach(() => {
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("DocumentToolbar — RequireRole 단일 게이트 생성·이름변경·삭제", () => {
  it("viewer(비-admin) → 생성·이름변경·삭제 컨트롤 미노출 (Req 3.6·4.5·5.6·9.2)", () => {
    mockNonAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={Role.VIEWER}
        selectedId={5}
        selectedTitle="문서"
      />,
    );

    expect(screen.queryByRole("button", { name: "새 문서" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "이름 변경" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "삭제" })).not.toBeInTheDocument();
  });

  it("editor → 생성 컨트롤 노출, 제출 시 create({ title, parentId }) 호출 (Req 3.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.EDITOR}
        selectedId={null}
        selectedTitle={null}
      />,
    );

    fireEvent.change(screen.getByLabelText("새 문서 제목"), {
      target: { value: "  새 노트  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "새 문서" }));

    expect(vi.mocked(mutations.create)).toHaveBeenCalledWith({
      title: "새 노트",
      parentId: null,
    });
  });

  it("editor → 빈 제목은 제출하지 않는다(클라이언트 가드, Req 3.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.EDITOR}
        selectedId={null}
        selectedTitle={null}
      />,
    );

    fireEvent.change(screen.getByLabelText("새 문서 제목"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "새 문서" }));

    expect(vi.mocked(mutations.create)).not.toHaveBeenCalled();
  });

  it("owner → 이름 변경 컨트롤이 rename(selectedId, title) 호출 (Req 4.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.OWNER}
        selectedId={42}
        selectedTitle="원래 제목"
      />,
    );

    fireEvent.change(screen.getByLabelText("문서 이름 변경"), {
      target: { value: "새 제목" },
    });
    fireEvent.click(screen.getByRole("button", { name: "이름 변경" }));

    expect(vi.mocked(mutations.rename)).toHaveBeenCalledWith(42, "새 제목");
  });

  it("admin 세션 + currentRole null → 컨트롤 노출(RequireRole admin override, Req 9.2)", () => {
    mockAdmin();
    render(
      <DocumentToolbar
        mutations={makeMutations()}
        currentRole={null}
        selectedId={5}
        selectedTitle="문서"
      />,
    );

    expect(screen.getByRole("button", { name: "새 문서" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "이름 변경" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "삭제" })).toBeInTheDocument();
  });

  it("삭제 → ConfirmDialog 확인 시 remove(selectedId) 호출 후 닫힘 (Req 5.1)", () => {
    mockNonAdmin();
    const mutations = makeMutations();
    render(
      <DocumentToolbar
        mutations={mutations}
        currentRole={Role.EDITOR}
        selectedId={7}
        selectedTitle="지울 문서"
      />,
    );

    // 초기엔 다이얼로그 없음.
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "삭제" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "휴지통으로 이동" }));
    expect(vi.mocked(mutations.remove)).toHaveBeenCalledWith(7);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("mutations.state.error → ErrorMessage 로 표면화한다", () => {
    mockNonAdmin();
    const error = new ApiError({
      status: 409,
      code: "conflict",
      message: "이미 존재하는 문서입니다.",
    });
    render(
      <DocumentToolbar
        mutations={makeMutations({ pending: false, error })}
        currentRole={Role.EDITOR}
        selectedId={null}
        selectedTitle={null}
      />,
    );

    expect(screen.getByText("이미 존재하는 문서입니다.")).toBeInTheDocument();
  });
});
