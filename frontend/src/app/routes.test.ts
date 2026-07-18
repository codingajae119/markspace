import { describe, it, expect } from "vitest";

import {
  ROUTES,
  RETURN_TO_PARAM,
  buildLoginPath,
  resolveReturnTo,
} from "@/app/routes";

describe("ROUTES", () => {
  it("exposes the canonical route path constants", () => {
    expect(ROUTES.login).toBe("/login");
    expect(ROUTES.root).toBe("/");
    expect(ROUTES.share).toBe("/share/:token");
  });

  it("uses the returnTo param key that the NavSeam default mirrors", () => {
    expect(RETURN_TO_PARAM).toBe("returnTo");
  });
});

describe("buildLoginPath", () => {
  it("appends an encoded returnTo query for a normal protected path", () => {
    expect(buildLoginPath("/docs/5")).toBe("/login?returnTo=%2Fdocs%2F5");
  });

  it("encodes returnTo values that themselves contain query strings", () => {
    expect(buildLoginPath("/docs/5?tab=history")).toBe(
      "/login?returnTo=%2Fdocs%2F5%3Ftab%3Dhistory",
    );
  });

  it("omits the query when returnTo is empty (avoids ?returnTo= noise)", () => {
    expect(buildLoginPath("")).toBe("/login");
  });

  it("omits the query when returnTo equals root (avoids ?returnTo=%2F noise)", () => {
    expect(buildLoginPath("/")).toBe("/login");
  });
});

describe("resolveReturnTo", () => {
  it("round-trips a path produced by buildLoginPath", () => {
    const built = buildLoginPath("/docs/5");
    const search = built.slice(built.indexOf("?"));
    expect(resolveReturnTo(search)).toBe("/docs/5");
    expect(resolveReturnTo("?returnTo=%2Fdocs%2F5")).toBe("/docs/5");
  });

  it("restores a returnTo path that contains an encoded query string", () => {
    expect(resolveReturnTo("?returnTo=%2Fdocs%2F5%3Ftab%3Dhistory")).toBe(
      "/docs/5?tab=history",
    );
  });

  it("defaults to root when the search string is empty", () => {
    expect(resolveReturnTo("")).toBe(ROUTES.root);
  });

  it("defaults to root when the returnTo param is absent", () => {
    expect(resolveReturnTo("?foo=bar")).toBe(ROUTES.root);
  });

  it("defaults to root when the returnTo param is present but empty", () => {
    expect(resolveReturnTo("?returnTo=")).toBe(ROUTES.root);
  });

  it("tolerates a leading '?' being absent", () => {
    expect(resolveReturnTo("returnTo=%2Fdocs%2F5")).toBe("/docs/5");
  });

  it("rejects absolute external URLs (open-redirect guard)", () => {
    expect(resolveReturnTo("?returnTo=https%3A%2F%2Fevil.com")).toBe(
      ROUTES.root,
    );
  });

  it("rejects protocol-relative URLs (open-redirect guard)", () => {
    expect(resolveReturnTo("?returnTo=%2F%2Fevil.com")).toBe(ROUTES.root);
  });

  it("rejects backslash protocol-relative URLs (open-redirect guard)", () => {
    expect(resolveReturnTo("?returnTo=%2F%5Cevil.com")).toBe(ROUTES.root);
    expect(resolveReturnTo("?returnTo=%5C%5Cevil.com")).toBe(ROUTES.root);
  });

  it("rejects a returnTo that is not a relative path (must start with '/')", () => {
    expect(resolveReturnTo("?returnTo=docs%2F5")).toBe(ROUTES.root);
  });

  it("accepts a same-origin relative path with query and fragment", () => {
    expect(resolveReturnTo("?returnTo=%2Fdocs%2F5%23section")).toBe(
      "/docs/5#section",
    );
  });
});
