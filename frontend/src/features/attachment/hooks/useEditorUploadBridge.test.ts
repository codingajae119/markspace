import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";

import {
  useEditorUploadBridge,
  locateToken,
} from "./useEditorUploadBridge";
import type { InsertContext } from "./useAttachmentUpload";
import { useAttachmentUpload } from "./useAttachmentUpload";
import { buildPlaceholderToken } from "../lib/attachmentReference";
import type { EditorHandle } from "@/shared/editor/EditorWrapper";

/**
 * useEditorUploadBridge 는 s16 EditorWrapper 이벤트/EditorHandle 계약을 소비해 업로드 훅에
 * 결선하는 소비 어댑터다. 다음 관측 가능한 계약을 고정한다:
 *  - paste → startUpload({ file, fileName, kind:"image" }), drop → startUpload({ file, fileName })(kind 없음).
 *  - canUpload:false 또는 documentId:null 이면 진입점 방어적 비활성(startUpload 미호출).
 *  - onReady(handle) 저장 후 InsertContext 가 handle.insert/replaceRange 로 결선.
 * useAttachmentUpload 를 모킹하여 브리지를 격리하고, 주입된 InsertContext 를 포획해 어댑터를
 * 직접 검증한다(Requirements 1.1·1.2·1.4·1.6·6.5·7.5).
 */
vi.mock("./useAttachmentUpload", () => ({
  useAttachmentUpload: vi.fn(),
}));

const useAttachmentUploadMock = useAttachmentUpload as unknown as Mock;

let startUploadMock: Mock;
let capturedDocumentId: number;
let capturedInsert: InsertContext;

beforeEach(() => {
  startUploadMock = vi.fn(() => Promise.resolve(null));
  capturedInsert = { insertPlaceholder: vi.fn(), replaceToken: vi.fn() };
  useAttachmentUploadMock.mockReset();
  useAttachmentUploadMock.mockImplementation(
    (documentId: number, insert: InsertContext) => {
      capturedDocumentId = documentId;
      capturedInsert = insert;
      return { startUpload: startUploadMock, uploads: new Map() };
    },
  );
});

function makeHandle(markdown = ""): EditorHandle {
  return {
    getMarkdown: vi.fn(() => markdown),
    insert: vi.fn(),
    replaceRange: vi.fn(),
  };
}

function file(name = "pic.png"): File {
  return new File([new Blob(["x"])], name, { type: "image/png" });
}

describe("locateToken", () => {
  it("finds a token on the first line (1-based line, 0-based ch)", () => {
    const token = buildPlaceholderToken("upload-1");
    const range = locateToken(`ab${token}cd`, token);
    expect(range).toEqual({ from: [1, 2], to: [1, 2 + token.length] });
  });

  it("finds a token on a later line", () => {
    const token = buildPlaceholderToken("upload-2");
    const md = `line one\nx${token}`;
    const range = locateToken(md, token);
    expect(range).toEqual({ from: [2, 1], to: [2, 1 + token.length] });
  });

  it("returns null when the token is absent", () => {
    expect(locateToken("no token here", buildPlaceholderToken("upload-3"))).toBeNull();
  });
});

describe("useEditorUploadBridge — gating (defensive disable)", () => {
  it("does NOT upload when canUpload is false", () => {
    const { result } = renderHook(() =>
      useEditorUploadBridge({ documentId: 42, canUpload: false }),
    );
    act(() => {
      result.current.onImagePaste(file());
      result.current.onFileDrop(file("doc.pdf"));
    });
    expect(startUploadMock).not.toHaveBeenCalled();
  });

  it("does NOT upload when documentId is null", () => {
    const { result } = renderHook(() =>
      useEditorUploadBridge({ documentId: null, canUpload: true }),
    );
    act(() => {
      result.current.onImagePaste(file());
      result.current.onFileDrop(file("doc.pdf"));
    });
    expect(startUploadMock).not.toHaveBeenCalled();
  });
});

describe("useEditorUploadBridge — upload wiring", () => {
  it("paste triggers upload with kind:image and fileName from file.name", () => {
    const { result } = renderHook(() =>
      useEditorUploadBridge({ documentId: 42, canUpload: true }),
    );
    const f = file("shot.png");
    act(() => {
      result.current.onImagePaste(f);
    });
    expect(startUploadMock).toHaveBeenCalledTimes(1);
    expect(startUploadMock).toHaveBeenCalledWith({
      file: f,
      fileName: "shot.png",
      kind: "image",
    });
  });

  it("drop triggers upload with NO kind (backend infers)", () => {
    const { result } = renderHook(() =>
      useEditorUploadBridge({ documentId: 42, canUpload: true }),
    );
    const f = file("report.pdf");
    act(() => {
      result.current.onFileDrop(f);
    });
    expect(startUploadMock).toHaveBeenCalledTimes(1);
    expect(startUploadMock).toHaveBeenCalledWith({ file: f, fileName: "report.pdf" });
  });

  it("passes the resolved documentId to useAttachmentUpload", () => {
    renderHook(() => useEditorUploadBridge({ documentId: 7, canUpload: true }));
    expect(capturedDocumentId).toBe(7);
  });
});

describe("useEditorUploadBridge — InsertContext adapter over EditorHandle", () => {
  it("insertPlaceholder forwards the token to handle.insert after onReady", () => {
    const { result } = renderHook(() =>
      useEditorUploadBridge({ documentId: 42, canUpload: true }),
    );
    const token = buildPlaceholderToken("upload-1");
    const handle = makeHandle();
    act(() => {
      result.current.onReady(handle);
      capturedInsert.insertPlaceholder("upload-1", token);
    });
    expect(handle.insert).toHaveBeenCalledWith(token);
  });

  it("replaceToken recomputes range from getMarkdown and calls handle.replaceRange", () => {
    const { result } = renderHook(() =>
      useEditorUploadBridge({ documentId: 42, canUpload: true }),
    );
    const token = buildPlaceholderToken("upload-1");
    const handle = makeHandle(`intro\n${token}`);
    act(() => {
      result.current.onReady(handle);
      capturedInsert.replaceToken("upload-1", "![pic](/attachments/9)");
    });
    expect(handle.replaceRange).toHaveBeenCalledWith(
      [2, 0],
      [2, token.length],
      "![pic](/attachments/9)",
    );
  });

  it("replaceToken is a safe no-op when the token is not found", () => {
    const { result } = renderHook(() =>
      useEditorUploadBridge({ documentId: 42, canUpload: true }),
    );
    const handle = makeHandle("no placeholder here");
    act(() => {
      result.current.onReady(handle);
      capturedInsert.replaceToken("upload-1", "whatever");
    });
    expect(handle.replaceRange).not.toHaveBeenCalled();
  });

  it("InsertContext callbacks are safe no-ops before onReady (no handle)", () => {
    renderHook(() => useEditorUploadBridge({ documentId: 42, canUpload: true }));
    expect(() => {
      capturedInsert.insertPlaceholder("upload-1", buildPlaceholderToken("upload-1"));
      capturedInsert.replaceToken("upload-1", "x");
    }).not.toThrow();
  });
});
