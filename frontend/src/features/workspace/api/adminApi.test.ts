import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { adminApi } from "./adminApi";
import { apiClient } from "@/shared/api/client";
import type { UserRead, WorkspaceRead, Page } from "./types";

// adminApi 는 얇은 어댑터이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·바디를 관찰한다.
vi.mock("@/shared/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

const getMock = apiClient.get as unknown as Mock;
const postMock = apiClient.post as unknown as Mock;
const patchMock = apiClient.patch as unknown as Mock;

/** 응답으로 반환할 UserRead 픽스처. */
function sampleUser(): UserRead {
  return {
    id: 3,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    login_id: "alice",
    name: "Alice",
    email: null,
    is_admin: false,
    is_active: true,
    is_deleted: false,
  };
}

/** 목록 응답 Page 픽스처. */
function sampleUserPage(): Page<UserRead> {
  return { items: [sampleUser()], total: 1 };
}

/** changeOwner 응답으로 반환할 WorkspaceRead 픽스처. */
function sampleWorkspace(): WorkspaceRead {
  return {
    id: 7,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    name: "WS",
    is_shareable: false,
    trash_retention_days: 30,
  };
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
});

describe("adminApi.listUsers", () => {
  it("gets a clean /admin/users path when no limit/offset are provided", async () => {
    const page = sampleUserPage();
    getMock.mockResolvedValueOnce(page);

    const result = await adminApi.listUsers();

    expect(getMock).toHaveBeenCalledWith("/admin/users");
    expect(result).toEqual(page);
  });

  it("appends limit and offset as query params when both are provided", async () => {
    getMock.mockResolvedValueOnce(sampleUserPage());

    await adminApi.listUsers(20, 40);

    expect(getMock).toHaveBeenCalledWith("/admin/users?limit=20&offset=40");
  });

  it("appends only limit when offset is omitted", async () => {
    getMock.mockResolvedValueOnce(sampleUserPage());

    await adminApi.listUsers(20);

    expect(getMock).toHaveBeenCalledWith("/admin/users?limit=20");
  });

  it("appends only offset when limit is omitted", async () => {
    getMock.mockResolvedValueOnce(sampleUserPage());

    await adminApi.listUsers(undefined, 40);

    expect(getMock).toHaveBeenCalledWith("/admin/users?offset=40");
  });
});

describe("adminApi.createUser", () => {
  it("posts to /admin/users with the create body and returns the created user", async () => {
    const user = sampleUser();
    postMock.mockResolvedValueOnce(user);

    const result = await adminApi.createUser({
      login_id: "alice",
      password: "pw",
      name: "Alice",
    });

    expect(postMock).toHaveBeenCalledWith("/admin/users", {
      login_id: "alice",
      password: "pw",
      name: "Alice",
    });
    expect(result).toEqual(user);
  });
});

describe("adminApi.updateUser", () => {
  it("patches /admin/users/{id} with the update body and returns the updated user", async () => {
    const user = sampleUser();
    patchMock.mockResolvedValueOnce(user);

    const result = await adminApi.updateUser(3, { is_active: false });

    expect(patchMock).toHaveBeenCalledWith("/admin/users/3", { is_active: false });
    expect(result).toEqual(user);
  });
});

describe("adminApi.resetPassword", () => {
  it("posts /admin/users/{id}/password with new_password and resolves void", async () => {
    postMock.mockResolvedValueOnce(undefined);

    const result = await adminApi.resetPassword(3, { new_password: "newpw" });

    expect(postMock).toHaveBeenCalledWith("/admin/users/3/password", {
      new_password: "newpw",
    });
    expect(result).toBeUndefined();
  });
});

describe("adminApi.changeOwner", () => {
  it("posts /admin/workspaces/{id}/owner with new_owner_user_id and returns the workspace", async () => {
    const ws = sampleWorkspace();
    postMock.mockResolvedValueOnce(ws);

    const result = await adminApi.changeOwner(7, { new_owner_user_id: 5 });

    expect(postMock).toHaveBeenCalledWith("/admin/workspaces/7/owner", {
      new_owner_user_id: 5,
    });
    expect(result).toEqual(ws);
  });
});
