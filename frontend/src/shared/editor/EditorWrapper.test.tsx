import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

/**
 * Toast UI Editor 는 ProseMirror 로 DOM 을 무겁게 조작하여 jsdom 에서 정상
 * 인스턴스화되지 않는다. 따라서 `@toast-ui/editor` 모듈을 모킹하고, 래퍼가
 *   - mode=edit → Editor 생성자(WYSIWYG 기본 + markdown 토글 미차단)
 *   - mode=read → Viewer factory + `.readonly-prose` 컨테이너
 *   - onReady 핸들의 getMarkdown() 이 현재 콘텐츠 반환
 * 을 만족하는지 관측한다.
 */

const editorCtorSpy = vi.fn<(options: Record<string, unknown>) => void>();
const factorySpy = vi.fn<(options: Record<string, unknown>) => void>();
const destroySpy = vi.fn();
const insertTextSpy = vi.fn<(text: string) => void>();
const replaceSelectionSpy =
  vi.fn<(text: string, start?: unknown, end?: unknown) => void>();
const onSpy = vi.fn<(type: string, handler: () => void) => void>();
const offSpy = vi.fn<(type: string) => void>();
// getEditorElements().mdPreview 에 채울 HTML — 편집 모드 Preview 수식 렌더 테스트가 주입한다.
let mdPreviewHtml = "";
// 마지막으로 반환된 안정적 mdPreview 요소(테스트가 renderMathIn 결과를 검증하려 참조).
let lastMdPreview: HTMLElement | null = null;
const MOCK_MARKDOWN = "# mock markdown\n\nbody";

vi.mock("@toast-ui/editor", () => {
  class MockEditor {
    constructor(options: Record<string, unknown>) {
      editorCtorSpy(options);
    }

    getMarkdown(): string {
      return MOCK_MARKDOWN;
    }

    // 6.2 capability: 커서 삽입.
    insertText(text: string): void {
      insertTextSpy(text);
    }

    // 6.2 capability: 범위 치환(placeholder→최종 참조).
    replaceSelection(text: string, start?: unknown, end?: unknown): void {
      replaceSelectionSpy(text, start, end);
    }

    // 편집 모드 이벤트 구독(Preview 수식 렌더 결선용). 타입별 핸들러를 기록한다.
    on(type: string, handler: () => void): void {
      onSpy(type, handler);
    }

    off(type: string): void {
      offSpy(type);
    }

    // 편집 표면 DOM 슬롯. Preview 요소는 안정적으로 캐시하여(테스트가 검증) 주입 HTML 로 채운다.
    getEditorElements(): {
      mdEditor: HTMLElement;
      mdPreview: HTMLElement;
      wwEditor: HTMLElement;
    } {
      if (lastMdPreview === null) {
        lastMdPreview = document.createElement("div");
        lastMdPreview.innerHTML = mdPreviewHtml;
      }
      return {
        mdEditor: document.createElement("div"),
        mdPreview: lastMdPreview,
        wwEditor: document.createElement("div"),
      };
    }

    destroy(): void {
      destroySpy();
    }

    static factory(options: Record<string, unknown>): MockEditor {
      factorySpy(options);
      return new MockEditor(options);
    }
  }

  return { default: MockEditor };
});

// CSS 사이드이펙트 import 는 vitest(css:true)가 처리하므로 별도 모킹 불필요.

import { EditorWrapper } from "@/shared/editor/EditorWrapper";
import type { EditorHandle } from "@/shared/editor/EditorWrapper";

beforeEach(() => {
  editorCtorSpy.mockClear();
  factorySpy.mockClear();
  destroySpy.mockClear();
  insertTextSpy.mockClear();
  replaceSelectionSpy.mockClear();
  onSpy.mockClear();
  offSpy.mockClear();
  mdPreviewHtml = "";
  lastMdPreview = null;
});

afterEach(() => {
  cleanup();
});

describe("EditorWrapper — Toast UI 단일 래퍼 (8.1~8.5)", () => {
  it("mode=edit 는 Editor 를 markdown(Write) 기본으로 생성하고 모드 토글을 차단하지 않는다 (8.2)", () => {
    render(<EditorWrapper mode="edit" initialContent="hello" />);

    // Editor 생성자가 호출되고 Viewer factory 는 호출되지 않는다(편집 경로).
    expect(editorCtorSpy).toHaveBeenCalledTimes(1);
    expect(factorySpy).not.toHaveBeenCalled();

    const options = editorCtorSpy.mock.calls[0][0];
    // markdown(Write) 기본.
    expect(options.initialEditType).toBe("markdown");
    expect(options.initialValue).toBe("hello");
    // 모드 스위치를 강제로 숨기지 않는다 → WYSIWYG 토글 사용 가능.
    expect(options.hideModeSwitch).not.toBe(true);
    // viewer 모드가 아니다.
    expect(options.viewer).not.toBe(true);
    // el 컨테이너가 주입된다.
    expect(options.el).toBeInstanceOf(HTMLElement);
  });

  it("mode=edit 는 afterPreviewRender 에 Preview 수식 렌더를 결선하고 unmount 시 해제한다", () => {
    // Preview(markdown 모드 출력 DOM)에 수식이 들어있다고 가정한다.
    mdPreviewHtml = "<p>미리보기 $x+y=1$ 끝</p>";
    const { unmount } = render(<EditorWrapper mode="edit" initialContent="x" />);

    // afterPreviewRender 이벤트에 핸들러가 구독된다.
    const call = onSpy.mock.calls.find(([type]) => type === "afterPreviewRender");
    expect(call).toBeDefined();

    // 핸들러 실행 시 Preview DOM 에 실제 KaTeX 가 렌더된다(모킹 아님 — 실제 renderMathIn).
    const handler = call![1];
    handler();
    expect(lastMdPreview).not.toBeNull();
    expect(lastMdPreview!.querySelector(".katex")).not.toBeNull();

    // WYSIWYG 편집 표면(wwEditor)에는 수식을 렌더하지 않는다 — 현 상태 유지.
    expect(lastMdPreview!.textContent).not.toContain("$x+y=1$");

    // unmount 시 이벤트 구독을 해제한다(리스너 누수 방지).
    unmount();
    expect(offSpy).toHaveBeenCalledWith("afterPreviewRender");
  });

  it("mode=read 는 Viewer factory 로 렌더하고 .readonly-prose 컨테이너 안에 위치한다 (8.3)", () => {
    const { container } = render(
      <EditorWrapper mode="read" initialContent="readme" />,
    );

    // Viewer factory 경로(viewer:true), Editor 생성 경로 아님.
    expect(factorySpy).toHaveBeenCalledTimes(1);
    const options = factorySpy.mock.calls[0][0];
    expect(options.viewer).toBe(true);
    expect(options.initialValue).toBe("readme");
    expect(options.el).toBeInstanceOf(HTMLElement);

    // 공용 prose 컨테이너(ReadOnlyProse 소비)가 DOM 에 존재한다.
    const prose = container.querySelector(".readonly-prose");
    expect(prose).not.toBeNull();
    // viewer 가 mount 되는 el 은 prose 컨테이너 하위에 있다.
    expect(prose?.contains(options.el as HTMLElement)).toBe(true);
  });

  it("onReady 핸들의 getMarkdown() 이 현재(edit) 콘텐츠를 반환한다 (8.4)", () => {
    let handle: EditorHandle | undefined;
    render(
      <EditorWrapper
        mode="edit"
        initialContent="hello"
        onReady={(h) => {
          handle = h;
        }}
      />,
    );

    expect(handle).toBeDefined();
    expect(handle?.getMarkdown()).toBe(MOCK_MARKDOWN);
  });

  it("mode=read 의 onReady 핸들 getMarkdown() 은 주입된 콘텐츠를 반영한다 (8.4)", () => {
    let handle: EditorHandle | undefined;
    render(
      <EditorWrapper
        mode="read"
        initialContent="readme content"
        onReady={(h) => {
          handle = h;
        }}
      />,
    );

    expect(handle).toBeDefined();
    expect(handle?.getMarkdown()).toBe("readme content");
  });

  it("동일 컴포넌트 하나로 edit/read 양 모드를 처리한다 — 단일 진입점 (8.1)", () => {
    // 별도 컴포넌트 없이 같은 <EditorWrapper> 로 두 모드를 렌더.
    const editRender = render(<EditorWrapper mode="edit" />);
    expect(editorCtorSpy).toHaveBeenCalledTimes(1);
    expect(factorySpy).not.toHaveBeenCalled();
    editRender.unmount();

    render(<EditorWrapper mode="read" />);
    expect(factorySpy).toHaveBeenCalledTimes(1);
  });

  it("언마운트 시 Toast 인스턴스를 정리한다(핸들 누수 방지)", () => {
    const { unmount } = render(<EditorWrapper mode="edit" initialContent="x" />);
    expect(destroySpy).not.toHaveBeenCalled();
    unmount();
    expect(destroySpy).toHaveBeenCalledTimes(1);
  });
});

describe("EditorWrapper — capability 슬롯 (8.6~8.8)", () => {
  it("renderers.customHTMLRenderer 를 edit 모드 Editor 생성자에 그대로 위임한다 (8.8 edit)", () => {
    const customHTMLRenderer = { paragraph: () => null };
    render(
      <EditorWrapper mode="edit" renderers={{ customHTMLRenderer }} />,
    );

    expect(editorCtorSpy).toHaveBeenCalledTimes(1);
    const options = editorCtorSpy.mock.calls[0][0];
    // 위임: 래퍼가 caller 의 customHTMLRenderer 를 참조 보존하여 전달.
    expect(options.customHTMLRenderer).toBe(customHTMLRenderer);
  });

  it("동일 renderers.customHTMLRenderer 를 read 모드 Viewer factory 에도 전달한다 — 단일 렌더 경로 (8.8 read)", () => {
    const customHTMLRenderer = { paragraph: () => null };
    render(
      <EditorWrapper mode="read" renderers={{ customHTMLRenderer }} />,
    );

    expect(factorySpy).toHaveBeenCalledTimes(1);
    const options = factorySpy.mock.calls[0][0];
    expect(options.viewer).toBe(true);
    // 양 모드가 동일 override 를 소비(렌더 경로 이원화 없음).
    expect(options.customHTMLRenderer).toBe(customHTMLRenderer);
  });

  it("customImageRenderer 를 edit·read 양 모드에서 Toast image 컨버터로 결선한다 (8.8)", () => {
    const rendered: string[] = [];
    const customImageRenderer = (ref: string): HTMLElement => {
      rendered.push(ref);
      const img = document.createElement("img");
      img.setAttribute("data-ref", ref);
      return img;
    };

    // edit 모드.
    const editRender = render(
      <EditorWrapper mode="edit" renderers={{ customImageRenderer }} />,
    );
    const editRenderer = editorCtorSpy.mock.calls[0][0]
      .customHTMLRenderer as Record<
      string,
      (node: { destination: string | null }) => { type: string; content: string }
    >;
    expect(typeof editRenderer.image).toBe("function");
    const editToken = editRenderer.image({ destination: "/attachments/42" });
    expect(rendered).toContain("/attachments/42");
    expect(editToken.type).toBe("html");
    expect(editToken.content).toContain('data-ref="/attachments/42"');
    editRender.unmount();

    // read 모드 — 동일 override 가 Viewer 에도 결선된다.
    render(<EditorWrapper mode="read" renderers={{ customImageRenderer }} />);
    const readRenderer = factorySpy.mock.calls[0][0].customHTMLRenderer as Record<
      string,
      (node: { destination: string | null }) => { type: string; content: string }
    >;
    expect(typeof readRenderer.image).toBe("function");
    readRenderer.image({ destination: "/attachments/99" });
    expect(rendered).toContain("/attachments/99");
  });

  it("onImagePaste: 붙여넣기/드롭 이미지 blob 훅이 File 과 함께 콜백을 호출한다 (8.6)", () => {
    const onImagePaste = vi.fn<(file: File) => void>();
    render(<EditorWrapper mode="edit" onImagePaste={onImagePaste} />);

    const options = editorCtorSpy.mock.calls[0][0];
    const hooks = options.hooks as {
      addImageBlobHook: (blob: Blob, cb: (url: string) => void) => void;
    };
    expect(typeof hooks.addImageBlobHook).toBe("function");

    const blob = new Blob(["x"], { type: "image/png" });
    hooks.addImageBlobHook(blob, () => {});

    expect(onImagePaste).toHaveBeenCalledTimes(1);
    const arg = onImagePaste.mock.calls[0][0];
    expect(arg).toBeInstanceOf(File);
    expect(arg.type).toBe("image/png");
  });

  it("onFileDrop: 에디터 루트의 drop 이벤트에서 dataTransfer.files 를 콜백으로 전달한다 (8.6)", () => {
    const onFileDrop = vi.fn<(file: File) => void>();
    render(<EditorWrapper mode="edit" onFileDrop={onFileDrop} />);

    const el = editorCtorSpy.mock.calls[0][0].el as HTMLElement;
    const file = new File(["data"], "note.txt", { type: "text/plain" });
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", {
      value: { files: [file] },
    });
    el.dispatchEvent(event);

    expect(onFileDrop).toHaveBeenCalledTimes(1);
    expect(onFileDrop.mock.calls[0][0]).toBe(file);
  });

  it("handle.insert(text) 는 편집 인스턴스의 insertText 를 호출한다 (8.7)", () => {
    let handle: EditorHandle | undefined;
    render(
      <EditorWrapper
        mode="edit"
        onReady={(h) => {
          handle = h;
        }}
      />,
    );

    handle?.insert("x");
    expect(insertTextSpy).toHaveBeenCalledTimes(1);
    expect(insertTextSpy).toHaveBeenCalledWith("x");
  });

  it("handle.replaceRange(from,to,text) 는 정규화된 좌표로 범위 치환을 호출한다 (8.7)", () => {
    let handle: EditorHandle | undefined;
    render(
      <EditorWrapper
        mode="edit"
        onReady={(h) => {
          handle = h;
        }}
      />,
    );

    handle?.replaceRange([0, 0], [0, 3], "ref");
    expect(replaceSelectionSpy).toHaveBeenCalledTimes(1);
    expect(replaceSelectionSpy).toHaveBeenCalledWith("ref", [0, 0], [0, 3]);
  });

  it("read 모드에서 insert/replaceRange 는 무해한 no-op(편집 전용 mutation) 이다 (8.7)", () => {
    let handle: EditorHandle | undefined;
    render(
      <EditorWrapper
        mode="read"
        initialContent="ro"
        onReady={(h) => {
          handle = h;
        }}
      />,
    );

    expect(() => handle?.insert("x")).not.toThrow();
    expect(() => handle?.replaceRange([0, 0], [0, 1], "y")).not.toThrow();
    expect(insertTextSpy).not.toHaveBeenCalled();
    expect(replaceSelectionSpy).not.toHaveBeenCalled();
  });

  it("capability 제공 시에도 단일 인스턴스만 생성한다(포크 없음)", () => {
    render(
      <EditorWrapper
        mode="edit"
        onImagePaste={() => {}}
        onFileDrop={() => {}}
        renderers={{
          customImageRenderer: () => document.createElement("img"),
          customHTMLRenderer: {},
        }}
        onReady={() => {}}
      />,
    );

    // edit 인스턴스 1개, Viewer factory 미호출 — 포크/이중 인스턴스 없음.
    expect(editorCtorSpy).toHaveBeenCalledTimes(1);
    expect(factorySpy).not.toHaveBeenCalled();
  });
});
