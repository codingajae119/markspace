import { describe, it, expect } from "vitest";

import { buildShareUrl } from "./buildShareUrl";

/**
 * buildShareUrl 은 게스트가 여는 프론트 링크(`<origin>/share/<token>`)를 구성하는 순수 함수다.
 * 경로 세그먼트는 s16 `ROUTES.share`(정적 `"/share/:token"`)의 `:token` 치환에서 파생하며,
 * 백엔드 `share_url`(`/public/{token}` 공개 API 경로)을 노출하지 않는다.
 * 부수효과가 없어(단 `window.location.origin` 읽기만) 단위 테스트로 계약을 고정한다
 * (Requirements 2.2, 4.1).
 */
describe("buildShareUrl", () => {
  it("`<origin>/share/<token>` 를 구성한다(origin 은 window.location.origin)", () => {
    expect(buildShareUrl("abc")).toBe(`${window.location.origin}/share/abc`);
  });

  it("서로 다른 토큰은 서로 다른 게스트 링크를 낸다", () => {
    expect(buildShareUrl("token-xyz")).toBe(`${window.location.origin}/share/token-xyz`);
    expect(buildShareUrl("abc")).not.toBe(buildShareUrl("def"));
  });

  it("백엔드 공개 API 경로(`/public/`)를 노출하지 않는다", () => {
    expect(buildShareUrl("abc")).not.toContain("/public/");
  });
});
