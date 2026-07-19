import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { AttachmentPlaceholder } from "./AttachmentPlaceholder";

/**
 * AttachmentPlaceholder 는 `uploading`·`error`·`unavailable` 세 변형을 안전하게
 * (깨진 이미지/죽은 링크가 아니라) 표현한다. `uploading` 은 공용 Spinner(role=status)를
 * 재사용하고, `error`·`unavailable` 은 일반적(generic) 안내 문구만 노출하여 내부 세부정보
 * (상태 코드·경로·원인)를 과다 노출하지 않는다. `label` prop 으로 기본 문구를 덮어쓸 수
 * 있다 (Requirements 2.1, 5.2).
 */
describe("AttachmentPlaceholder — 안전 placeholder (2.1, 5.2)", () => {
  afterEach(() => {
    cleanup();
  });

  it("uploading: 공용 Spinner(role=status)를 노출한다", () => {
    render(<AttachmentPlaceholder variant="uploading" />);
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(status).toHaveAccessibleName();
  });

  it("uploading: label prop 으로 접근 가능한 라벨을 덮어쓴다", () => {
    render(<AttachmentPlaceholder variant="uploading" label="이미지 업로드 중" />);
    expect(screen.getByRole("status")).toHaveAccessibleName("이미지 업로드 중");
  });

  it("error: 안전한 기본 문구를 노출하고 깨진 img/링크를 렌더하지 않는다", () => {
    const { container } = render(<AttachmentPlaceholder variant="error" />);
    expect(screen.getByText("첨부를 불러오지 못했습니다")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("error: label prop 으로 기본 문구를 덮어쓴다", () => {
    render(<AttachmentPlaceholder variant="error" label="다시 시도해 주세요" />);
    expect(screen.getByText("다시 시도해 주세요")).toBeInTheDocument();
    expect(screen.queryByText("첨부를 불러오지 못했습니다")).not.toBeInTheDocument();
  });

  it("unavailable: 일반적 안내 문구를 노출하고 깨진 img/링크를 렌더하지 않는다", () => {
    const { container } = render(<AttachmentPlaceholder variant="unavailable" />);
    expect(screen.getByText("이 첨부를 표시할 수 없습니다")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("unavailable: 내부 세부정보(상태 코드·경로 등)를 과다 노출하지 않는다", () => {
    const { container } = render(<AttachmentPlaceholder variant="unavailable" />);
    const text = container.textContent ?? "";
    // 404/403 같은 상태 코드나 내부 경로가 노출되지 않는다.
    expect(text).not.toMatch(/40[34]/);
    expect(text).not.toMatch(/attachments\//);
    expect(text).not.toMatch(/forbidden|not_found/i);
  });

  it("error·unavailable: 접근 가능한 role 로 상태를 노출한다", () => {
    render(<AttachmentPlaceholder variant="error" />);
    // role=img 로 안내(비로딩 시각 상태)를 노출한다.
    expect(
      screen.getByRole("img", { name: "첨부를 불러오지 못했습니다" }),
    ).toBeInTheDocument();
  });
});
