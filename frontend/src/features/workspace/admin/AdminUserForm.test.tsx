import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AdminUserForm } from "./AdminUserForm";
import { adminApi } from "../api/adminApi";
import type { UserRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// adminApi 를 모킹하여 폼 단독 경계에서 create/updateUser 결선을 검증한다.
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
    id: 5,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: null,
    login_id: "carol",
    name: "캐롤",
    email: null,
    is_admin: false,
    is_active: true,
    is_deleted: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(adminApi.createUser).mockReset();
  vi.mocked(adminApi.updateUser).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdminUserForm — 계정 생성(Req 5.2)", () => {
  it("login_id·password·name·email 입력만 노출하고 is_admin·상태 flag 입력은 없다 (Req 5.2)", () => {
    render(<AdminUserForm onSaved={vi.fn()} />);

    expect(screen.getByLabelText("로그인 ID")).toBeInTheDocument();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
    expect(screen.getByLabelText("이름")).toBeInTheDocument();
    expect(screen.getByLabelText("이메일")).toBeInTheDocument();
    // is_admin·is_active·is_deleted 는 생성 시 입력받지 않는다.
    expect(screen.queryByLabelText(/관리자/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/활성/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/삭제/)).not.toBeInTheDocument();
  });

  it("유효 입력 제출 시 createUser(login_id·password·name·email)를 호출하고 onSaved 로 결과를 전달한다 (Req 5.2)", async () => {
    const created = user({ id: 9, login_id: "carol", name: "캐롤", email: "carol@example.com" });
    vi.mocked(adminApi.createUser).mockResolvedValue(created);
    const onSaved = vi.fn();

    render(<AdminUserForm onSaved={onSaved} />);

    await userEvent.type(screen.getByLabelText("로그인 ID"), "carol");
    await userEvent.type(screen.getByLabelText("비밀번호"), "pw12345678");
    await userEvent.type(screen.getByLabelText("이름"), "캐롤");
    await userEvent.type(screen.getByLabelText("이메일"), "carol@example.com");
    await userEvent.click(screen.getByRole("button", { name: "계정 생성" }));

    await waitFor(() => expect(adminApi.createUser).toHaveBeenCalledTimes(1));
    expect(adminApi.createUser).toHaveBeenCalledWith({
      login_id: "carol",
      password: "pw12345678",
      name: "캐롤",
      email: "carol@example.com",
    });
    expect(onSaved).toHaveBeenCalledWith(created);
  });

  it("이메일 미입력 시 body 에 email 을 포함하지 않는다 (email 선택)", async () => {
    vi.mocked(adminApi.createUser).mockResolvedValue(user({ id: 10, login_id: "dave" }));

    render(<AdminUserForm onSaved={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("로그인 ID"), "dave");
    await userEvent.type(screen.getByLabelText("비밀번호"), "pw12345678");
    await userEvent.type(screen.getByLabelText("이름"), "데이브");
    await userEvent.click(screen.getByRole("button", { name: "계정 생성" }));

    await waitFor(() => expect(adminApi.createUser).toHaveBeenCalledTimes(1));
    expect(adminApi.createUser).toHaveBeenCalledWith({
      login_id: "dave",
      password: "pw12345678",
      name: "데이브",
    });
  });

  it("성공 시 비밀번호를 화면에 보존하지 않는다 (비밀번호 미보존)", async () => {
    vi.mocked(adminApi.createUser).mockResolvedValue(user({ id: 11, login_id: "erin" }));

    render(<AdminUserForm onSaved={vi.fn()} />);

    const pw = screen.getByLabelText("비밀번호") as HTMLInputElement;
    await userEvent.type(screen.getByLabelText("로그인 ID"), "erin");
    await userEvent.type(pw, "pw12345678");
    await userEvent.type(screen.getByLabelText("이름"), "에린");
    await userEvent.click(screen.getByRole("button", { name: "계정 생성" }));

    await waitFor(() => expect(pw.value).toBe(""));
  });

  it("중복 login_id 409 는 ErrorMessage(role=alert)로 표시한다 (Req 5.7)", async () => {
    vi.mocked(adminApi.createUser).mockRejectedValue(
      new ApiError({ status: 409, code: "conflict", message: "이미 존재하는 로그인 ID 입니다." }),
    );

    render(<AdminUserForm onSaved={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("로그인 ID"), "carol");
    await userEvent.type(screen.getByLabelText("비밀번호"), "pw12345678");
    await userEvent.type(screen.getByLabelText("이름"), "캐롤");
    await userEvent.click(screen.getByRole("button", { name: "계정 생성" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("이미 존재하는 로그인 ID 입니다.");
  });
});

describe("AdminUserForm — 상태 편집(is_active·is_deleted 독립 토글, Req 5.3)", () => {
  it("활성 계정의 비활성화 토글은 updateUser(id, {is_active:false})만 보낸다 (is_deleted 미포함)", async () => {
    const target = user({ id: 5, is_active: true, is_deleted: false });
    vi.mocked(adminApi.updateUser).mockResolvedValue({ ...target, is_active: false });

    render(<AdminUserForm user={target} onSaved={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "carol 비활성화" }));

    await waitFor(() => expect(adminApi.updateUser).toHaveBeenCalledTimes(1));
    expect(adminApi.updateUser).toHaveBeenCalledWith(5, { is_active: false });
  });

  it("삭제 토글은 updateUser(id, {is_deleted:true})만 보낸다 (is_active 미포함, 독립)", async () => {
    const target = user({ id: 5, is_active: true, is_deleted: false });
    vi.mocked(adminApi.updateUser).mockResolvedValue({ ...target, is_deleted: true });

    render(<AdminUserForm user={target} onSaved={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "carol 삭제" }));

    await waitFor(() => expect(adminApi.updateUser).toHaveBeenCalledTimes(1));
    expect(adminApi.updateUser).toHaveBeenCalledWith(5, { is_deleted: true });
  });

  it("삭제된 계정은 복원 토글이 updateUser(id, {is_deleted:false})를 보낸다", async () => {
    const target = user({ id: 5, is_deleted: true });
    vi.mocked(adminApi.updateUser).mockResolvedValue({ ...target, is_deleted: false });

    render(<AdminUserForm user={target} onSaved={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "carol 복원" }));

    await waitFor(() => expect(adminApi.updateUser).toHaveBeenCalledWith(5, { is_deleted: false }));
  });

  it("단일 admin 409 는 안내 문구를 표시하고 onSaved 를 호출하지 않는다 (Req 5.5 롤백)", async () => {
    const target = user({ id: 5, is_admin: true, is_active: true });
    vi.mocked(adminApi.updateUser).mockRejectedValue(
      new ApiError({ status: 409, code: "conflict", message: "last admin" }),
    );
    const onSaved = vi.fn();

    render(<AdminUserForm user={target} onSaved={onSaved} />);

    await userEvent.click(screen.getByRole("button", { name: "carol 비활성화" }));

    expect(await screen.findByText(/마지막 admin/)).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
