import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { RoleSelect } from "./RoleSelect";
import type { MemberRole } from "../api/types";

// RoleSelect 는 MemberRole 3값(owner/editor/viewer)만 방출하는 순수 프리미티브다(Req 3.4).
// 옵션 집합·onChange 방출값·비활성 전달을 관찰한다.

describe("RoleSelect", () => {
  it("정확히 3개 옵션(owner/editor/viewer)만 렌더한다 (Req 3.4)", () => {
    render(<RoleSelect value="editor" onChange={() => {}} />);

    const options = screen.getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((o) => o.value)).toEqual(["owner", "editor", "viewer"]);
  });

  it("현재 value 를 선택 상태로 반영한다", () => {
    render(<RoleSelect value="viewer" onChange={() => {}} />);
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("viewer");
  });

  it("옵션 선택 시 onChange 를 해당 MemberRole 로 호출한다", () => {
    const onChange = vi.fn<(role: MemberRole) => void>();
    render(<RoleSelect value="viewer" onChange={onChange} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "owner" } });
    expect(onChange).toHaveBeenCalledWith("owner");

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "editor" } });
    expect(onChange).toHaveBeenCalledWith("editor");
  });

  it("옵션에 없는 4번째 값은 방출할 수 없다(옵션 집합이 3값으로 폐쇄)", () => {
    const onChange = vi.fn<(role: MemberRole) => void>();
    render(<RoleSelect value="owner" onChange={onChange} />);

    const values = (screen.getAllByRole("option") as HTMLOptionElement[]).map((o) => o.value);
    expect(values).not.toContain("admin");
    expect(values).not.toContain("guest");
    expect(values).toHaveLength(3);
  });

  it("disabled 를 select 에 전달한다", () => {
    render(<RoleSelect value="owner" onChange={() => {}} disabled />);
    expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true);
  });

  it("id·label 을 연결한다", () => {
    render(<RoleSelect value="owner" onChange={() => {}} id="member_role" label="역할" />);
    // label 텍스트로 접근 가능해야 한다(htmlFor↔id 연결).
    expect(screen.getByLabelText("역할")).toBe(screen.getByRole("combobox"));
  });
});
