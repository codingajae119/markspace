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
const MOCK_MARKDOWN = "# mock markdown\n\nbody";

vi.mock("@toast-ui/editor", () => {
  class MockEditor {
    constructor(options: Record<string, unknown>) {
      editorCtorSpy(options);
    }

    getMarkdown(): string {
      return MOCK_MARKDOWN;
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
});

afterEach(() => {
  cleanup();
});

describe("EditorWrapper — Toast UI 단일 래퍼 (8.1~8.5)", () => {
  it("mode=edit 는 Editor 를 WYSIWYG 기본으로 생성하고 markdown 토글을 차단하지 않는다 (8.2)", () => {
    render(<EditorWrapper mode="edit" initialContent="hello" />);

    // Editor 생성자가 호출되고 Viewer factory 는 호출되지 않는다(편집 경로).
    expect(editorCtorSpy).toHaveBeenCalledTimes(1);
    expect(factorySpy).not.toHaveBeenCalled();

    const options = editorCtorSpy.mock.calls[0][0];
    // WYSIWYG 기본.
    expect(options.initialEditType).toBe("wysiwyg");
    expect(options.initialValue).toBe("hello");
    // markdown 토글(모드 스위치)을 강제로 숨기지 않는다 → markdown 토글 사용 가능.
    expect(options.hideModeSwitch).not.toBe(true);
    // viewer 모드가 아니다.
    expect(options.viewer).not.toBe(true);
    // el 컨테이너가 주입된다.
    expect(options.el).toBeInstanceOf(HTMLElement);
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
