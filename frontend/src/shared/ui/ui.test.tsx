import { describe, it, expect, afterEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Button, Spinner, EmptyState, ErrorMessage } from "@/shared/ui";
import { ApiError, parseErrorResponse } from "@/shared/api/errors";

afterEach(() => {
  cleanup();
});

describe("Button — 공용 버튼 프리미티브 (7.1, 7.5)", () => {
  it("children 을 렌더하고 onClick 을 전달한다", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>저장</Button>);

    const button = screen.getByRole("button", { name: "저장" });
    await userEvent.click(button);

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("type·disabled 등 표준 button 속성을 전달하고, disabled 면 클릭이 발생하지 않는다", async () => {
    const onClick = vi.fn();
    render(
      <Button type="submit" disabled onClick={onClick}>
        전송
      </Button>,
    );

    const button = screen.getByRole("button", { name: "전송" });
    expect(button).toHaveAttribute("type", "submit");
    expect(button).toBeDisabled();

    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("호출부 className 을 병합한다", () => {
    render(<Button className="mt-4">라벨</Button>);
    expect(screen.getByRole("button", { name: "라벨" })).toHaveClass("mt-4");
  });
});

describe("Spinner — 로딩 인디케이터 (7.1)", () => {
  it("접근 가능한 role=status 로 렌더된다", () => {
    render(<Spinner />);
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    // 시각적으로 숨겨진 라벨이라도 접근 가능한 이름을 가진다.
    expect(status).toHaveAccessibleName();
  });
});

describe("EmptyState — 빈/오류 상태 표시 (7.1)", () => {
  it("title 과 message 를 렌더한다", () => {
    render(<EmptyState title="문서가 없습니다" message="새 문서를 만들어 보세요." />);
    expect(screen.getByText("문서가 없습니다")).toBeInTheDocument();
    expect(screen.getByText("새 문서를 만들어 보세요.")).toBeInTheDocument();
  });

  it("action/children 슬롯을 렌더한다", () => {
    render(
      <EmptyState title="비어 있음">
        <button type="button">새로 만들기</button>
      </EmptyState>,
    );
    expect(screen.getByRole("button", { name: "새로 만들기" })).toBeInTheDocument();
  });
});

describe("ErrorMessage — ApiError 표시 (7.4)", () => {
  it("error 가 null 이면 아무것도 렌더하지 않는다", () => {
    const { container } = render(<ErrorMessage error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("error.message 를 표시한다", () => {
    const error = new ApiError({
      status: 400,
      code: "validation_error",
      message: "입력을 확인하세요.",
    });
    render(<ErrorMessage error={error} />);
    expect(screen.getByText("입력을 확인하세요.")).toBeInTheDocument();
  });

  it("field_errors 를 목록으로 표시한다 (각 field: message)", () => {
    const error = parseErrorResponse(422, {
      code: "validation_error",
      message: "검증에 실패했습니다.",
      field_errors: [
        { field: "name", message: "required" },
        { field: "email", message: "invalid" },
      ],
    });
    render(<ErrorMessage error={error} />);

    expect(screen.getByText("검증에 실패했습니다.")).toBeInTheDocument();

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    // 두 필드 오류가 모두 표시된다.
    expect(screen.getByText(/name/)).toBeInTheDocument();
    expect(screen.getByText(/required/)).toBeInTheDocument();
    expect(screen.getByText(/email/)).toBeInTheDocument();
    expect(screen.getByText(/invalid/)).toBeInTheDocument();
  });

  it("field_errors 가 비어 있으면 목록을 렌더하지 않는다", () => {
    const error = new ApiError({
      status: 500,
      code: "internal",
      message: "예기치 못한 오류가 발생했습니다.",
    });
    render(<ErrorMessage error={error} />);
    expect(screen.getByText("예기치 못한 오류가 발생했습니다.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
