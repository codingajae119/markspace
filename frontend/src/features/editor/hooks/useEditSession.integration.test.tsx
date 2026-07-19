import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useEditSession } from "./useEditSession";
import { lockVersionApi } from "../api/lockVersionApi";
import { ApiError } from "@/shared/api/errors";
import type { EditorHandle } from "@/shared/editor/EditorWrapper";
import type { DocumentLockRead, EditableDocument } from "../types";

/**
 * useEditSession 은 마운트 시 잠금 획득(lockDocument→resolveLockState)·self 면 초기
 * 콘텐츠 로드(getDocument)·편집 활성, 언마운트/라우트 전환 cleanup 에서 잠금 보유·미취소
 * 시에만 **정확히 1회** saveDocument 를 호출하는 생명주기를 오케스트레이션한다. 협력자
 * (lockVersionApi)를 모킹하고 실 resolveLockState 를 사용하여 진입 상태전이·이탈 1회 저장·
 * 취소 억제·미획득 무저장·주기저장 부재만 관찰한다
 * (Requirements 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6,
 *  4.1, 4.2, 4.3, 4.5).
 */
vi.mock("../api/lockVersionApi", () => ({
  lockVersionApi: {
    lockDocument: vi.fn(),
    getDocument: vi.fn(),
    saveDocument: vi.fn(),
    cancelEdit: vi.fn(),
    forceUnlock: vi.fn(),
    listVersions: vi.fn(),
  },
}));

const lockDocumentMock = lockVersionApi.lockDocument as unknown as Mock;
const getDocumentMock = lockVersionApi.getDocument as unknown as Mock;
const saveDocumentMock = lockVersionApi.saveDocument as unknown as Mock;
const cancelEditMock = lockVersionApi.cancelEdit as unknown as Mock;

const DOC_ID = 42;

function lockRead(): DocumentLockRead {
  return {
    document_id: DOC_ID,
    lock_user_id: 9,
    lock_acquired_at: "2026-07-19T00:00:00Z",
  };
}

function editableDoc(content = "본문 markdown"): EditableDocument {
  return {
    id: DOC_ID,
    workspace_id: 7,
    title: "문서",
    content,
    current_version_id: null,
  };
}

function apiError(status: number, code = "conflict"): ApiError {
  return new ApiError({ status, code, message: `err-${status}` });
}

function fakeHandle(markdown: string): EditorHandle {
  return {
    getMarkdown: () => markdown,
    insert: vi.fn(),
    replaceRange: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  lockDocumentMock.mockResolvedValue(lockRead());
  getDocumentMock.mockResolvedValue(editableDoc());
  saveDocumentMock.mockResolvedValue({
    id: 1,
    document_id: DOC_ID,
    created_by: 9,
    created_at: "2026-07-19T00:00:01Z",
  });
  cancelEditMock.mockResolvedValue(undefined);
});

describe("useEditSession", () => {
  it("잠금 200(self) 시 getDocument 로 초기 콘텐츠 로드 후 status=editing·document 세팅 (1.1,1.2,1.3)", async () => {
    const { result } = renderHook(() => useEditSession(DOC_ID));

    await waitFor(() => expect(result.current.status).toBe("editing"));

    expect(lockDocumentMock).toHaveBeenCalledWith(DOC_ID);
    expect(getDocumentMock).toHaveBeenCalledWith(DOC_ID);
    expect(result.current.lockState.kind).toBe("self");
    expect(result.current.document?.content).toBe("본문 markdown");
    expect(result.current.error).toBeNull();
  });

  it("잠금 409(타인) 시 status=blocked·getDocument 미호출·편집 미활성 (2.2)", async () => {
    lockDocumentMock.mockRejectedValue(apiError(409, "conflict"));

    const { result } = renderHook(() => useEditSession(DOC_ID));

    await waitFor(() => expect(result.current.status).toBe("blocked"));

    expect(getDocumentMock).not.toHaveBeenCalled();
    expect(result.current.lockState.kind).toBe("other");
    expect(result.current.document).toBeNull();
  });

  it("잠금 403 시 status=error·error 표면화·편집 미활성 (1.6)", async () => {
    lockDocumentMock.mockRejectedValue(apiError(403, "forbidden"));

    const { result } = renderHook(() => useEditSession(DOC_ID));

    await waitFor(() => expect(result.current.status).toBe("error"));

    expect(getDocumentMock).not.toHaveBeenCalled();
    expect(result.current.lockState.kind).toBe("error");
    expect(result.current.error?.status).toBe(403);
  });

  it("잠금 404 시 status=error·error 표면화 (1.6)", async () => {
    lockDocumentMock.mockRejectedValue(apiError(404, "not_found"));

    const { result } = renderHook(() => useEditSession(DOC_ID));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.status).toBe(404);
  });

  it("self+bindHandle 후 언마운트 시 saveDocument 를 {content} 로 **정확히 1회** 호출 (3.1)", async () => {
    const { result, unmount } = renderHook(() => useEditSession(DOC_ID));

    await waitFor(() => expect(result.current.status).toBe("editing"));
    act(() => {
      result.current.bindHandle(fakeHandle("md"));
    });

    unmount();

    expect(saveDocumentMock).toHaveBeenCalledTimes(1);
    expect(saveDocumentMock).toHaveBeenCalledWith(DOC_ID, { content: "md" });
  });

  it("cancel() 후 언마운트 시 이탈 저장을 억제한다(saveDocument 미호출·cancelEdit 1회) (3.5,4.1,4.2)", async () => {
    const { result, unmount } = renderHook(() => useEditSession(DOC_ID));

    await waitFor(() => expect(result.current.status).toBe("editing"));
    act(() => {
      result.current.bindHandle(fakeHandle("md"));
    });

    await act(async () => {
      await result.current.cancel();
    });

    expect(cancelEditMock).toHaveBeenCalledTimes(1);
    expect(cancelEditMock).toHaveBeenCalledWith(DOC_ID);
    expect(result.current.status).toBe("released");

    unmount();

    expect(saveDocumentMock).not.toHaveBeenCalled();
  });

  it("cancel 실패(409) 시 ApiError 를 표면화한다 (4.4)", async () => {
    cancelEditMock.mockRejectedValue(apiError(409, "conflict"));

    const { result } = renderHook(() => useEditSession(DOC_ID));
    await waitFor(() => expect(result.current.status).toBe("editing"));
    act(() => {
      result.current.bindHandle(fakeHandle("md"));
    });

    await act(async () => {
      await result.current.cancel();
    });

    expect(result.current.error?.status).toBe(409);
  });

  it("잠금 미획득(409) 후 언마운트 시 saveDocument 를 호출하지 않는다 (3.6)", async () => {
    lockDocumentMock.mockRejectedValue(apiError(409, "conflict"));

    const { result, unmount } = renderHook(() => useEditSession(DOC_ID));
    await waitFor(() => expect(result.current.status).toBe("blocked"));

    unmount();

    expect(saveDocumentMock).not.toHaveBeenCalled();
  });

  it("self 이지만 handle 미바인딩 시 언마운트 저장을 하지 않는다 (3.1 가드)", async () => {
    const { result, unmount } = renderHook(() => useEditSession(DOC_ID));
    await waitFor(() => expect(result.current.status).toBe("editing"));

    unmount();

    expect(saveDocumentMock).not.toHaveBeenCalled();
  });

  it("마운트 상태에서는(언마운트 전) 주기·debounce 저장이 없다(saveDocument 0회) (3.2)", async () => {
    const { result } = renderHook(() => useEditSession(DOC_ID));
    await waitFor(() => expect(result.current.status).toBe("editing"));
    act(() => {
      result.current.bindHandle(fakeHandle("md"));
    });

    // 이탈 없이 대기해도 저장 트리거가 없어야 한다.
    await new Promise((r) => setTimeout(r, 20));

    expect(saveDocumentMock).not.toHaveBeenCalled();
  });

  it("getDocument 실패 시 status=error·error 표면화 (1.6)", async () => {
    getDocumentMock.mockRejectedValue(apiError(404, "not_found"));

    const { result } = renderHook(() => useEditSession(DOC_ID));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.status).toBe(404);
  });

  it("retryAcquire() 는 released/saved 플래그를 리셋하고 재획득한다(재획득 후 이탈 저장 1회) (1.4)", async () => {
    // 최초 취소로 released 세팅 → retryAcquire 로 재획득 → 이탈 저장이 다시 가능해야 한다.
    const { result, unmount } = renderHook(() => useEditSession(DOC_ID));
    await waitFor(() => expect(result.current.status).toBe("editing"));
    act(() => {
      result.current.bindHandle(fakeHandle("md2"));
    });

    await act(async () => {
      await result.current.cancel();
    });
    expect(result.current.status).toBe("released");

    await act(async () => {
      await result.current.retryAcquire();
    });
    await waitFor(() => expect(result.current.status).toBe("editing"));

    unmount();

    expect(saveDocumentMock).toHaveBeenCalledTimes(1);
    expect(saveDocumentMock).toHaveBeenCalledWith(DOC_ID, { content: "md2" });
  });
});
