import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ConfirmDialog } from "./ConfirmDialog";

// ConfirmDialog 은 파괴적 조작(삭제→휴지통, 비가역 완전삭제) 확인을 담당하는
// 재사용 모달이다. open=false 면 아무것도 렌더하지 않고, open=true 면 제목·본문·
// 확인/취소 버튼을 접근 가능한 dialog 로 렌더한다. irreversible=true 일 때만
// "되돌릴 수 없습니다" 경고를 표시한다(백엔드 OpenAPI 비가역 계약과 정합).
// Requirements: 5.1, 8.4

describe("ConfirmDialog", () => {
  it("open=false 면 아무것도 렌더하지 않는다", () => {
    const { container } = render(
      <ConfirmDialog
        open={false}
        title="삭제 확인"
        message="이 문서를 휴지통으로 옮깁니다."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("open=true 면 제목·본문·확인/취소 버튼을 렌더한다 (Req 5.1)", () => {
    render(
      <ConfirmDialog
        open
        title="삭제 확인"
        message="이 문서를 휴지통으로 옮깁니다."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("삭제 확인")).toBeInTheDocument();
    expect(
      screen.getByText("이 문서를 휴지통으로 옮깁니다."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "확인" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "취소" })).toBeInTheDocument();
  });

  it("커스텀 라벨을 사용한다", () => {
    render(
      <ConfirmDialog
        open
        title="완전삭제"
        message="묶음을 완전히 삭제합니다."
        confirmLabel="완전삭제"
        cancelLabel="닫기"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "완전삭제" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "닫기" })).toBeInTheDocument();
  });

  it("확인 클릭 시 onConfirm, 취소 클릭 시 onCancel 을 호출한다 (Req 5.1)", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="삭제 확인"
        message="이 문서를 휴지통으로 옮깁니다."
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "확인" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("irreversible=true 면 비가역 경고를 표시한다 (Req 8.4)", () => {
    render(
      <ConfirmDialog
        open
        irreversible
        title="완전삭제"
        message="묶음을 완전히 삭제합니다."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const warning = screen.getByTestId("irreversible-warning");
    expect(warning).toBeInTheDocument();
    expect(warning.textContent).toMatch(/되돌릴 수 없습니다/);
  });

  it("irreversible 이 아니면 비가역 경고가 없다", () => {
    render(
      <ConfirmDialog
        open
        title="삭제 확인"
        message="이 문서를 휴지통으로 옮깁니다."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("irreversible-warning")).toBeNull();
    expect(screen.queryByText(/되돌릴 수 없습니다/)).toBeNull();
  });

  it("접근 가능한 dialog 역할을 가지며 제목으로 라벨된다", () => {
    render(
      <ConfirmDialog
        open
        title="삭제 확인"
        message="이 문서를 휴지통으로 옮깁니다."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("삭제 확인");
  });

  it("irreversible=true 면 alertdialog 역할로 렌더된다", () => {
    render(
      <ConfirmDialog
        open
        irreversible
        title="완전삭제"
        message="묶음을 완전히 삭제합니다."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("완전삭제");
  });
});
