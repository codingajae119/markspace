import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";

import { ApiError } from "@/shared/api/errors";
import type { DocumentRead } from "../types";

/**
 * DocumentViewer 는 s16 단일 EditorWrapper(read)를 재사용하여 본문을 렌더한다.
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

describe("DocumentViewer — 단일 EditorWrapper(read) 재사용 (Req 7.1~7.6)", () => {
  it("마운트 시 getDocument(documentId) 를 호출하고, 로드 후 read 뷰어를 content(markdown)로 렌더한다 (Req 7.1~7.3)", async () => {
    const doc = sampleDoc({ id: 7 });
    getDocumentMock.mockResolvedValue(doc);

    render(<DocumentViewer documentId={7} canEdit={false} />);

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

  it("canEdit=true 면 편집 버튼을 렌더하고 클릭 시 onEnterEdit(documentId) 를 호출한다 (Req 7.4, 7.5)", async () => {
    const doc = sampleDoc({ id: 9 });
    getDocumentMock.mockResolvedValue(doc);
    const onEnterEdit = vi.fn<(documentId: number) => void>();

    render(
      <DocumentViewer documentId={9} canEdit={true} onEnterEdit={onEnterEdit} />,
    );

    const editButton = await screen.findByRole("button", { name: "편집" });
    fireEvent.click(editButton);
    expect(onEnterEdit).toHaveBeenCalledWith(9);
  });

  it("canEdit=false(뷰어) 면 편집·삭제 버튼을 렌더하지 않는다 (Req 7.4, 7.5, 5.1)", async () => {
    getDocumentMock.mockResolvedValue(sampleDoc({ id: 3 }));

    render(<DocumentViewer documentId={3} canEdit={false} />);

    await waitFor(() => {
      expect(factorySpy).toHaveBeenCalled();
    });
    expect(screen.queryByRole("button", { name: "편집" })).toBeNull();
    expect(screen.queryByRole("button", { name: "삭제" })).toBeNull();
  });

  it("canEdit=true 면 삭제 버튼을 편집 버튼과 함께 렌더한다 (Req 5.1)", async () => {
    getDocumentMock.mockResolvedValue(sampleDoc({ id: 9 }));

    render(<DocumentViewer documentId={9} canEdit={true} />);

    // 편집·삭제 버튼이 함께(편집 옆) 노출된다.
    expect(await screen.findByRole("button", { name: "편집" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "삭제" })).toBeInTheDocument();
  });

  it("삭제 → ConfirmDialog 확인 시 onDelete(documentId) 호출 후 닫힘 (Req 5.1)", async () => {
    getDocumentMock.mockResolvedValue(sampleDoc({ id: 9, title: "지울 문서" }));
    const onDelete = vi.fn<(documentId: number) => void>();

    render(<DocumentViewer documentId={9} canEdit={true} onDelete={onDelete} />);

    // 초기엔 확인 모달이 없다.
    const deleteButton = await screen.findByRole("button", { name: "삭제" });
    expect(screen.queryByRole("dialog")).toBeNull();

    // 삭제 클릭 → 확인 모달이 뜨고(문서 제목 안내), 아직 seam 은 호출되지 않는다.
    fireEvent.click(deleteButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    // 확인 → onDelete(documentId) 호출 후 모달이 닫힌다(변이는 상위 페이지가 소유).
    fireEvent.click(screen.getByRole("button", { name: "휴지통으로 이동" }));
    expect(onDelete).toHaveBeenCalledWith(9);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("삭제 확인 모달에서 취소하면 onDelete 를 호출하지 않고 닫힌다 (Req 5.1)", async () => {
    getDocumentMock.mockResolvedValue(sampleDoc({ id: 4 }));
    const onDelete = vi.fn<(documentId: number) => void>();

    render(<DocumentViewer documentId={4} canEdit={true} onDelete={onDelete} />);

    fireEvent.click(await screen.findByRole("button", { name: "삭제" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("getDocument 가 ApiError 로 실패하면 ErrorMessage 를 보이고 본문(에디터)은 렌더하지 않는다 (Req 7.6)", async () => {
    const apiError = new ApiError({
      status: 404,
      code: "not_found",
      message: "문서를 찾을 수 없습니다.",
    });
    getDocumentMock.mockRejectedValue(apiError);

    render(<DocumentViewer documentId={404} canEdit={true} />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("문서를 찾을 수 없습니다.");
    // 본문 read 뷰어는 렌더하지 않는다.
    expect(factorySpy).not.toHaveBeenCalled();
    // 실패 시 편집 진입 seam 도 노출하지 않는다.
    expect(screen.queryByRole("button", { name: "편집" })).toBeNull();
  });

  it("documentId 가 바뀌면 새 문서를 재조회한다 (latest-wins)", async () => {
    getDocumentMock.mockImplementation((id) =>
      Promise.resolve(sampleDoc({ id })),
    );

    const { rerender } = render(
      <DocumentViewer documentId={1} canEdit={false} />,
    );
    await waitFor(() => {
      expect(getDocumentMock).toHaveBeenCalledWith(1);
    });

    rerender(<DocumentViewer documentId={2} canEdit={false} />);
    await waitFor(() => {
      expect(getDocumentMock).toHaveBeenCalledWith(2);
    });
  });
});
