import { describe, it, expect, beforeEach, vi } from "vitest";

import {
  setNavigator,
  setLoginPathBuilder,
  redirectToLogin,
  resetNavigation,
} from "@/shared/api/navigation";

beforeEach(() => {
  // 모듈 스코프 싱글턴이 테스트 간 누수하지 않도록 초기화.
  resetNavigation();
});

describe("navigation seam", () => {
  it("is a safe no-op when no navigator is injected", () => {
    // navigator 미주입 시 redirectToLogin 은 던지지 않고 조용히 무시된다.
    expect(() => redirectToLogin("/docs/5")).not.toThrow();
  });

  it("navigates to the login path preserving returnTo (encoded) after setNavigator", () => {
    const nav = vi.fn();
    setNavigator(nav);

    redirectToLogin("/docs/5");

    expect(nav).toHaveBeenCalledTimes(1);
    expect(nav).toHaveBeenCalledWith("/login?returnTo=%2Fdocs%2F5", {
      replace: true,
    });
  });

  it("URL-encodes returnTo paths that contain query strings and special chars", () => {
    const nav = vi.fn();
    setNavigator(nav);

    const currentPath = "/docs/5?tab=a&x=1#frag";
    redirectToLogin(currentPath);

    const expectedEncoded = encodeURIComponent(currentPath);
    expect(nav).toHaveBeenCalledWith(`/login?returnTo=${expectedEncoded}`, {
      replace: true,
    });
    // returnTo 는 round-trip 으로 원래 경로를 복원할 수 있어야 한다.
    const call = nav.mock.calls[0];
    const to = call[0] as string;
    const search = to.slice(to.indexOf("?"));
    const returnTo = new URLSearchParams(search).get("returnTo");
    expect(returnTo).toBe(currentPath);
  });

  it("uses an injected login-path builder instead of the default when provided", () => {
    const nav = vi.fn();
    setNavigator(nav);
    const customBuilder = vi.fn(
      (currentPath: string) => `/signin#back=${encodeURIComponent(currentPath)}`,
    );
    setLoginPathBuilder(customBuilder);

    redirectToLogin("/docs/5");

    expect(customBuilder).toHaveBeenCalledWith("/docs/5");
    expect(nav).toHaveBeenCalledWith("/signin#back=%2Fdocs%2F5", {
      replace: true,
    });
  });

  it("does not invoke the login-path builder when no navigator is present", () => {
    const customBuilder = vi.fn((currentPath: string) => `/login?rt=${currentPath}`);
    setLoginPathBuilder(customBuilder);

    redirectToLogin("/docs/5");

    // navigator 가 없으면 경로 계산조차 하지 않고 안전하게 무시된다.
    expect(customBuilder).not.toHaveBeenCalled();
  });
});
