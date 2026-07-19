import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AdminUserPanel } from "./AdminUserPanel";
import { adminApi } from "../api/adminApi";
import type { Page, UserRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

vi.mock("../api/adminApi", () => ({
  adminApi: {
    listUsers: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    resetPassword: vi.fn(),
    changeOwner: vi.fn(),
  },
}));

function user(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: 1,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    login_id: "root",
    name: "루트",
    email: null,
    is_admin: true,
    is_active: true,
    is_deleted: false,
    ...overrides,
  };
}

function page(items: UserRead[]): Page<UserRead> {
  return { items, total: items.length };
}

/** 특정 사용자 행(login_id 텍스트를 포함하는 li) 을 반환한다. */
function rowFor(loginId: string): HTMLElement {
  return screen.getByText(loginId).closest("li") as HTMLElement;
}

beforeEach(() => {
  vi.mocked(adminApi.listUsers).mockReset();
  vi.mocked(adminApi.createUser).mockReset();
  vi.mocked(adminApi.updateUser).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdminUserPanel — 목록 로드·상태 표시(Req 5.1)", () => {
  it("마운트 시 listUsers 를 호출하고 삭제·비활동 계정을 포함해 상태 flag 와 함께 렌더한다 (Req 5.1)", async () => {
    const admin = user({ id: 1, login_id: "root", is_admin: true, is_active: true, is_deleted: false });
    const deleted = user({
      id: 2,
      login_id: "bob",
      name: "밥",
      is_admin: false,
      is_active: false,
      is_deleted: true,
    });
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([admin, deleted]));

    render(<AdminUserPanel />);

    expect(adminApi.listUsers).toHaveBeenCalledTimes(1);

    // 삭제·비활동 계정도 필터링하지 않고 표시(Req 5.1).
    expect(await screen.findByText("root")).toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();

    const deletedRow = rowFor("bob");
    // 상태 flag 가 가시적으로 드러난다(비활성·삭제됨).
    expect(within(deletedRow).getByText(/비활성/)).toBeInTheDocument();
    expect(within(deletedRow).getByText(/삭제됨/)).toBeInTheDocument();
  });

  it("로드 실패 시 ErrorMessage(role=alert)를 표시한다 (Req 5.7)", async () => {
    vi.mocked(adminApi.listUsers).mockRejectedValue(
      new ApiError({ status: 500, code: "internal", message: "서버 오류가 발생했습니다." }),
    );

    render(<AdminUserPanel />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("서버 오류가 발생했습니다.");
  });
});

describe("AdminUserPanel — 계정 생성 결선(Req 5.2)", () => {
  it("생성 성공 시 새 계정이 목록에 반영된다 (201 → 반영)", async () => {
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([user({ id: 1, login_id: "root" })]));
    const created = user({ id: 9, login_id: "carol", name: "캐롤", is_admin: false });
    vi.mocked(adminApi.createUser).mockResolvedValue(created);

    render(<AdminUserPanel />);
    await screen.findByText("root");

    await userEvent.type(screen.getByLabelText("로그인 ID"), "carol");
    await userEvent.type(screen.getByLabelText("비밀번호"), "pw12345678");
    await userEvent.type(screen.getByLabelText("이름"), "캐롤");
    await userEvent.click(screen.getByRole("button", { name: "계정 생성" }));

    expect(await screen.findByText("carol")).toBeInTheDocument();
    expect(adminApi.createUser).toHaveBeenCalledWith({
      login_id: "carol",
      password: "pw12345678",
      name: "캐롤",
    });
  });

  it("중복 login_id 409 는 ErrorMessage 로 표시된다 (Req 5.7)", async () => {
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([user({ id: 1, login_id: "root" })]));
    vi.mocked(adminApi.createUser).mockRejectedValue(
      new ApiError({ status: 409, code: "conflict", message: "이미 존재하는 로그인 ID 입니다." }),
    );

    render(<AdminUserPanel />);
    await screen.findByText("root");

    await userEvent.type(screen.getByLabelText("로그인 ID"), "root");
    await userEvent.type(screen.getByLabelText("비밀번호"), "pw12345678");
    await userEvent.type(screen.getByLabelText("이름"), "중복");
    await userEvent.click(screen.getByRole("button", { name: "계정 생성" }));

    expect(await screen.findByText("이미 존재하는 로그인 ID 입니다.")).toBeInTheDocument();
  });
});

describe("AdminUserPanel — 독립 상태 토글·단일 admin 잠금(Req 5.3·5.5)", () => {
  it("is_active 토글은 updateUser(id, {is_active})만 보낸다 (독립)", async () => {
    const bob = user({ id: 2, login_id: "bob", is_admin: false, is_active: false, is_deleted: false });
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([bob]));
    vi.mocked(adminApi.updateUser).mockResolvedValue({ ...bob, is_active: true });

    render(<AdminUserPanel />);
    await screen.findByText("bob");

    await userEvent.click(screen.getByRole("button", { name: "bob 재활성화" }));

    await waitFor(() => expect(adminApi.updateUser).toHaveBeenCalledTimes(1));
    expect(adminApi.updateUser).toHaveBeenCalledWith(2, { is_active: true });
  });

  it("is_deleted 토글은 updateUser(id, {is_deleted})만 보낸다 (독립)", async () => {
    const bob = user({ id: 2, login_id: "bob", is_admin: false, is_active: true, is_deleted: false });
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([bob]));
    vi.mocked(adminApi.updateUser).mockResolvedValue({ ...bob, is_deleted: true });

    render(<AdminUserPanel />);
    await screen.findByText("bob");

    await userEvent.click(screen.getByRole("button", { name: "bob 삭제" }));

    await waitFor(() => expect(adminApi.updateUser).toHaveBeenCalledTimes(1));
    expect(adminApi.updateUser).toHaveBeenCalledWith(2, { is_deleted: true });
  });

  it("단일 admin 비활성화 409 는 안내 문구를 표시하고 목록 상태를 되돌린다 (Req 5.5)", async () => {
    const admin = user({ id: 1, login_id: "root", is_admin: true, is_active: true, is_deleted: false });
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([admin]));
    vi.mocked(adminApi.updateUser).mockRejectedValue(
      new ApiError({ status: 409, code: "conflict", message: "last admin" }),
    );

    render(<AdminUserPanel />);
    await screen.findByText("root");

    await userEvent.click(screen.getByRole("button", { name: "root 비활성화" }));

    expect(await screen.findByText(/마지막 admin/)).toBeInTheDocument();
    // 롤백: 여전히 활성 상태(비활성화 버튼이 그대로 노출).
    expect(screen.getByRole("button", { name: "root 비활성화" })).toBeInTheDocument();
  });
});

describe("AdminUserPanel — 비밀번호 재설정 진입(Req 5.4)", () => {
  it("행의 비밀번호 재설정 버튼으로 다이얼로그를 열고 resetPassword 를 결선한다 (Req 5.4)", async () => {
    const bob = user({ id: 2, login_id: "bob" });
    vi.mocked(adminApi.listUsers).mockResolvedValue(page([bob]));
    vi.mocked(adminApi.resetPassword).mockResolvedValue(undefined);

    render(<AdminUserPanel />);
    await screen.findByText("bob");

    await userEvent.click(screen.getByRole("button", { name: "bob 비밀번호 재설정" }));

    await userEvent.type(screen.getByLabelText("새 비밀번호"), "newpw123456");
    await userEvent.click(screen.getByRole("button", { name: "재설정" }));

    await waitFor(() => expect(adminApi.resetPassword).toHaveBeenCalledTimes(1));
    expect(adminApi.resetPassword).toHaveBeenCalledWith(2, { new_password: "newpw123456" });
  });
});
