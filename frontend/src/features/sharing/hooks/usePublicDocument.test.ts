import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { usePublicDocument } from "./usePublicDocument";
import { publicApi } from "../api/publicApi";
import type { PublicDocumentRead } from "../api/types";
import { ApiError } from "@/shared/api/errors";

/**
 * usePublicDocument 는 `publicApi.getPublicDocument(token)` 로 공개 트리를 로드해
 * `loading→ready` 로 전이하며, 모든 노드(root+하위)의 `content_html` 의 링크 스코프 첨부
 * 참조(`/public/{token}/attachments/{id}`)를 실제 `rewriteAttachmentRefs` 로 절대화한다.
 * 404 는 사유를 구분하지 않고 unavailable 로 통일(존재 추정 차단)하고, 그 외 오류(5xx·비404)는
 * error 로 ApiError 를 보존한다. 공개(무가드) 호출이라 401 리다이렉트를 유발하지 않는다.
 * base URL 은 `@/config` 단일 설정만 소비한다(Requirements 5.4·6.2·6.3·6.5·7.1·7.4).
 *
 * 실제 rewriteAttachmentRefs 를 사용(재작성 회귀 실검증)하되, 어댑터(publicApi)와 base URL
 * 설정(@/config)만 모킹한다.
 */
vi.mock("../api/publicApi", () => ({
  publicApi: {
    getPublicDocument: vi.fn(),
    buildAttachmentUrl: vi.fn(),
  },
}));

vi.mock("@/config", () => ({
  apiConfig: { baseUrl: "http://localhost:8000" },
}));

const getPublicDocumentMock = publicApi.getPublicDocument as unknown as Mock;

beforeEach(() => {
  getPublicDocumentMock.mockReset();
});

const TOKEN = "tok-abc";

/** 특정 토큰의 링크 스코프 첨부 참조를 담은 중첩 트리 응답을 만든다. */
function makeTreeResponse(): PublicDocumentRead {
  return {
    root: {
      id: 1,
      title: "루트",
      content_html: `<p><img src="/public/${TOKEN}/attachments/5"></p>`,
      children: [
        {
          id: 2,
          title: "자식",
          content_html: `<p><img src="/public/${TOKEN}/attachments/50"></p>`,
          children: [],
        },
      ],
    },
  };
}

describe("usePublicDocument", () => {
  it("200 → ready 로 전이하고 root·자식 노드의 content_html 을 모두 절대화한다(재귀, Req 6.3·7.1)", async () => {
    getPublicDocumentMock.mockResolvedValue(makeTreeResponse());

    const { result } = renderHook(() => usePublicDocument(TOKEN));

    // 초기 상태는 loading.
    expect(result.current.status).toBe("loading");

    await waitFor(() => expect(result.current.status).toBe("ready"));

    if (result.current.status !== "ready") {
      throw new Error("expected ready");
    }
    // root 참조가 절대화되었는가.
    expect(result.current.root.content_html).toContain(
      `http://localhost:8000/public/${TOKEN}/attachments/5`,
    );
    // 자식 참조도 절대화되었는가(재귀 증명).
    const child = result.current.root.children[0];
    expect(child.content_html).toContain(
      `http://localhost:8000/public/${TOKEN}/attachments/50`,
    );
    // 상대 참조가 남아있지 않은가(이중 접두 없음·모두 절대화).
    expect(result.current.root.content_html).not.toContain(
      `"/public/${TOKEN}/attachments/5"`,
    );
    expect(getPublicDocumentMock).toHaveBeenCalledWith(TOKEN);
  });

  it("404 → unavailable 로 통일하고 사유/에러를 노출하지 않는다(존재 추정 차단, Req 5.4·6.5)", async () => {
    getPublicDocumentMock.mockRejectedValue(
      new ApiError({ status: 404, code: "not_found", message: "없음" }),
    );

    const { result } = renderHook(() => usePublicDocument(TOKEN));

    await waitFor(() => expect(result.current.status).toBe("unavailable"));

    // unavailable 상태에는 error 필드 등 사유가 없다.
    expect(result.current).toEqual({ status: "unavailable" });
  });

  it("비404 오류(5xx) → error 로 ApiError 를 보존한다", async () => {
    const err = new ApiError({
      status: 500,
      code: "internal",
      message: "서버 오류",
    });
    getPublicDocumentMock.mockRejectedValue(err);

    const { result } = renderHook(() => usePublicDocument(TOKEN));

    await waitFor(() => expect(result.current.status).toBe("error"));

    if (result.current.status !== "error") {
      throw new Error("expected error");
    }
    expect(result.current.error).toBe(err);
  });

  it("token 변경 중 도착한 이전 응답은 무시한다(stale 방지)", async () => {
    // 첫 토큰은 영원히 미결(pending), 둘째 토큰은 즉시 해소되도록 구성한다.
    let resolveFirst: ((v: PublicDocumentRead) => void) | undefined;
    const firstPending = new Promise<PublicDocumentRead>((resolve) => {
      resolveFirst = resolve;
    });
    const secondResponse: PublicDocumentRead = {
      root: {
        id: 9,
        title: "둘째",
        content_html: "<p>second</p>",
        children: [],
      },
    };
    getPublicDocumentMock
      .mockReturnValueOnce(firstPending)
      .mockResolvedValueOnce(secondResponse);

    const { result, rerender } = renderHook(
      ({ token }: { token: string }) => usePublicDocument(token),
      { initialProps: { token: "tok-1" } },
    );

    // 토큰 변경 → 둘째 요청이 먼저 해소.
    rerender({ token: "tok-2" });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    if (result.current.status !== "ready") {
      throw new Error("expected ready");
    }
    expect(result.current.root.id).toBe(9);

    // 이제 이전(첫) 토큰 응답이 뒤늦게 도착 — 무시되어야 한다.
    resolveFirst?.(makeTreeResponse());
    await Promise.resolve();
    // 상태는 여전히 둘째 응답(id 9)을 유지한다.
    expect(result.current.status).toBe("ready");
    if (result.current.status !== "ready") {
      throw new Error("expected ready");
    }
    expect(result.current.root.id).toBe(9);
  });
});
