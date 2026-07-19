import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useAttachmentResource } from "./useAttachmentResource";
import { attachmentApi } from "../api/attachmentApi";
import { ApiError } from "@/shared/api/errors";

/**
 * useAttachmentResource 는 `fetchAttachmentBlob(id)` 로 받은 blob 으로 오브젝트 URL 을
 * 생성해 `loading→ready` 로 전이하고, 언마운트·id 변경 시 `revokeObjectURL` 로 해제한다.
 * 404→unavailable(not_found)·403→unavailable(forbidden)·5xx/네트워크→error 로 매핑하며
 * 첨부 상태(보관·소멸)를 재판정하지 않는다. 401 은 apiClient 전역 인터셉터 위임이라 여기서
 * 특수 처리하지 않고 error 로 떨어진다. jsdom 은 URL.createObjectURL/revokeObjectURL 을
 * 구현하지 않으므로 스텁한다 (Requirements 3.1·3.2·3.3·3.4·4.1·4.4·5.1·5.2·5.4·6.2·6.3·6.4).
 */
vi.mock("../api/attachmentApi", () => ({
  attachmentApi: {
    fetchAttachmentBlob: vi.fn(),
    uploadAttachment: vi.fn(),
  },
}));

const fetchBlobMock = attachmentApi.fetchAttachmentBlob as unknown as Mock;

// jsdom 은 URL.createObjectURL/revokeObjectURL 을 구현하지 않으므로(spyOn 대상 부재)
// mock 함수를 전역에 직접 할당한다. delete 로 제거하면 testing-library 자동 정리
// (afterEach)가 flush 하는 React 패시브 cleanup 시점에 함수가 사라져 실패하므로,
// 함수는 계속 유지하고 호출 기록만 beforeEach 에서 초기화한다(vitest 는 파일 단위 격리).
const createObjectUrlMock = vi.fn<(blob: Blob) => string>();
const revokeObjectUrlMock = vi.fn<(url: string) => void>();
(URL as unknown as { createObjectURL: unknown }).createObjectURL =
  createObjectUrlMock;
(URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL =
  revokeObjectUrlMock;

beforeEach(() => {
  fetchBlobMock.mockReset();
  createObjectUrlMock.mockReset().mockReturnValue("blob:mock-url");
  revokeObjectUrlMock.mockReset();
});

describe("useAttachmentResource", () => {
  it("200 blob → ready 로 전이하고 오브젝트 URL·meta 를 노출한다", async () => {
    const blob = new Blob(["binary"], { type: "image/png" });
    fetchBlobMock.mockResolvedValue(blob);

    const { result } = renderHook(() =>
      useAttachmentResource(42, { kind: "image", fileName: "pic.png" }),
    );

    // 초기 상태는 loading.
    expect(result.current.status).toBe("loading");

    await waitFor(() => expect(result.current.status).toBe("ready"));

    if (result.current.status !== "ready") {
      throw new Error("expected ready");
    }
    expect(result.current.objectUrl).toBe("blob:mock-url");
    expect(result.current.kind).toBe("image");
    expect(result.current.fileName).toBe("pic.png");
    expect(fetchBlobMock).toHaveBeenCalledWith(42);
    expect(createObjectUrlMock).toHaveBeenCalledWith(blob);
  });

  it("meta 미지정 시 kind/fileName 기본값(file·빈 문자열)으로 ready 를 채운다", async () => {
    fetchBlobMock.mockResolvedValue(new Blob(["x"]));

    const { result } = renderHook(() => useAttachmentResource(7));

    await waitFor(() => expect(result.current.status).toBe("ready"));
    if (result.current.status !== "ready") {
      throw new Error("expected ready");
    }
    expect(result.current.kind).toBe("file");
    expect(result.current.fileName).toBe("");
  });

  it("언마운트 시 생성된 오브젝트 URL 을 revoke 한다(누수 방지, Req 3.4)", async () => {
    fetchBlobMock.mockResolvedValue(new Blob(["x"]));

    const { result, unmount } = renderHook(() => useAttachmentResource(9));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    unmount();
    expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:mock-url");
  });

  it("id 변경 시 재요청하고 이전 오브젝트 URL 을 revoke 한다(Req 3.4)", async () => {
    fetchBlobMock.mockResolvedValue(new Blob(["x"]));

    const { result, rerender } = renderHook(
      ({ id }: { id: number }) => useAttachmentResource(id),
      { initialProps: { id: 1 } },
    );
    await waitFor(() => expect(result.current.status).toBe("ready"));

    rerender({ id: 2 });
    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:mock-url");
    expect(fetchBlobMock).toHaveBeenCalledTimes(2);
    expect(fetchBlobMock).toHaveBeenNthCalledWith(1, 1);
    expect(fetchBlobMock).toHaveBeenNthCalledWith(2, 2);
  });

  it("404 → unavailable(not_found) 로 매핑한다(Req 5.1)", async () => {
    fetchBlobMock.mockRejectedValue(
      new ApiError({ status: 404, code: "not_found", message: "없음" }),
    );

    const { result } = renderHook(() => useAttachmentResource(11));
    await waitFor(() => expect(result.current.status).toBe("unavailable"));

    if (result.current.status !== "unavailable") {
      throw new Error("expected unavailable");
    }
    expect(result.current.reason).toBe("not_found");
  });

  it("403 → unavailable(forbidden) 로 매핑한다(Req 5.2)", async () => {
    fetchBlobMock.mockRejectedValue(
      new ApiError({ status: 403, code: "forbidden", message: "권한 없음" }),
    );

    const { result } = renderHook(() => useAttachmentResource(12));
    await waitFor(() => expect(result.current.status).toBe("unavailable"));

    if (result.current.status !== "unavailable") {
      throw new Error("expected unavailable");
    }
    expect(result.current.reason).toBe("forbidden");
  });

  it("5xx → error 로 구분하고 ApiError 를 보존한다(Req 5.4)", async () => {
    const err = new ApiError({ status: 500, code: "internal", message: "서버 오류" });
    fetchBlobMock.mockRejectedValue(err);

    const { result } = renderHook(() => useAttachmentResource(13));
    await waitFor(() => expect(result.current.status).toBe("error"));

    if (result.current.status !== "error") {
      throw new Error("expected error");
    }
    expect(result.current.error).toBe(err);
  });

  it("401 은 특수 처리 없이 error 로 떨어진다(전역 인터셉터 위임, Req 6.3)", async () => {
    const err = new ApiError({
      status: 401,
      code: "unauthenticated",
      message: "인증 만료",
    });
    fetchBlobMock.mockRejectedValue(err);

    const { result } = renderHook(() => useAttachmentResource(14));
    await waitFor(() => expect(result.current.status).toBe("error"));

    if (result.current.status !== "error") {
      throw new Error("expected error");
    }
    expect(result.current.error).toBe(err);
  });
});
