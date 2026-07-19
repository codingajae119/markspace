import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

import { TrashBundleItem } from "./TrashBundleItem";
import type { TrashBundleRead } from "../types";

// TrashBundleItem 은 휴지통 묶음 한 행을 표시한다. 루트 요약(root_title·member_count·
// expires_at)과 구성원 목록을 렌더하고, 복구/완전삭제 콜백을 발화한다. 완전삭제는
// ConfirmDialog(irreversible)로 확인받은 뒤에만 onPurge 를 호출한다.
// Requirements: 8.2, 8.4

function sampleBundle(partial: Partial<TrashBundleRead> = {}): TrashBundleRead {
  return {
    bundle_id: 42,
    root_document_id: 42,
    root_title: "프로젝트 계획",
    workspace_id: 7,
    trashed_at: "2026-07-01T09:00:00Z",
    expires_at: "2026-07-31T09:00:00Z",
    member_count: 3,
    members: [
      { id: 42, parent_id: null, title: "프로젝트 계획" },
      { id: 43, parent_id: 42, title: "1분기 로드맵" },
      { id: 44, parent_id: 42, title: "예산안" },
    ],
    ...partial,
  };
}

describe("TrashBundleItem", () => {
  it("root_title·member_count·expires_at 를 렌더한다 (Req 8.2)", () => {
    const bundle = sampleBundle();
    render(
      <TrashBundleItem
        bundle={bundle}
        onRestore={vi.fn()}
        onPurge={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "프로젝트 계획" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/3/).length).toBeGreaterThan(0);

    const formatted = new Date(bundle.expires_at).toLocaleString();
    expect(screen.getByText(new RegExp(formatted.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
  });

  it("각 구성원 title 을 렌더한다 (Req 8.2)", () => {
    render(
      <TrashBundleItem
        bundle={sampleBundle()}
        onRestore={vi.fn()}
        onPurge={vi.fn()}
      />,
    );

    expect(screen.getByText("1분기 로드맵")).toBeInTheDocument();
    expect(screen.getByText("예산안")).toBeInTheDocument();
  });

  it("복구 클릭 시 onRestore(bundle_id) 를 호출한다 (Req 8.2)", () => {
    const onRestore = vi.fn();
    render(
      <TrashBundleItem
        bundle={sampleBundle({ bundle_id: 99 })}
        onRestore={onRestore}
        onPurge={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "복구" }));
    expect(onRestore).toHaveBeenCalledTimes(1);
    expect(onRestore).toHaveBeenCalledWith(99);
  });

  it("완전삭제 클릭 시 ConfirmDialog(비가역)를 열고, 확인해야 onPurge(bundle_id)를 호출한다 (Req 8.4)", () => {
    const onPurge = vi.fn();
    render(
      <TrashBundleItem
        bundle={sampleBundle({ bundle_id: 55 })}
        onRestore={vi.fn()}
        onPurge={onPurge}
      />,
    );

    // 다이얼로그를 열기 전에는 경고도 없고 onPurge 도 미호출
    expect(screen.queryByTestId("irreversible-warning")).toBeNull();
    expect(onPurge).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "완전삭제" }));

    // 비가역 경고가 보이는 alertdialog 가 열린다
    const dialog = screen.getByRole("alertdialog");
    const warning = within(dialog).getByTestId("irreversible-warning");
    expect(warning).toBeInTheDocument();
    expect(warning.textContent).toMatch(/되돌릴 수 없습니다/);
    expect(onPurge).not.toHaveBeenCalled();

    // 다이얼로그 안의 확인 버튼을 눌러야 onPurge(bundle_id) 호출
    fireEvent.click(within(dialog).getByRole("button", { name: "완전삭제" }));

    expect(onPurge).toHaveBeenCalledTimes(1);
    expect(onPurge).toHaveBeenCalledWith(55);
  });

  it("완전삭제 다이얼로그를 취소하면 onPurge 를 호출하지 않는다 (Req 8.4)", () => {
    const onPurge = vi.fn();
    render(
      <TrashBundleItem
        bundle={sampleBundle()}
        onRestore={vi.fn()}
        onPurge={onPurge}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "완전삭제" }));
    expect(screen.getByTestId("irreversible-warning")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "취소" }));

    expect(onPurge).not.toHaveBeenCalled();
    // 취소 후 다이얼로그가 닫힌다
    expect(screen.queryByTestId("irreversible-warning")).toBeNull();
  });
});
