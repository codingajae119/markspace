import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useShareManager } from "./useShareManager";
import { shareApi } from "../api/shareApi";
import { buildShareUrl } from "../lib/buildShareUrl";
import type { ShareLinkRead } from "../api/types";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import { ApiError } from "@/shared/api/errors";

/**
 * useShareManager 는 공유 관리(발급·토글) 오케스트레이션 훅으로, shareApi 응답만으로
 * link/frontShareUrl 상태를 채운다(S1: 사전 조회 엔드포인트 없음 → link 초기값 null).
 * 재발급(이미 링크가 존재하던 상태에서의 issue)은 새 토큰을 발급하므로 reissued=true 로
 * 표면화하고(INV-8), 토글은 토큰을 유지하는 유일한 상태 기반 예외라 reissued 를 건드리지
 * 않는다. invalidated 는 관측 신호(documentStatus·isShareable)에서 파생하며 훅 자체가
 * 판단/회수하지 않는다(백엔드 소관). 실패 시 ApiError 를 그대로 표면화하고 link 는 불변이며
 * null 을 반환한다. shareApi·useCurrentWorkspace 만 모킹하고 buildShareUrl 은 실제로 쓴다
 * (Requirements 1.3·1.4·2.1·2.3·2.4·3.1·3.2·3.3·5.1·5.2·5.3).
 */
vi.mock("../api/shareApi", () => ({
  shareApi: {
    issueLink: vi.fn(),
    toggleLink: vi.fn(),
  },
}));

vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));

import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";

const issueMock = shareApi.issueLink as unknown as Mock;
const toggleMock = shareApi.toggleLink as unknown as Mock;
const wsMock = useCurrentWorkspace as unknown as Mock;

/** 훅이 읽는 필드(isShareable)만 갖춘 최소 컨텍스트 값. */
function setShareable(isShareable: boolean): void {
  wsMock.mockReturnValue({
    status: "ready",
    workspaces: [],
    currentWorkspace: null,
    workspaceId: null,
    role: null,
    isShareable,
    selectWorkspace: vi.fn(),
    refresh: vi.fn(),
  } as CurrentWorkspaceContextValue);
}

function link(overrides: Partial<ShareLinkRead> = {}): ShareLinkRead {
  return {
    id: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    document_id: 42,
    token: "tok-abc",
    is_enabled: true,
    share_url: "/public/tok-abc",
    ...overrides,
  };
}

/** 외부에서 해상 시점을 제어하는 deferred promise. */
function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  issueMock.mockReset();
  toggleMock.mockReset();
  wsMock.mockReset();
  setShareable(true);
});

describe("useShareManager", () => {
  it("최초 발급 성공: link·frontShareUrl 설정, reissued=false, ShareLinkRead 반환(Req 2.1·5.3)", async () => {
    const issued = link({ token: "tok-first" });
    issueMock.mockResolvedValue(issued);

    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );

    // S1: 사전 조회 없음 → 초기 link 은 null.
    expect(result.current.link).toBeNull();
    expect(result.current.frontShareUrl).toBeNull();
    expect(result.current.reissued).toBe(false);

    let returned: ShareLinkRead | null = null;
    await act(async () => {
      returned = await result.current.issue();
    });

    expect(issueMock).toHaveBeenCalledWith(42);
    expect(returned).toBe(issued);
    expect(result.current.link).toBe(issued);
    expect(result.current.frontShareUrl).toBe(buildShareUrl("tok-first"));
    expect(result.current.reissued).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.pending).toBe(false);
  });

  it("재발급 성공: 이미 링크가 있던 상태에서 issue → reissued=true·새 토큰 반영(INV-8·Req 2.3)", async () => {
    const first = link({ token: "tok-first" });
    const second = link({ id: 2, token: "tok-second" });
    issueMock.mockResolvedValueOnce(first).mockResolvedValueOnce(second);

    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );

    await act(async () => {
      await result.current.issue();
    });
    expect(result.current.reissued).toBe(false);

    await act(async () => {
      await result.current.issue();
    });

    expect(result.current.reissued).toBe(true);
    expect(result.current.link).toBe(second);
    expect(result.current.frontShareUrl).toBe(buildShareUrl("tok-second"));
    expect(result.current.error).toBeNull();
  });

  it("발급 실패: ApiError 표면화, link/frontShareUrl 불변, null 반환(Req 2.4)", async () => {
    const issued = link({ token: "tok-first" });
    issueMock.mockResolvedValueOnce(issued);

    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );

    await act(async () => {
      await result.current.issue();
    });
    const urlBefore = result.current.frontShareUrl;

    const err = new ApiError({ status: 409, code: "conflict", message: "공유 불가" });
    issueMock.mockRejectedValueOnce(err);

    let returned: ShareLinkRead | null = issued;
    await act(async () => {
      returned = await result.current.issue();
    });

    expect(returned).toBeNull();
    expect(result.current.error).toBe(err);
    // 실패는 기존 link/frontShareUrl 을 침범하지 않는다.
    expect(result.current.link).toBe(issued);
    expect(result.current.frontShareUrl).toBe(urlBefore);
  });

  it("토글(false) 성공: link 갱신·토큰 유지·reissued 불변(Req 3.1)", async () => {
    const issued = link({ token: "tok-keep", is_enabled: true });
    const disabled = link({ token: "tok-keep", is_enabled: false });
    issueMock.mockResolvedValue(issued);
    toggleMock.mockResolvedValue(disabled);

    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );

    await act(async () => {
      await result.current.issue();
    });
    expect(result.current.reissued).toBe(false);

    let returned: ShareLinkRead | null = null;
    await act(async () => {
      returned = await result.current.toggle(false);
    });

    expect(toggleMock).toHaveBeenCalledWith(42, { is_enabled: false });
    expect(returned).toBe(disabled);
    expect(result.current.link).toBe(disabled);
    // 토큰 유지 → frontShareUrl 동일.
    expect(result.current.frontShareUrl).toBe(buildShareUrl("tok-keep"));
    // 토글은 reissued 를 건드리지 않는다.
    expect(result.current.reissued).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("토글 활성화 409(게이트 오프/비활성): ApiError 표면화·link 불변(Req 3.2)", async () => {
    const issued = link({ token: "tok-keep", is_enabled: false });
    issueMock.mockResolvedValue(issued);
    const err = new ApiError({ status: 409, code: "conflict", message: "게이트 오프" });
    toggleMock.mockRejectedValue(err);

    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );

    await act(async () => {
      await result.current.issue();
    });

    let returned: ShareLinkRead | null = issued;
    await act(async () => {
      returned = await result.current.toggle(true);
    });

    expect(returned).toBeNull();
    expect(result.current.error).toBe(err);
    expect(result.current.link).toBe(issued);
  });

  it("토글 404(링크 부재 → 발급 유도): ApiError 표면화·link 불변(Req 3.3)", async () => {
    const err = new ApiError({ status: 404, code: "not_found", message: "링크 없음" });
    toggleMock.mockRejectedValue(err);

    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );

    let returned: ShareLinkRead | null = link();
    await act(async () => {
      returned = await result.current.toggle(true);
    });

    expect(returned).toBeNull();
    expect(result.current.error).toBe(err);
    expect(result.current.link).toBeNull();
  });

  it("invalidated 파생: documentStatus !== active → true(Req 5.1·5.2)", () => {
    setShareable(true);
    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "archived" }),
    );
    expect(result.current.invalidated).toBe(true);
  });

  it("invalidated 파생: isShareable=false → true(Req 5.1·5.2)", () => {
    setShareable(false);
    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );
    expect(result.current.invalidated).toBe(true);
  });

  it("invalidated 파생: active + shareable → false", () => {
    setShareable(true);
    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );
    expect(result.current.invalidated).toBe(false);
  });

  it("pending: in-flight 동안 true 였다가 해상 후 false(Req 5.3)", async () => {
    const d = deferred<ShareLinkRead>();
    issueMock.mockReturnValue(d.promise);

    const { result } = renderHook(() =>
      useShareManager({ documentId: 42, documentStatus: "active" }),
    );

    expect(result.current.pending).toBe(false);

    let p!: Promise<ShareLinkRead | null>;
    act(() => {
      p = result.current.issue();
    });

    await waitFor(() => {
      expect(result.current.pending).toBe(true);
    });

    await act(async () => {
      d.resolve(link());
      await p;
    });

    expect(result.current.pending).toBe(false);
  });
});
