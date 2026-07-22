import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { ApiError } from "@/shared/api/errors";
import type { DocumentRead } from "../types";

/**
 * DocumentViewer 는 s16 단일 EditorWrapper(read)를 재사용하여 본문을 렌더한다(순수 읽기 뷰;
 * 편집·삭제 seam 은 상단 DocumentToolbar 가 소유하므로 여기서 검증하지 않는다).
 * EditorWrapper 는 내부적으로 Toast UI Editor 를 인스턴스화하는데 jsdom 에서 동작하지
 * 않으므로 `@toast-ui/editor` 를 EditorWrapper.test.tsx 와 동일한 mock 형태로 모킹한다.
 *   - read 경로는 `Editor.factory({ viewer:true, initialValue })` 를 호출한다.
 *   - factory spy 의 initialValue 가 doc.content(markdown)이고 doc.content_html 이 아님을
 *     검증하여 "content_html 미사용·단일 read 경로" 를 증명한다.
 */

const editorCtorSpy = vi.fn<(options: Record<string, unknown>) => void>();
const factorySpy = vi.fn<(options: Record<string, unknown>) => void>();
const destroySpy = vi.fn();
const insertTextSpy = vi.fn<(text: string) => void>();
const replaceSelectionSpy =
  vi.fn<(text: string, start?: unknown, end?: unknown) => void>();
const MOCK_MARKDOWN = "# mock markdown\n\nbody";

vi.mock("@toast-ui/editor", () => {
  class MockEditor {
    constructor(options: Record<string, unknown>) {
      editorCtorSpy(options);
    }

    getMarkdown(): string {
      return MOCK_MARKDOWN;
    }

    insertText(text: string): void {
      insertTextSpy(text);
    }

    replaceSelection(text: string, start?: unknown, end?: unknown): void {
      replaceSelectionSpy(text, start, end);
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

// documentApi.getDocument 를 모킹하여 detail fetch 를 관측한다.
const getDocumentMock = vi.fn<(id: number) => Promise<DocumentRead>>();
vi.mock("../api/documentApi", () => ({
  documentApi: {
    getDocument: (id: number): Promise<DocumentRead> => getDocumentMock(id),
  },
}));

import { DocumentViewer } from "./DocumentViewer";

/** 모든 DocumentRead 필드를 채운 fixture. content 와 content_html 을 서로 다르게 둔다. */
function sampleDoc(partial: Partial<DocumentRead> = {}): DocumentRead {
  return {
    id: 7,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    workspace_id: 1,
    parent_id: null,
    title: "샘플 문서",
    status: "active",
    sort_order: "1",
    current_version_id: 42,
    created_by: 1,
    content: "# MARKDOWN BODY\n\nfrom content field",
    content_html: "<h1>HTML BODY (must NOT be used)</h1>",
    ...partial,
  };
}

beforeEach(() => {
  editorCtorSpy.mockClear();
  factorySpy.mockClear();
  destroySpy.mockClear();
  insertTextSpy.mockClear();
  replaceSelectionSpy.mockClear();
  getDocumentMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("DocumentViewer — 단일 EditorWrapper(read) 재사용 (Req 7.1~7.3, 7.6)", () => {
  it("마운트 시 getDocument(documentId) 를 호출하고, 로드 후 read 뷰어를 content(markdown)로 렌더한다 (Req 7.1~7.3)", async () => {
    const doc = sampleDoc({ id: 7 });
    getDocumentMock.mockResolvedValue(doc);

    render(<DocumentViewer documentId={7} />);

    await waitFor(() => {
      expect(getDocumentMock).toHaveBeenCalledWith(7);
    });

    // read 경로: Editor.factory({ viewer:true, initialValue: doc.content }).
    await waitFor(() => {
      expect(factorySpy).toHaveBeenCalledTimes(1);
    });
    const options = factorySpy.mock.calls[0][0];
    expect(options.viewer).toBe(true);
    // content(markdown)를 사용하고 content_html 은 사용하지 않는다(단일 read 경로).
    expect(options.initialValue).toBe(doc.content);
    expect(options.initialValue).not.toBe(doc.content_html);
  });

  it("편집·삭제 버튼은 뷰어가 소유하지 않는다(상단 DocumentToolbar 소유, Req 5.1·7.4·7.5)", async () => {
    getDocumentMock.mockResolvedValue(sampleDoc({ id: 3 }));

    render(<DocumentViewer documentId={3} />);

    await waitFor(() => {
      expect(factorySpy).toHaveBeenCalled();
    });
    expect(screen.queryByRole("button", { name: "편집" })).toBeNull();
    expect(screen.queryByRole("button", { name: "삭제" })).toBeNull();
  });

  it("getDocument 가 ApiError 로 실패하면 ErrorMessage 를 보이고 본문(에디터)은 렌더하지 않는다 (Req 7.6)", async () => {
    const apiError = new ApiError({
      status: 404,
      code: "not_found",
      message: "문서를 찾을 수 없습니다.",
    });
    getDocumentMock.mockRejectedValue(apiError);

    render(<DocumentViewer documentId={404} />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("문서를 찾을 수 없습니다.");
    // 본문 read 뷰어는 렌더하지 않는다.
    expect(factorySpy).not.toHaveBeenCalled();
  });

  it("documentId 가 바뀌면 새 문서를 재조회한다 (latest-wins)", async () => {
    getDocumentMock.mockImplementation((id) =>
      Promise.resolve(sampleDoc({ id })),
    );

    const { rerender } = render(<DocumentViewer documentId={1} />);
    await waitFor(() => {
      expect(getDocumentMock).toHaveBeenCalledWith(1);
    });

    rerender(<DocumentViewer documentId={2} />);
    await waitFor(() => {
      expect(getDocumentMock).toHaveBeenCalledWith(2);
    });
  });
});
