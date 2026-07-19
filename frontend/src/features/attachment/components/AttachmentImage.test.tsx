import { describe, it, expect, afterEach, vi, type Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ApiError } from "@/shared/api/errors";
import { AttachmentImage } from "./AttachmentImage";
import { useAttachmentResource } from "../hooks/useAttachmentResource";

// 렌더 분기만 격리 검증하기 위해 리소스 훅을 모킹한다(HTTP·object URL 부수효과 제외).
vi.mock("../hooks/useAttachmentResource", () => ({
  useAttachmentResource: vi.fn(),
}));

const mockedHook = useAttachmentResource as unknown as Mock;

/**
 * AttachmentImage 는 `useAttachmentResource(id, { kind: "image" })` 리소스 상태만 보고
 * 렌더한다: `ready` 는 인증 blob 오브젝트 URL 로 `<img>` 렌더(원시 /attachments src 금지),
 * `loading` 은 Spinner, `unavailable`(404/403·admin 보관 포함) 과 `error` 는 안전
 * placeholder. 컴포넌트는 첨부의 보관·소멸을 재판정하지 않고 관측 상태만 반영한다
 * (Requirements 3.1, 3.3, 5.1, 5.2, 5.5).
 */
describe("AttachmentImage — 인증 이미지 렌더·placeholder 폴백 (3.1, 3.3, 5.1, 5.2, 5.5)", () => {
  afterEach(() => {
    cleanup();
    mockedHook.mockReset();
  });

  it("ready: 오브젝트 URL 로 <img> 를 렌더하고 alt 를 반영한다", () => {
    mockedHook.mockReturnValue({
      status: "ready",
      objectUrl: "blob:x",
      kind: "image",
      fileName: "a.png",
    });

    render(<AttachmentImage attachmentId={1} alt="설명" />);

    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "blob:x");
    expect(img).toHaveAttribute("alt", "설명");
  });

  it("ready: alt 미지정 시 빈 alt 로 렌더한다(장식 이미지 접근성)", () => {
    mockedHook.mockReturnValue({
      status: "ready",
      objectUrl: "blob:y",
      kind: "image",
      fileName: "a.png",
    });

    const { container } = render(<AttachmentImage attachmentId={1} />);

    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute("alt", "");
  });

  it("훅을 attachmentId 와 kind:'image' 로 호출한다", () => {
    mockedHook.mockReturnValue({
      status: "ready",
      objectUrl: "blob:x",
      kind: "image",
      fileName: "a.png",
    });

    render(<AttachmentImage attachmentId={42} />);

    expect(mockedHook).toHaveBeenCalledWith(42, { kind: "image" });
  });

  it("loading: Spinner(role=status)를 노출하고 <img> 를 렌더하지 않는다", () => {
    mockedHook.mockReturnValue({ status: "loading" });

    const { container } = render(<AttachmentImage attachmentId={1} />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("unavailable(not_found): placeholder 를 렌더하고 원시 /attachments src 를 주입하지 않는다", () => {
    mockedHook.mockReturnValue({ status: "unavailable", reason: "not_found" });

    const { container } = render(<AttachmentImage attachmentId={1} />);

    expect(screen.getByText("이 첨부를 표시할 수 없습니다")).toBeInTheDocument();
    expect(container.querySelector("img[src='/attachments/1']")).toBeNull();
  });

  it("unavailable(forbidden): placeholder 를 렌더한다", () => {
    mockedHook.mockReturnValue({ status: "unavailable", reason: "forbidden" });

    render(<AttachmentImage attachmentId={1} />);

    expect(screen.getByText("이 첨부를 표시할 수 없습니다")).toBeInTheDocument();
  });

  it("admin 보관 첨부(백엔드 404 → unavailable): placeholder 를 렌더한다(Req 5.5)", () => {
    // 프론트는 보관 여부를 재판정하지 않고 서빙 관측 결과(unavailable)만 반영한다.
    mockedHook.mockReturnValue({ status: "unavailable", reason: "not_found" });

    const { container } = render(<AttachmentImage attachmentId={7} />);

    expect(screen.getByText("이 첨부를 표시할 수 없습니다")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("error: 오류 변형 placeholder 를 렌더한다(일시 오류·unavailable 과 구분)", () => {
    mockedHook.mockReturnValue({
      status: "error",
      error: new ApiError({ status: 500, code: "internal", message: "x" }),
    });

    const { container } = render(<AttachmentImage attachmentId={1} />);

    expect(screen.getByText("첨부를 불러오지 못했습니다")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
