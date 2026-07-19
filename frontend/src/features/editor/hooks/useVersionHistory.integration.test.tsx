import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useVersionHistory } from "./useVersionHistory";
import { lockVersionApi } from "../api/lockVersionApi";
import { ApiError } from "@/shared/api/errors";
import type { DocumentVersionRead, Page } from "../types";

/**
 * useVersionHistory 는 마운트 시 listVersions(id, limit, offset=0) 로 버전 목록을 로드하고
 * (status=ready·versions·total), loadMore 로 offset=누적 length 를 이어받아 **append**
 * (replace 아님) 하며, reload 로 offset 0 부터 재로드한다. currentVersionId 는 문서 상세에서
 * 주입받아 그대로 노출(현재 버전 구분용)하고, 조회 실패(403/404)는 ApiError 를 표면화한다.
 * 협력자(lockVersionApi)만 모킹하고 로드/페이지네이션/오류/빈 상태만 관찰한다
 * (Requirements 6.1, 6.2, 6.5, 6.6). 본문(content) 조회·rollback 는 호출하지 않는다.
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

const listVersionsMock = lockVersionApi.listVersions as unknown as Mock;

const DOC_ID = 42;

function version(id: number): DocumentVersionRead {
  return {
    id,
    document_id: DOC_ID,
    created_by: 9,
    created_at: `2026-07-19T00:00:${String(id).padStart(2, "0")}Z`,
  };
}

function page(items: DocumentVersionRead[], total: number): Page<DocumentVersionRead> {
  return { items, total };
}

function apiError(status: number, code = "forbidden"): ApiError {
  return new ApiError({ status, code, message: `err-${status}` });
}

beforeEach(() => {
  vi.clearAllMocks();
  listVersionsMock.mockResolvedValue(page([version(3), version(2), version(1)], 3));
});

describe("useVersionHistory", () => {
  it("마운트 시 listVersions(id, limit, offset=0) 로 로드 후 status=ready·versions·total 세팅 (6.1)", async () => {
    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(listVersionsMock).toHaveBeenCalledTimes(1);
    const [id, , offset] = listVersionsMock.mock.calls[0];
    expect(id).toBe(DOC_ID);
    expect(offset).toBe(0);
    expect(result.current.versions.map((v) => v.id)).toEqual([3, 2, 1]);
    expect(result.current.total).toBe(3);
    expect(result.current.error).toBeNull();
  });

  it("초기 상태는 loading 이다 (6.1)", async () => {
    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));
    expect(result.current.status).toBe("loading");
    // 마운트 로드가 act 밖에서 상태를 갱신하지 않도록 정착시킨다.
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  it("loadMore 는 offset=누적 length 로 호출하고 결과를 append 한다(replace 아님) (6.2)", async () => {
    listVersionsMock.mockResolvedValueOnce(page([version(5), version(4), version(3)], 5));
    listVersionsMock.mockResolvedValueOnce(page([version(2), version(1)], 5));

    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.versions).toHaveLength(3);

    await act(async () => {
      await result.current.loadMore();
    });

    // 두 번째 호출 offset 은 첫 페이지 길이(3)
    const secondCall = listVersionsMock.mock.calls[1];
    expect(secondCall[0]).toBe(DOC_ID);
    expect(secondCall[2]).toBe(3);
    // append: 길이 증가·기존 항목 유지
    expect(result.current.versions.map((v) => v.id)).toEqual([5, 4, 3, 2, 1]);
    expect(result.current.total).toBe(5);
  });

  it("loadMore 는 모든 항목을 로드한 뒤(versions.length>=total)에는 추가 호출하지 않는다 (6.2)", async () => {
    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.versions).toHaveLength(3);
    expect(result.current.total).toBe(3);

    await act(async () => {
      await result.current.loadMore();
    });

    // 이미 total 만큼 로드됨 → 추가 호출 없음(초기 1회만)
    expect(listVersionsMock).toHaveBeenCalledTimes(1);
  });

  it("reload 는 offset 0 부터 재로드한다(누적 아님) (6.2)", async () => {
    listVersionsMock.mockResolvedValueOnce(page([version(3), version(2), version(1)], 5));
    listVersionsMock.mockResolvedValueOnce(page([version(0)], 5)); // loadMore
    listVersionsMock.mockResolvedValueOnce(page([version(9), version(8)], 2)); // reload

    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    await act(async () => {
      await result.current.loadMore();
    });
    expect(result.current.versions).toHaveLength(4);

    await act(async () => {
      await result.current.reload();
    });

    const reloadCall = listVersionsMock.mock.calls[2];
    expect(reloadCall[2]).toBe(0);
    expect(result.current.versions.map((v) => v.id)).toEqual([9, 8]);
    expect(result.current.total).toBe(2);
  });

  it("currentVersionId 를 주입받아 그대로 노출한다 (6.5)", async () => {
    const { result } = renderHook(() => useVersionHistory(DOC_ID, 2));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.currentVersionId).toBe(2);
  });

  it("403 실패 시 status=error·error 표면화 (6.6)", async () => {
    listVersionsMock.mockRejectedValue(apiError(403, "forbidden"));

    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.status).toBe(403);
    expect(result.current.versions).toEqual([]);
  });

  it("404 실패 시 status=error·error 표면화 (6.6)", async () => {
    listVersionsMock.mockRejectedValue(apiError(404, "not_found"));

    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.status).toBe(404);
  });

  it("빈 이력(total 0) 은 ready·빈 versions 로 반영한다(빈 상태)", async () => {
    listVersionsMock.mockResolvedValue(page([], 0));

    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.versions).toEqual([]);
    expect(result.current.total).toBe(0);
  });

  it("content/rollback 엔드포인트를 호출하지 않는다(listVersions 만 소비)", async () => {
    const { result } = renderHook(() => useVersionHistory(DOC_ID, null));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(lockVersionApi.getDocument).not.toHaveBeenCalled();
    expect(lockVersionApi.saveDocument).not.toHaveBeenCalled();
    expect(lockVersionApi.lockDocument).not.toHaveBeenCalled();
  });
});
