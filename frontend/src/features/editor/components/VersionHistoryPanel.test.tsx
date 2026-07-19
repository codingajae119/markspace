import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";

import { ApiError } from "@/shared/api/errors";
import type { DocumentVersionRead } from "../types";
import type { UseVersionHistory } from "../hooks/useVersionHistory";

/**
 * VersionHistoryPanel 은 useVersionHistory 가 노출하는 버전 메타(저장자·시각)를 읽기 전용
 * 목록으로 렌더하고, current_version_id 를 구분 표시하며, "더 보기" 로 loadMore 를 호출한다.
 * rollback·복원·본문 표시 UI 는 두지 않는다(Req 6.1~6.6).
 *
 * useVersionHistory 는 마운트 시 API 를 호출하는 훅이므로 여기서는 제어 가능한 stub 으로
 * 모킹하여 각 상태(loading/ready/empty/error)와 loadMore 호출을 검증한다.
 */

const loadMoreSpy = vi.fn();
const reloadSpy = vi.fn();

let mockState: UseVersionHistory;

vi.mock("../hooks/useVersionHistory", () => ({
  useVersionHistory: (documentId: number, currentVersionId: number | null) => {
    // 인자 통과 검증용 기록.
    mockState.currentVersionId = currentVersionId;
    void documentId;
    return mockState;
  },
}));

import { VersionHistoryPanel } from "./VersionHistoryPanel";

function version(partial: Partial<DocumentVersionRead> = {}): DocumentVersionRead {
  return {
    id: 1,
    document_id: 42,
    created_by: 7,
    created_at: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

function readyState(
  overrides: Partial<UseVersionHistory> = {},
): UseVersionHistory {
  return {
    status: "ready",
    versions: [],
    total: 0,
    currentVersionId: null,
    error: null,
    reload: reloadSpy,
    loadMore: loadMoreSpy,
    ...overrides,
  };
}

beforeEach(() => {
  mockState = readyState();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("VersionHistoryPanel", () => {
  it("각 버전의 저장자·저장 시각 메타데이터를 렌더한다 (Req 6.1)", () => {
    mockState = readyState({
      versions: [
        version({ id: 10, created_by: 3, created_at: "2026-02-02T10:00:00Z" }),
        version({ id: 9, created_by: 4, created_at: "2026-01-01T09:00:00Z" }),
      ],
      total: 2,
    });

    render(<VersionHistoryPanel documentId={42} currentVersionId={null} />);

    // 저장자(created_by) 표면화.
    const savers = screen.getAllByTestId("version-created-by");
    expect(savers).toHaveLength(2);
    expect(savers[0]).toHaveTextContent("3");
    expect(savers[1]).toHaveTextContent("4");
    // 저장 시각(created_at)을 <time dateTime> 으로 표면화(원본 ISO 유지).
    const times = screen.getAllByTestId("version-created-at");
    expect(times).toHaveLength(2);
    expect(times[0]).toHaveAttribute("dateTime", "2026-02-02T10:00:00Z");
    expect(times[1]).toHaveAttribute("dateTime", "2026-01-01T09:00:00Z");
  });

  it("current_version_id 와 일치하는 행만 '현재' 로 구분 표시한다 (Req 6.5)", () => {
    mockState = readyState({
      versions: [version({ id: 10 }), version({ id: 9 })],
      total: 2,
      currentVersionId: 10,
    });

    render(<VersionHistoryPanel documentId={42} currentVersionId={10} />);

    const badges = screen.getAllByText("현재");
    expect(badges).toHaveLength(1);
    // 배지가 붙은 행은 id=10 행이어야 한다.
    const currentRow = screen.getByTestId("version-row-10");
    expect(currentRow).toHaveTextContent("현재");
    const otherRow = screen.getByTestId("version-row-9");
    expect(otherRow).not.toHaveTextContent("현재");
  });

  it("currentVersionId 가 null 이면 어떤 행도 '현재' 로 표시하지 않는다 (Req 6.5)", () => {
    mockState = readyState({
      versions: [version({ id: 10 }), version({ id: 9 })],
      total: 2,
      currentVersionId: null,
    });

    render(<VersionHistoryPanel documentId={42} currentVersionId={null} />);

    expect(screen.queryByText("현재")).toBeNull();
  });

  it("versions.length < total 이면 '더 보기' 를 노출하고 클릭 시 loadMore 를 호출한다 (Req 6.2)", () => {
    mockState = readyState({
      versions: [version({ id: 10 })],
      total: 3,
    });

    render(<VersionHistoryPanel documentId={42} currentVersionId={null} />);

    const button = screen.getByRole("button", { name: /더 보기/ });
    fireEvent.click(button);
    expect(loadMoreSpy).toHaveBeenCalledTimes(1);
  });

  it("versions.length >= total 이면 '더 보기' 를 노출하지 않는다 (Req 6.2)", () => {
    mockState = readyState({
      versions: [version({ id: 10 }), version({ id: 9 })],
      total: 2,
    });

    render(<VersionHistoryPanel documentId={42} currentVersionId={null} />);

    expect(screen.queryByRole("button", { name: /더 보기/ })).toBeNull();
  });

  it("rollback·복원·되돌리기 등 상태 변경 UI 를 렌더하지 않는다 (Req 6.3, 6.4)", () => {
    mockState = readyState({
      versions: [version({ id: 10 }), version({ id: 9 })],
      total: 2,
      currentVersionId: 10,
    });

    render(<VersionHistoryPanel documentId={42} currentVersionId={10} />);

    // rollback/restore/revert 성격 조작이 어떤 형태로도 존재하지 않아야 한다.
    const forbidden = /(rollback|restore|revert|복원|되돌리|롤백)/i;
    expect(screen.queryByText(forbidden)).toBeNull();
    expect(
      screen.queryAllByRole("button").filter((el) => forbidden.test(el.textContent ?? "")),
    ).toHaveLength(0);
    // "더 보기" 외의 액션 버튼은 없다(모두 로드된 상태이므로 버튼 자체가 없어야 한다).
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("loading 상태이면 Spinner 를 렌더한다", () => {
    mockState = readyState({ status: "loading", versions: [], total: 0 });

    render(<VersionHistoryPanel documentId={42} currentVersionId={null} />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /더 보기/ })).toBeNull();
  });

  it("ready 이며 버전이 0개이면 EmptyState 를 렌더한다", () => {
    mockState = readyState({ status: "ready", versions: [], total: 0 });

    render(<VersionHistoryPanel documentId={42} currentVersionId={null} />);

    expect(screen.getByText(/저장된 버전이 없습니다/)).toBeInTheDocument();
  });

  it("error 상태이면 ErrorMessage 로 ApiError 를 표면화한다 (Req 6.6)", () => {
    const apiError = new ApiError({
      status: 403,
      code: "forbidden",
      message: "권한이 없습니다.",
    });
    mockState = readyState({ status: "error", versions: [], total: 0, error: apiError });

    render(<VersionHistoryPanel documentId={42} currentVersionId={null} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("권한이 없습니다.");
  });
});
