import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { AssignableUserSelect } from "./AssignableUserSelect";
import type { AssignableUser } from "../api/types";
import { ApiError } from "@/shared/api/errors";

// AssignableUserSelect 는 순수 표시 컴포넌트로 status 를 판별자로 삼아 정확히 하나의
// 표면(Spinner/EmptyState/ErrorMessage/select)만 렌더한다(design "AssignableUserSelect",
// Req 3.1·3.5·3.6·4.1·1.3). 데이터·reload 는 상위 훅이 소유한다.

const USERS: AssignableUser[] = [
  { id: 1, name: "Alice", email: "alice@example.com" },
  { id: 2, name: "Bob", email: null },
];

describe("AssignableUserSelect", () => {
  it('status "loading" 시 Spinner 를 렌더하고 select 를 노출하지 않는다 (Req 3.6)', () => {
    render(
      <AssignableUserSelect
        users={[]}
        status="loading"
        error={null}
        value={null}
        onChange={() => {}}
      />,
    );

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it('status "ready" 이고 users 가 비면 EmptyState 안내를 렌더하고 선택 옵션이 없다 (Req 3.5)', () => {
    render(
      <AssignableUserSelect
        users={[]}
        status="ready"
        error={null}
        value={null}
        onChange={() => {}}
      />,
    );

    expect(screen.getByText("배정 가능한 사용자가 없습니다")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
  });

  it('status "error" 시 ErrorMessage 로 오류 메시지를 표시한다 (Req 4.1)', () => {
    const error = new ApiError({ status: 403, code: "forbidden", message: "권한이 없습니다." });
    render(
      <AssignableUserSelect
        users={[]}
        status="error"
        error={error}
        value={null}
        onChange={() => {}}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("권한이 없습니다.");
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it('status "ready" + users 시 옵션을 "이름 (email)" 로 렌더하고 email 없으면 이름만 표시한다 (Req 3.1·1.3)', () => {
    render(
      <AssignableUserSelect
        users={USERS}
        status="ready"
        error={null}
        value={null}
        onChange={() => {}}
      />,
    );

    expect(screen.getByRole("combobox")).toBeInTheDocument();
    // 이메일이 있는 사용자: "이름 (email)"
    expect(screen.getByRole("option", { name: "Alice (alice@example.com)" })).toBeInTheDocument();
    // 이메일이 null 인 사용자: 이름만 (Req 1.3)
    expect(screen.getByRole("option", { name: "Bob" })).toBeInTheDocument();
  });

  it("옵션 선택 시 onChange 를 해당 user id 로 호출한다 (Req 3.1)", () => {
    const onChange = vi.fn<(userId: number | null) => void>();
    render(
      <AssignableUserSelect
        users={USERS}
        status="ready"
        error={null}
        value={null}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2" } });
    expect(onChange).toHaveBeenCalledWith(2);
  });

  it("빈 선택(placeholder) 을 고르면 onChange(null) 을 호출한다", () => {
    const onChange = vi.fn<(userId: number | null) => void>();
    render(
      <AssignableUserSelect
        users={USERS}
        status="ready"
        error={null}
        value={1}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("value 를 select 의 선택 상태로 반영한다", () => {
    render(
      <AssignableUserSelect
        users={USERS}
        status="ready"
        error={null}
        value={2}
        onChange={() => {}}
      />,
    );
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("2");
  });

  it("disabled 를 select 에 전달한다", () => {
    render(
      <AssignableUserSelect
        users={USERS}
        status="ready"
        error={null}
        value={null}
        onChange={() => {}}
        disabled
      />,
    );
    expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true);
  });
});
