import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";

import type { CustomRenderers, EditorHandle } from "@/shared/editor/EditorWrapper";
import type { UseEditSession } from "../hooks/useEditSession";
import type { EditableDocument } from "../types";

/**
 * EditorPane 은 s16 단일 EditorWrapper(mode:"edit", initialContent=document.content)를
 * 렌더하고 onReady 핸들을 useEditSession.bindHandle 에 결선하며, 취소 컨트롤을 노출하고
 * s21 seam 슬롯(onImagePaste/onFileDrop)을 그대로 통과 노출한다(자체 저장 버튼·자체 에디터
 * 인스턴스·업로드 동작 없음).
 *
 * EditorWrapper 는 내부적으로 Toast UI Editor 를 인스턴스화하는 heavy 컴포넌트이므로
 * 여기서는 lightweight stub 으로 모킹하여 수신 props 를 기록하고 onReady 를 임의 핸들로
 * 발화할 수 있게 한다(Req 1.2, 1.3, 3.1, 4.1, 7.5, 7.7).
 */

interface RecordedProps {
  mode: "edit" | "read";
  initialContent?: string;
  onReady?: (handle: EditorHandle) => void;
  onImagePaste?: (file: File) => void;
  onFileDrop?: (file: File) => void;
  renderers?: CustomRenderers;
}

const wrapperCalls: RecordedProps[] = [];
const fakeHandle: EditorHandle = {
  getMarkdown: () => "current md",
  insert: () => {},
  replaceRange: () => {},
};

vi.mock("@/shared/editor/EditorWrapper", () => ({
  EditorWrapper: (props: RecordedProps) => {
    wrapperCalls.push(props);
    return (
      <div data-testid="editor-wrapper">
        <button
          type="button"
          data-testid="fire-ready"
          onClick={() => props.onReady?.(fakeHandle)}
        >
          fire ready
        </button>
      </div>
    );
  },
}));

import { EditorPane } from "./EditorPane";

function sampleDoc(partial: Partial<EditableDocument> = {}): EditableDocument {
  return {
    id: 42,
    workspace_id: 7,
    title: "제목",
    content: "hello md",
    current_version_id: 3,
    ...partial,
  };
}

function fakeSession(overrides: Partial<UseEditSession> = {}): UseEditSession {
  return {
    status: "editing",
    lockState: {
      kind: "self",
      lock: {
        document_id: 42,
        lock_user_id: 1,
        lock_acquired_at: "2026-01-01T00:00:00Z",
      },
    },
    document: sampleDoc(),
    error: null,
    bindHandle: vi.fn(),
    cancel: vi.fn().mockResolvedValue(undefined),
    retryAcquire: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

beforeEach(() => {
  wrapperCalls.length = 0;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("EditorPane", () => {
  it("EditorWrapper 를 mode='edit'·initialContent=document.content 로 렌더한다 (Req 1.2, 1.3)", () => {
    render(<EditorPane session={fakeSession()} />);

    expect(wrapperCalls).toHaveLength(1);
    expect(wrapperCalls[0].mode).toBe("edit");
    expect(wrapperCalls[0].initialContent).toBe("hello md");
    expect(screen.getByTestId("editor-wrapper")).toBeInTheDocument();
  });

  it("EditorWrapper 인스턴스를 정확히 1개만 렌더한다(에디터 이원화 금지) (Req 7.5)", () => {
    render(<EditorPane session={fakeSession()} />);

    expect(screen.getAllByTestId("editor-wrapper")).toHaveLength(1);
    expect(wrapperCalls).toHaveLength(1);
  });

  it("onReady 발화 시 session.bindHandle 에 핸들을 결선한다 (Req 7.5, 2.2 wiring)", () => {
    const session = fakeSession();
    render(<EditorPane session={session} />);

    fireEvent.click(screen.getByTestId("fire-ready"));

    expect(session.bindHandle).toHaveBeenCalledTimes(1);
    expect(session.bindHandle).toHaveBeenCalledWith(fakeHandle);
  });

  it("취소 버튼 클릭 시 session.cancel 을 호출한다 (Req 4.1)", () => {
    const session = fakeSession();
    render(<EditorPane session={session} />);

    fireEvent.click(screen.getByRole("button", { name: /취소/ }));

    expect(session.cancel).toHaveBeenCalledTimes(1);
  });

  it("명시적 저장 버튼을 렌더하지 않는다(이탈 자동저장) (Req 3.1)", () => {
    render(<EditorPane session={fakeSession()} />);

    expect(screen.queryByRole("button", { name: /저장/ })).toBeNull();
  });

  it("onImagePaste/onFileDrop 를 EditorWrapper 로 그대로 통과 노출한다 (Req 7.7 seam)", () => {
    const onImagePaste = vi.fn();
    const onFileDrop = vi.fn();
    render(
      <EditorPane
        session={fakeSession()}
        onImagePaste={onImagePaste}
        onFileDrop={onFileDrop}
      />,
    );

    expect(wrapperCalls[0].onImagePaste).toBe(onImagePaste);
    expect(wrapperCalls[0].onFileDrop).toBe(onFileDrop);
  });

  it("session.document == null 이면 EditorWrapper 를 렌더하지 않는다(콘텐츠 없이 마운트 금지) (Req 7.5)", () => {
    render(<EditorPane session={fakeSession({ document: null })} />);

    expect(screen.queryByTestId("editor-wrapper")).toBeNull();
    expect(wrapperCalls).toHaveLength(0);
  });

  it("renderers 로 주입한 객체를 동일 참조로 EditorWrapper 에 통과한다 (Req 2.3)", () => {
    const renderers = {
      customImageRenderer: () => document.createElement("img"),
    } as CustomRenderers;
    render(<EditorPane session={fakeSession()} renderers={renderers} />);

    // 동일 참조(identity) — 렌더 경로를 재구성/이원화하지 않고 그대로 통과한다.
    expect(wrapperCalls[0].renderers).toBe(renderers);
  });

  it("onReady 발화 시 준비된 단일 handle 을 bindHandle·onEditorReady 양쪽에 동일 참조로 1회씩 분배한다 (D1, Req 5.1)", () => {
    const session = fakeSession();
    const onEditorReady = vi.fn();
    const mockHandle = {
      getMarkdown: () => "md",
      insert: () => {},
      replaceRange: () => {},
    } as EditorHandle;
    render(<EditorPane session={session} onEditorReady={onEditorReady} />);

    // stub 이 수신한 onReady 를 캡처해 준비된 handle 로 발화한다.
    const onReady = wrapperCalls[0].onReady;
    expect(onReady).toBeTypeOf("function");
    onReady!(mockHandle);

    // 자동저장 경로와 업로드 브리지 경로가 각 1회, 동일 handle 참조를 공유한다.
    expect(session.bindHandle).toHaveBeenCalledTimes(1);
    expect(session.bindHandle).toHaveBeenCalledWith(mockHandle);
    expect(onEditorReady).toHaveBeenCalledTimes(1);
    expect(onEditorReady).toHaveBeenCalledWith(mockHandle);
    // 두 소비처가 받은 인자가 동일 참조임을 명시 확인(D1 단일 handle 공유).
    expect((session.bindHandle as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      (onEditorReady.mock.calls[0][0] as EditorHandle),
    );
    expect(onEditorReady.mock.calls[0][0]).toBe(mockHandle);
  });

  it("onEditorReady 미주입 시 bindHandle 만 결선되고 오류가 없다(하위 호환)", () => {
    const session = fakeSession();
    const mockHandle = {
      getMarkdown: () => "md",
      insert: () => {},
      replaceRange: () => {},
    } as EditorHandle;
    render(<EditorPane session={session} />);

    const onReady = wrapperCalls[0].onReady;
    expect(onReady).toBeTypeOf("function");
    expect(() => onReady!(mockHandle)).not.toThrow();

    expect(session.bindHandle).toHaveBeenCalledTimes(1);
    expect(session.bindHandle).toHaveBeenCalledWith(mockHandle);
  });
});
