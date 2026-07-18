import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";

import { authApi } from "./authApi";
import { apiClient } from "@/shared/api/client";
import type { AuthUser } from "@/app/session/SessionProvider";

// authApi 는 얇은 래퍼이므로 실제 HTTP 대신 s16 apiClient 를 모킹해 위임 경로·옵션을 관찰한다.
vi.mock("@/shared/api/client", () => ({ apiClient: { post: vi.fn() } }));

const postMock = apiClient.post as unknown as Mock;

/** 로그인 응답으로 반환할 정본 AuthUser 픽스처. */
function sampleUser(): AuthUser {
  return { id: 1, login_id: "u", name: "User", email: null, is_admin: false };
}

beforeEach(() => {
  postMock.mockReset();
});

describe("authApi.login", () => {
  it("posts to /auth/login with a login_id·password body and skipAuthRedirect", async () => {
    const user = sampleUser();
    postMock.mockResolvedValueOnce(user);

    const result = await authApi.login({ login_id: "u", password: "p" });

    expect(postMock).toHaveBeenCalledWith(
      "/auth/login",
      { login_id: "u", password: "p" },
      { skipAuthRedirect: true },
    );
    expect(result).toEqual(user);
  });
});

describe("authApi.logout", () => {
  it("posts to /auth/logout on the default path (no skipAuthRedirect)", async () => {
    postMock.mockResolvedValueOnce(undefined);

    await authApi.logout();

    expect(postMock).toHaveBeenCalledWith("/auth/logout");
  });
});

describe("authApi.changePassword", () => {
  it("posts to /auth/password with the password change body on the default path", async () => {
    postMock.mockResolvedValueOnce(undefined);

    await authApi.changePassword({ current_password: "old", new_password: "newsecret" });

    expect(postMock).toHaveBeenCalledWith("/auth/password", {
      current_password: "old",
      new_password: "newsecret",
    });
  });
});
