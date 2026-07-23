import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/shared/api/errors";
import { useShareManager } from "../hooks/useShareManager";
import type { UseShareManagerResult } from "../hooks/useShareManager";
import type { ShareLinkRead } from "../api/types";
import { DocumentShareControl } from "./DocumentShareControl";

// DocumentShareControl 은 노출 게이트를 소유하지 않는 자기완결 마운트 유닛이다(툴바가 마운트를
// 결정, 마운트되면 렌더). 상태 파생·동작 매핑·복사 게이팅만 검증하므로 useShareManager 를
// 모킹해 상태를 결정적으로 제어한다. CopyLinkButton 은 모킹해 전달된 frontShareUrl 을 표면화만
// 시켜 "복사 대상=게스트 프론트 링크(share_url 아님)"를 단언한다. 복사·피드백·폴백 자체는
// CopyLinkButton 이 이미 소유하므로 재검증하지 않는다.
// Requirements: 2.2, 2.3, 4.1, 4.2, 4.3, 4.4, 5.1, 5.4, 5.5, 6.1, 6.2

vi.mock("../hooks/useShareManager", () => ({ useShareManager: vi.fn() }));
vi.mock("./CopyLinkButton", () => ({
  // 전달받은 frontShareUrl 을 그대로 표면화해 복사 대상을 단언 가능하게 한다.
  CopyLinkButton: ({ frontShareUrl }: { frontShareUrl: string | null }) => (
    <div data-testid="copy-link-button" data-front-share-url={frontShareUrl ?? ""}>
      링크 복사
    </div>
  ),
}));

const useShareManagerMock = useShareManager as unknown as Mock;

const activeLink: ShareLinkRead = {
  id: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  document_id: 10,
  token: "tok-abc",
  is_enabled: true,
  share_url: "/public/tok-abc", // 백엔드 공개 API 경로 — 복사 대상이 되어선 안 됨.
};

const disabledLink: ShareLinkRead = { ...activeLink, is_enabled: false };

/** useShareManager 반환 상태를 구성(기본은 링크 없음·오류 없음·유휴). */
function makeManager(
  overrides: Partial<UseShareManagerResult> = {},
): UseShareManagerResult {
  return {
    link: null,
    frontShareUrl: null,
    reissued: false,
    invalidated: false,
    loading: false,
    pending: false,
    error: null,
    issue: vi.fn().mockResolvedValue(null),
    toggle: vi.fn().mockResolvedValue(null),
    ...overrides,
  };
}

beforeEach(() => {
  useShareManagerMock.mockReset();
  useShareManagerMock.mockReturnValue(makeManager());
});

afterEach(() => {
  cleanup();
});

describe("DocumentShareControl — 라벨 전환 (Req 4.1·4.2)", () => {
  it("링크 활성 → '공유 해제' 라벨", () => {
    useShareManagerMock.mockReturnValue(
      makeManager({ link: activeLink, frontShareUrl: "http://localhost/share/tok-abc" }),
    );

    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "공유 해제" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "공유" })).not.toBeInTheDocument();
  });

  it("링크 없음 → '공유' 라벨", () => {
    // 기본 makeManager(): link=null.
    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "공유" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "공유 해제" })).not.toBeInTheDocument();
  });

  it("비활성 링크 → '공유' 라벨(공유 중 아님)", () => {
    useShareManagerMock.mockReturnValue(makeManager({ link: disabledLink }));

    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "공유" })).toBeInTheDocument();
  });
});

describe("DocumentShareControl — 동작 매핑 3분기 (Req 4.3·4.4)", () => {
  it("공유 중 클릭 → toggle(false) 호출(해제)", async () => {
    const toggle = vi.fn().mockResolvedValue(null);
    const issue = vi.fn().mockResolvedValue(null);
    useShareManagerMock.mockReturnValue(
      makeManager({ link: activeLink, frontShareUrl: "http://localhost/share/tok-abc", toggle, issue }),
    );
    const user = userEvent.setup();

    render(<DocumentShareControl documentId={10} documentStatus="active" />);
    await user.click(screen.getByRole("button", { name: "공유 해제" }));

    expect(toggle).toHaveBeenCalledTimes(1);
    expect(toggle).toHaveBeenCalledWith(false);
    expect(issue).not.toHaveBeenCalled();
  });

  it("미공유·링크 없음 클릭 → issue() 호출(새 토큰 발급)", async () => {
    const toggle = vi.fn().mockResolvedValue(null);
    const issue = vi.fn().mockResolvedValue(null);
    useShareManagerMock.mockReturnValue(makeManager({ link: null, toggle, issue }));
    const user = userEvent.setup();

    render(<DocumentShareControl documentId={10} documentStatus="active" />);
    await user.click(screen.getByRole("button", { name: "공유" }));

    expect(issue).toHaveBeenCalledTimes(1);
    expect(toggle).not.toHaveBeenCalled();
  });

  it("미공유·비활성 링크 클릭 → toggle(true) 호출(같은 URL 재활성)", async () => {
    const toggle = vi.fn().mockResolvedValue(null);
    const issue = vi.fn().mockResolvedValue(null);
    useShareManagerMock.mockReturnValue(makeManager({ link: disabledLink, toggle, issue }));
    const user = userEvent.setup();

    render(<DocumentShareControl documentId={10} documentStatus="active" />);
    await user.click(screen.getByRole("button", { name: "공유" }));

    expect(toggle).toHaveBeenCalledTimes(1);
    expect(toggle).toHaveBeenCalledWith(true);
    expect(issue).not.toHaveBeenCalled();
  });
});

describe("DocumentShareControl — 진행 중 비활성 (Req 2.2·6.2)", () => {
  it("loading(초기 조회 중) → 버튼 비활성", () => {
    useShareManagerMock.mockReturnValue(makeManager({ loading: true }));

    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "공유" })).toBeDisabled();
  });

  it("pending(조작 중) → 버튼 비활성", () => {
    useShareManagerMock.mockReturnValue(
      makeManager({ link: activeLink, frontShareUrl: "http://localhost/share/tok-abc", pending: true }),
    );

    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "공유 해제" })).toBeDisabled();
  });
});

describe("DocumentShareControl — 복사 버튼 게이팅 (Req 5.1·5.4·5.5)", () => {
  it("공유 중일 때만 CopyLinkButton 노출 + 복사 대상=frontShareUrl(share_url 아님)", () => {
    useShareManagerMock.mockReturnValue(
      makeManager({ link: activeLink, frontShareUrl: "http://localhost/share/tok-abc" }),
    );

    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    const copy = screen.getByTestId("copy-link-button");
    expect(copy).toBeInTheDocument();
    // 복사 대상은 게스트 프론트 링크(/share/…)이며 백엔드 share_url(/public/…)이 아니다.
    expect(copy).toHaveAttribute("data-front-share-url", "http://localhost/share/tok-abc");
  });

  it("미공유(링크 없음) → CopyLinkButton 미노출", () => {
    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(screen.queryByTestId("copy-link-button")).not.toBeInTheDocument();
  });

  it("비활성 링크(공유 중 아님) → CopyLinkButton 미노출", () => {
    useShareManagerMock.mockReturnValue(makeManager({ link: disabledLink }));

    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(screen.queryByTestId("copy-link-button")).not.toBeInTheDocument();
  });
});

describe("DocumentShareControl — 오류 표면화 (Req 6.1)", () => {
  it("error(ApiError) → ErrorMessage 로 표면화(초기 조회·조작 공통 sink)", () => {
    useShareManagerMock.mockReturnValue(
      makeManager({
        error: new ApiError({
          status: 409,
          code: "conflict",
          message: "공유가 꺼져 있거나 문서가 활성 상태가 아닙니다.",
        }),
      }),
    );

    render(<DocumentShareControl documentId={10} documentStatus="active" />);

    expect(
      screen.getByText("공유가 꺼져 있거나 문서가 활성 상태가 아닙니다."),
    ).toBeInTheDocument();
  });
});
