import { describe, it, expect, beforeEach, vi, type Mock } from "vitest";
import type { ReactElement } from "react";

import { AttachmentImage } from "./AttachmentImage";
import { AttachmentFileLink } from "./AttachmentFileLink";
import { buildAttachmentRenderers } from "./AttachmentRenderBridge";

/**
 * AttachmentRenderBridge 는 s16 `EditorWrapper.renderers` 슬롯에 넘길 `CustomRenderers`
 * (edit·read 양 모드 공통)를 구성한다. 이미지 참조(`/attachments/{id}`)는 인증
 * `AttachmentImage`, 파일 링크는 `AttachmentFileLink` 로 라우팅하며(단일 렌더 경로),
 * 비첨부 참조는 원시 `src` 없는 무해 요소/기본 위임으로 폴백한다. 라우팅만 격리 검증하기
 * 위해 자식 컴포넌트와 `react-dom/client` `createRoot` 를 모킹하고, `resolveAttachmentReference`
 * 는 실제 lib 을 사용한다(Requirements 3.5, 5.3, 7.2, 7.5).
 */

// createRoot(container).render(element) 의 render 인자(React element)를 캡처한다.
const { renderSpy, createRootSpy } = vi.hoisted(() => {
  const renderSpy = vi.fn();
  const createRootSpy = vi.fn(() => ({ render: renderSpy, unmount: vi.fn() }));
  return { renderSpy, createRootSpy };
});
vi.mock("react-dom/client", () => ({ createRoot: createRootSpy }));

// 자식 컴포넌트는 식별 가능한 참조로만 모킹한다(실제 렌더/HTTP 없이 라우팅만 확인).
vi.mock("./AttachmentImage", () => ({
  AttachmentImage: vi.fn(() => null),
}));
vi.mock("./AttachmentFileLink", () => ({
  AttachmentFileLink: vi.fn(() => null),
}));

/** renderSpy 가 마운트한 최근 React element 를 반환한다. */
function lastRendered(): ReactElement {
  const calls = renderSpy.mock.calls;
  return calls[calls.length - 1][0] as ReactElement;
}

/** Toast link 컨버터 호출을 흉내내는 최소 노드/컨텍스트. */
interface ToastLinkNodeLike {
  destination: string | null;
}
function makeContext(
  overrides: {
    entering?: boolean;
    childrenText?: string;
    origin?: Mock;
  } = {},
) {
  return {
    entering: overrides.entering ?? true,
    getChildrenText: vi.fn(() => overrides.childrenText ?? ""),
    skipChildren: vi.fn(),
    origin: overrides.origin ?? vi.fn(() => null),
  };
}

describe("AttachmentRenderBridge — 참조 resolver + s16 renderers 결선 (3.5, 5.3, 7.2, 7.5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("customImageRenderer('/attachments/7'): AttachmentImage(id=7) 를 마운트한 HTMLElement 반환", () => {
    const { customImageRenderer } = buildAttachmentRenderers();
    expect(customImageRenderer).toBeDefined();

    const el = customImageRenderer!("/attachments/7");

    expect(el).toBeInstanceOf(HTMLElement);
    // 반환한 컨테이너에 createRoot 로 마운트한다(원시 src 아님).
    expect(createRootSpy).toHaveBeenCalledWith(el);
    const rendered = lastRendered();
    expect(rendered.type).toBe(AttachmentImage);
    expect((rendered.props as { attachmentId: number }).attachmentId).toBe(7);
    // 원시 /attachments src 금지.
    expect(el.outerHTML).not.toContain("<img");
    expect(el.outerHTML).not.toContain("/attachments/7");
  });

  it("customImageRenderer(비첨부 href): AttachmentImage 마운트 없이 무해 요소(원시 src 없음) 반환", () => {
    const { customImageRenderer } = buildAttachmentRenderers();

    const el = customImageRenderer!("https://evil.example/x.png");

    expect(el).toBeInstanceOf(HTMLElement);
    expect(createRootSpy).not.toHaveBeenCalled();
    expect(renderSpy).not.toHaveBeenCalled();
    expect(el.outerHTML).not.toContain("<img");
    expect(el.outerHTML).not.toContain("evil.example");
  });

  it("customImageRenderer('/attachments/0'): 실제 resolver 규약(양의 정수만) → 미라우팅", () => {
    const { customImageRenderer } = buildAttachmentRenderers();

    customImageRenderer!("/attachments/0");
    customImageRenderer!("/attachments/042");
    customImageRenderer!("/attachments/7?x=1");

    expect(createRootSpy).not.toHaveBeenCalled();
  });

  it("customHTMLRenderer.link(파일 첨부 /attachments/9): AttachmentFileLink(id=9, fileName) 로 라우팅", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const node: ToastLinkNodeLike = { destination: "/attachments/9" };
    const ctx = makeContext({ entering: true, childrenText: "report.pdf" });
    const token = link(node, ctx);

    const rendered = lastRendered();
    expect(rendered.type).toBe(AttachmentFileLink);
    expect((rendered.props as { attachmentId: number }).attachmentId).toBe(9);
    expect((rendered.props as { fileName: string }).fileName).toBe("report.pdf");
    // 자식(링크 텍스트) 기본 렌더는 건너뛰고 html 토큰으로 치환, 기본 위임 없음.
    expect(ctx.skipChildren).toHaveBeenCalled();
    expect(ctx.origin).not.toHaveBeenCalled();
    expect(token).toMatchObject({ type: "html" });
  });

  it("customHTMLRenderer.link(닫는 토큰): 첨부여도 entering=false 는 null 반환(중복 마운트 없음)", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const node: ToastLinkNodeLike = { destination: "/attachments/9" };
    const token = link(node, makeContext({ entering: false, childrenText: "report.pdf" }));

    expect(token).toBeNull();
    expect(renderSpy).not.toHaveBeenCalled();
  });

  it("customHTMLRenderer.link(비첨부 링크): AttachmentFileLink 미라우팅 + 기본 위임(origin)", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const defaultToken = { type: "openTag", tagName: "a" };
    const origin = vi.fn(() => defaultToken);
    const node: ToastLinkNodeLike = { destination: "https://example.com/page" };
    const result = link(node, makeContext({ entering: true, origin }));

    expect(renderSpy).not.toHaveBeenCalled();
    expect(origin).toHaveBeenCalled();
    expect(result).toBe(defaultToken);
  });

  it("customHTMLRenderer.link(destination=null): 안전하게 기본 위임", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const origin = vi.fn(() => null);
    const result = link({ destination: null }, makeContext({ entering: true, origin }));

    expect(renderSpy).not.toHaveBeenCalled();
    expect(origin).toHaveBeenCalled();
    expect(result).toBeNull();
  });
});
