import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { Mock } from "vitest";

import { ROUTES } from "@/app/routes";

import { PublicDocumentView } from "../components/PublicDocumentView";
import { SharePage } from "./SharePage";

/**
 * s22 게스트 페이지(라우팅/파라미터) 테스트: `/share/:token` 게스트 라우트에 마운트된
 * SharePage 가 (1) 세션 Provider·가드 없이(공개, Req 6.1·8.3) 렌더되고, (2) 라우트
 * `token` 파라미터를 그대로 PublicDocumentView 로 전달함을 관측한다. 뷰어 하위 트리는
 * mock 으로 대체해 token prop 조달만 검증한다(가드 부재 = 리다이렉트 없음).
 */
vi.mock("../components/PublicDocumentView", () => ({
  PublicDocumentView: vi.fn(() => <div data-testid="public-view" />),
}));

describe("SharePage 게스트 페이지 (/share/:token 파라미터 → PublicDocumentView)", () => {
  beforeEach(() => {
    (PublicDocumentView as unknown as Mock).mockClear();
  });

  it("세션 Provider·가드 없이 렌더되고 token 파라미터를 PublicDocumentView 로 전달한다 (Req 6.1, 8.3)", () => {
    const router = createMemoryRouter(
      [{ path: ROUTES.share, element: <SharePage /> }],
      { initialEntries: ["/share/abc123"] },
    );
    render(<RouterProvider router={router} />);

    // (1) 세션 Provider 부재에도 리다이렉트 없이 게스트 화면이 렌더된다(공개, Req 6.1·8.3).
    expect(screen.getByTestId("public-view")).toBeInTheDocument();

    // (2) 라우트 token 파라미터가 그대로 뷰어 prop 으로 전달된다.
    const mock = PublicDocumentView as unknown as Mock;
    expect(mock).toHaveBeenCalled();
    expect(mock.mock.calls[0][0]).toEqual({ token: "abc123" });
  });
});
