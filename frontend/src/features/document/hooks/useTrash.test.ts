import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useTrash } from "./useTrash";
import { documentApi } from "../api/documentApi";
import type { Page, TrashBundleRead } from "../types";
import { ApiError } from "@/shared/api/errors";

/**
 * useTrash 는 마운트/워크스페이스 변경 시 첫 페이지를 로드하고(reload·loadPage),
 * 복원(restore)·영구삭제(purge)는 백엔드 204 결과를 그대로 반영하며 실패 시 raw ApiError 를
 * 표면화한 뒤 재목록(reload)한다. documentApi 는 모킹한다 (Requirements 8.1~8.5, 8.7).
 */
vi.mock("../api/documentApi", () => ({
  documentApi: {
    listTrash: vi.fn(),
    restoreBundle: vi.fn(),
    purgeBundle: vi.fn(),
  },
}));

const listTrashMock = documentApi.listTrash as unknown as Mock;
const restoreMock = documentApi.restoreBundle as unknown as Mock;
const purgeMock = documentApi.purgeBundle as unknown as Mock;

/** TrashBundleRead 전체 필드를 채운 픽스처(부분 override 지원). */
function sampleBundle(partial: Partial<TrashBundleRead> = {}): TrashBundleRead {
  return {
    bundle_id: 1,
    root_document_id: 1,
    root_title: "휴지통 루트",
    workspace_id: 7,
    trashed_at: "2026-07-01T00:00:00Z",
    expires_at: "2026-07-31T00:00:00Z",
    member_count: 1,
    members: [],
    ...partial,
  };
}

function page(items: TrashBundleRead[], total = items.length): Page<TrashBundleRead> {
  return { items, total };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useTrash", () => {
  it("마운트 시 첫 페이지를 로드해 ready 로 수렴하고 bundles/total 을 Page 에서 채운다", async () => {
    const bundles = [sampleBundle({ bundle_id: 1 }), sampleBundle({ bundle_id: 2 })];
    listTrashMock.mockResolvedValue(page(bundles, 5));

    const { result } = renderHook(() => useTrash("42"));

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(listTrashMock).toHaveBeenCalledWith("42", expect.any(Number), 0);
    expect(result.current.bundles).toEqual(bundles);
    expect(result.current.total).toBe(5);
    expect(result.current.error).toBeNull();
  });

  it("로드 실패 시 status=error 로 수렴하고 error 에 raw ApiError 를 보존한다", async () => {
    const err = new ApiError({ status: 403, code: "forbidden", message: "권한 없음" });
    listTrashMock.mockRejectedValue(err);

    const { result } = renderHook(() => useTrash("42"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe(err);
    expect(result.current.bundles).toEqual([]);
  });

  it("restore 성공(204)은 restoreBundle 호출→reload(listTrash 재호출) 후 true 를 반환한다", async () => {
    listTrashMock.mockResolvedValue(page([sampleBundle()], 1));
    restoreMock.mockResolvedValue(undefined);

    const { result } = renderHook(() => useTrash("42"));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    listTrashMock.mockClear();

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.restore(9);
    });

    expect(ret).toBe(true);
    expect(restoreMock).toHaveBeenCalledWith(9);
    expect(listTrashMock).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeNull();
  });

  it("restore 404 실패는 error 를 설정하고 재목록(reload)한 뒤 false 를 반환한다", async () => {
    listTrashMock.mockResolvedValue(page([sampleBundle()], 1));
    const err = new ApiError({ status: 404, code: "not_found", message: "없음" });
    restoreMock.mockRejectedValue(err);

    const { result } = renderHook(() => useTrash("42"));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    listTrashMock.mockClear();

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.restore(9);
    });

    expect(ret).toBe(false);
    expect(result.current.error).toBe(err);
    expect(listTrashMock).toHaveBeenCalledTimes(1);
  });

  it("purge 성공(204)은 purgeBundle 호출→reload 후 true 를 반환한다", async () => {
    listTrashMock.mockResolvedValue(page([sampleBundle()], 1));
    purgeMock.mockResolvedValue(undefined);

    const { result } = renderHook(() => useTrash("42"));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    listTrashMock.mockClear();

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.purge(3);
    });

    expect(ret).toBe(true);
    expect(purgeMock).toHaveBeenCalledWith(3);
    expect(listTrashMock).toHaveBeenCalledTimes(1);
  });

  it("purge 404 실패는 error 설정+reload 후 false 를 반환한다", async () => {
    listTrashMock.mockResolvedValue(page([sampleBundle()], 1));
    const err = new ApiError({ status: 404, code: "not_found", message: "없음" });
    purgeMock.mockRejectedValue(err);

    const { result } = renderHook(() => useTrash("42"));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    listTrashMock.mockClear();

    let ret: boolean | undefined;
    await act(async () => {
      ret = await result.current.purge(3);
    });

    expect(ret).toBe(false);
    expect(result.current.error).toBe(err);
    expect(listTrashMock).toHaveBeenCalledTimes(1);
  });

  it("빈 workspaceId 는 API 를 호출하지 않고 ready·빈 bundles 로 수렴한다", async () => {
    const { result } = renderHook(() => useTrash(""));

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(listTrashMock).not.toHaveBeenCalled();
    expect(result.current.bundles).toEqual([]);
    expect(result.current.total).toBe(0);
  });

  it("loadPage(limit, offset) 는 그 인자로 listTrash 를 호출한다", async () => {
    listTrashMock.mockResolvedValue(page([sampleBundle()], 100));

    const { result } = renderHook(() => useTrash("42"));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    listTrashMock.mockClear();

    await act(async () => {
      await result.current.loadPage(25, 50);
    });

    expect(listTrashMock).toHaveBeenCalledWith("42", 25, 50);
    expect(result.current.status).toBe("ready");
  });
});
