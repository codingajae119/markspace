import { describe, it, expect, beforeEach, vi, type Mock } from "vitest";
import type { ReactElement } from "react";

import { AttachmentImage } from "./AttachmentImage";
import { AttachmentFileLink } from "./AttachmentFileLink";
import {
  buildAttachmentRenderers,
  hydrateAttachmentsInDom,
} from "./AttachmentRenderBridge";

/**
 * AttachmentRenderBridge 는 s16 `EditorWrapper.renderers` 슬롯에 넘길 `CustomRenderers`
 * (edit·read 양 모드 공통)를 구성한다. Toast `customHTMLRenderer` 가 컨버터 반환을 **문자열**로만
 * 받으므로(비동기 React 커밋 미포착), 컨버터는 **직렬화 가능한 빈 placeholder(`data-*` 마커)** 만
 * 내보내고, 렌더 후 `hydrateDom` 이 그 마커에 인증 `AttachmentImage`·`AttachmentFileLink` 를
 * **라이브 마운트**한다(단일 렌더 경로). 라우팅/마운트만 격리 검증하기 위해 자식 컴포넌트와
 * `react-dom/client` `createRoot` 를 모킹하고, `resolveAttachmentReference` 는 실제 lib 을
 * 사용한다(Requirements 3.5, 5.3, 7.2, 7.5).
 */

// createRoot(container).render(element) 의 render 인자·unmount 를 캡처한다.
const { renderSpy, unmountSpy, createRootSpy } = vi.hoisted(() => {
  const renderSpy = vi.fn();
  const unmountSpy = vi.fn();
  const createRootSpy = vi.fn(() => ({ render: renderSpy, unmount: unmountSpy }));
  return { renderSpy, unmountSpy, createRootSpy };
});
vi.mock("react-dom/client", () => ({ createRoot: createRootSpy }));

// 자식 컴포넌트는 식별 가능한 참조로만 모킹한다(실제 렌더/HTTP 없이 라우팅만 확인).
vi.mock("./AttachmentImage", () => ({
  AttachmentImage: vi.fn(() => null),
}));
vi.mock("./AttachmentFileLink", () => ({
  AttachmentFileLink: vi.fn(() => null),
}));

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

/** html 토큰 content 문자열을 DOM 으로 파싱해 첫 요소를 반환(속성 검증용). */
function parseFirstElement(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host.firstElementChild as HTMLElement;
}

describe("AttachmentRenderBridge — placeholder 컨버터 (3.5, 5.3, 7.2, 7.5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("customImageRenderer('/attachments/7'): data-attachment-image-id=7 마커 span(원시 src 없음·즉시 마운트 없음)", () => {
    const { customImageRenderer } = buildAttachmentRenderers();
    expect(customImageRenderer).toBeDefined();

    const el = customImageRenderer!("/attachments/7");

    expect(el).toBeInstanceOf(HTMLElement);
    expect(el.tagName).toBe("SPAN");
    expect(el.getAttribute("data-attachment-image-id")).toBe("7");
    // 컨버터 단계에서는 라이브 마운트하지 않는다(직렬화 가능한 빈 마커만).
    expect(createRootSpy).not.toHaveBeenCalled();
    // 원시 /attachments src 금지.
    expect(el.outerHTML).not.toContain("<img");
    expect(el.outerHTML).not.toContain("/attachments/7");
  });

  it("customImageRenderer(비첨부 href): 마커 없는 무해 span(원시 src 없음)", () => {
    const { customImageRenderer } = buildAttachmentRenderers();

    const el = customImageRenderer!("https://evil.example/x.png");

    expect(el).toBeInstanceOf(HTMLElement);
    expect(el.hasAttribute("data-attachment-image-id")).toBe(false);
    expect(el.outerHTML).not.toContain("<img");
    expect(el.outerHTML).not.toContain("evil.example");
  });

  it("customImageRenderer(비정규 참조): 실제 resolver 규약(양의 정수만) → 마커 미부여", () => {
    const { customImageRenderer } = buildAttachmentRenderers();

    for (const ref of ["/attachments/0", "/attachments/042", "/attachments/7?x=1"]) {
      const el = customImageRenderer!(ref);
      expect(el.hasAttribute("data-attachment-image-id")).toBe(false);
    }
  });

  it("customHTMLRenderer.link(파일 첨부 /attachments/9): data-attachment-file-id·file-name 마커로 치환(즉시 마운트 없음)", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const node: ToastLinkNodeLike = { destination: "/attachments/9" };
    const ctx = makeContext({ entering: true, childrenText: "report.pdf" });
    const token = link(node, ctx);

    expect(token).toMatchObject({ type: "html" });
    const el = parseFirstElement((token as { content: string }).content);
    expect(el.getAttribute("data-attachment-file-id")).toBe("9");
    expect(el.getAttribute("data-attachment-file-name")).toBe("report.pdf");
    // 자식(링크 텍스트) 기본 렌더는 건너뛰고 html 토큰으로 치환, 기본 위임 없음.
    expect(ctx.skipChildren).toHaveBeenCalled();
    expect(ctx.origin).not.toHaveBeenCalled();
    // 컨버터 단계에서 라이브 마운트하지 않는다.
    expect(createRootSpy).not.toHaveBeenCalled();
  });

  it("customHTMLRenderer.link(파일명에 따옴표/`<`): 속성이 안전하게 이스케이프되어 원문 복원", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const token = link(
      { destination: "/attachments/9" },
      makeContext({ entering: true, childrenText: 'a"b<c>d' }),
    );

    const el = parseFirstElement((token as { content: string }).content);
    // setAttribute + outerHTML 직렬화 → 파싱 왕복 후 원문이 그대로 복원(주입 없음).
    expect(el.getAttribute("data-attachment-file-name")).toBe('a"b<c>d');
  });

  it("customHTMLRenderer.link(닫는 토큰): 첨부여도 entering=false 는 null 반환(중복 치환 없음)", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const node: ToastLinkNodeLike = { destination: "/attachments/9" };
    const token = link(node, makeContext({ entering: false, childrenText: "report.pdf" }));

    expect(token).toBeNull();
  });

  it("customHTMLRenderer.link(비첨부 링크): 미라우팅 + 기본 위임(origin)", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const defaultToken = { type: "openTag", tagName: "a" };
    const origin = vi.fn(() => defaultToken);
    const node: ToastLinkNodeLike = { destination: "https://example.com/page" };
    const result = link(node, makeContext({ entering: true, origin }));

    expect(origin).toHaveBeenCalled();
    expect(result).toBe(defaultToken);
  });

  it("customHTMLRenderer.link(destination=null): 안전하게 기본 위임", () => {
    const renderers = buildAttachmentRenderers();
    const link = (renderers.customHTMLRenderer as { link: Function }).link;

    const origin = vi.fn(() => null);
    const result = link({ destination: null }, makeContext({ entering: true, origin }));

    expect(origin).toHaveBeenCalled();
    expect(result).toBeNull();
  });
});

describe("hydrateAttachmentsInDom — placeholder 마커 라이브 마운트 (3.1, 4.3, 5.3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("이미지 마커에 AttachmentImage(id) 를, 파일 마커에 AttachmentFileLink(id, name) 를 마운트한다", () => {
    const root = document.createElement("div");
    root.innerHTML =
      '<span data-attachment-image-id="7"></span>' +
      '<span data-attachment-file-id="9" data-attachment-file-name="report.pdf"></span>';

    hydrateAttachmentsInDom(root);

    expect(createRootSpy).toHaveBeenCalledTimes(2);
    const mounted = renderSpy.mock.calls.map((c) => c[0] as ReactElement);
    const image = mounted.find((e) => e.type === AttachmentImage)!;
    const file = mounted.find((e) => e.type === AttachmentFileLink)!;
    expect((image.props as { attachmentId: number }).attachmentId).toBe(7);
    expect((file.props as { attachmentId: number }).attachmentId).toBe(9);
    expect((file.props as { fileName: string }).fileName).toBe("report.pdf");
  });

  it("반환 disposer 는 마운트한 모든 루트를 unmount 한다(오브젝트 URL 누수 방지)", () => {
    const root = document.createElement("div");
    root.innerHTML =
      '<span data-attachment-image-id="7"></span>' +
      '<span data-attachment-file-id="9" data-attachment-file-name="a.pdf"></span>';

    const dispose = hydrateAttachmentsInDom(root);
    expect(unmountSpy).not.toHaveBeenCalled();
    dispose();
    expect(unmountSpy).toHaveBeenCalledTimes(2);
  });

  it("같은 실 DOM 에 재호출돼도 이미 hydrate 된 마커는 재마운트하지 않는다(멱등)", () => {
    const root = document.createElement("div");
    root.innerHTML = '<span data-attachment-image-id="7"></span>';

    hydrateAttachmentsInDom(root);
    hydrateAttachmentsInDom(root);

    expect(createRootSpy).toHaveBeenCalledTimes(1);
  });

  it("비정규 마커 id(0·선행영)는 마운트하지 않는다", () => {
    const root = document.createElement("div");
    root.innerHTML =
      '<span data-attachment-image-id="0"></span>' +
      '<span data-attachment-image-id="042"></span>' +
      '<span data-attachment-file-id="-1" data-attachment-file-name="x"></span>';

    hydrateAttachmentsInDom(root);

    expect(createRootSpy).not.toHaveBeenCalled();
  });
});
