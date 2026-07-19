import { describe, it, expect, afterEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import type { PublicDocumentNode } from "../api/types";
import type { PublicDocState } from "../hooks/usePublicDocument";
import { ApiError } from "@/shared/api/errors";
import { usePublicDocument } from "../hooks/usePublicDocument";
import { PublicDocumentView } from "./PublicDocumentView";

// usePublicDocument 을 목으로 대체해 각 판별 상태를 직접 구동한다(실제 fetch 없이).
vi.mock("../hooks/usePublicDocument", () => ({
  usePublicDocument: vi.fn(),
}));

// 문서화된 예외 캐스트: 목 함수의 반환값을 상태별로 지정한다.
const mockUsePublicDocument = usePublicDocument as unknown as Mock;

function setState(state: PublicDocState): void {
  mockUsePublicDocument.mockReturnValue(state);
}

function makeNode(overrides: Partial<PublicDocumentNode> = {}): PublicDocumentNode {
  return {
    id: 1,
    title: "루트 문서",
    content_html: "<p>hello</p>",
    children: [],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PublicDocumentView — 게스트 뷰 컨테이너 (Req 6.1·6.4·6.5·6.6)", () => {
  it("loading 상태에서 Spinner(role=status)를 렌더한다 (Req 6.1)", () => {
    setState({ status: "loading" });
    render(<PublicDocumentView token="tok" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("unavailable 상태에서 '링크 사용 불가' EmptyState 를 렌더한다 (Req 6.5 — 사유 미구분)", () => {
    setState({ status: "unavailable" });
    render(<PublicDocumentView token="tok" />);
    expect(screen.getByText("링크 사용 불가")).toBeInTheDocument();
  });

  it("error 상태에서 ApiError message 를 ErrorMessage 로 표면화한다 (Req 6.1)", () => {
    const error = new ApiError({
      status: 500,
      code: "internal",
      message: "서버 오류가 발생했습니다.",
    });
    setState({ status: "error", error });
    render(<PublicDocumentView token="tok" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("서버 오류가 발생했습니다.")).toBeInTheDocument();
  });

  it("ready 상태에서 root 노드와 중첩 자식을 PublicDocumentNodeView 로 렌더한다 (Req 6.6)", () => {
    const root = makeNode({
      title: "공유 루트",
      content_html: "<p>루트본문</p>",
      children: [
        makeNode({ id: 2, title: "중첩 자식", content_html: "<p>자식본문</p>", children: [] }),
      ],
    });
    setState({ status: "ready", root });
    render(<PublicDocumentView token="tok" />);

    expect(screen.getByText("공유 루트")).toBeInTheDocument();
    expect(screen.getByText("루트본문")).toBeInTheDocument();
    // 중첩 자식도 재귀 렌더된다.
    expect(screen.getByText("중첩 자식")).toBeInTheDocument();
    expect(screen.getByText("자식본문")).toBeInTheDocument();
  });

  it("ready 상태는 읽기 전용 — 편집/삭제/이동/발급 등 변경 어포던스를 노출하지 않는다 (Req 6.4)", () => {
    const root = makeNode({ title: "읽기전용 문서", children: [] });
    setState({ status: "ready", root });
    const { container } = render(<PublicDocumentView token="tok" />);

    // 명명된 변경 컨트롤이 없다.
    expect(
      screen.queryByRole("button", { name: /편집|삭제|이동|발급|저장|해제/ }),
    ).toBeNull();
    // 어떤 버튼도, 어떤 입력 컨트롤도 존재하지 않는 순수 뷰어다.
    expect(within(container).queryByRole("button")).toBeNull();
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector("textarea")).toBeNull();
  });
});
