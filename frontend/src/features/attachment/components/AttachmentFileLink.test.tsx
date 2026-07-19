import {
  describe,
  it,
  expect,
  afterEach,
  beforeEach,
  vi,
  type Mock,
} from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { ApiError } from "@/shared/api/errors";
import { AttachmentFileLink } from "./AttachmentFileLink";
import { attachmentApi } from "../api/attachmentApi";

// blob 취득만 격리 검증하기 위해 첨부 API 를 모킹한다(HTTP 부수효과 제외).
vi.mock("../api/attachmentApi", () => ({
  attachmentApi: {
    fetchAttachmentBlob: vi.fn(),
    uploadAttachment: vi.fn(),
  },
}));

const mockedFetchBlob = attachmentApi.fetchAttachmentBlob as unknown as Mock;

/**
 * AttachmentFileLink 는 파일 첨부를 이미지가 아닌 다운로드 가능한 링크(버튼)로 표시하고,
 * 활성화 시 `attachmentApi.fetchAttachmentBlob(id)` 로 인증 blob 을 취득해 오브젝트 URL +
 * `download=original_name` 으로 다운로드를 트리거한다. 404/403 은 안전 placeholder,
 * 그 외 오류(5xx·네트워크)는 오류 표시로 폴백하며 깨진 링크로 남기지 않는다
 * (Requirements 4.1, 4.2, 4.3, 4.4, 5.1).
 */
describe("AttachmentFileLink — 인증 파일 다운로드 링크·placeholder/오류 폴백 (4.1, 4.2, 4.3, 4.4, 5.1)", () => {
  let clickSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
    clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    mockedFetchBlob.mockReset();
    clickSpy.mockRestore();
    vi.restoreAllMocks();
  });

  it("기본: 파일명을 담은 다운로드 링크(버튼)를 표시하고 <img> 를 렌더하지 않는다", () => {
    const { container } = render(
      <AttachmentFileLink attachmentId={1} fileName="report.pdf" />,
    );

    expect(
      screen.getByRole("button", { name: /report\.pdf/ }),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("활성화: fetchAttachmentBlob(id) 로 취득한 blob 을 original_name 으로 다운로드 트리거한다", async () => {
    const blob = new Blob(["data"], { type: "application/pdf" });
    mockedFetchBlob.mockResolvedValue(blob);

    const user = userEvent.setup();
    render(<AttachmentFileLink attachmentId={42} fileName="report.pdf" />);

    await user.click(screen.getByRole("button", { name: /report\.pdf/ }));

    await waitFor(() => {
      expect(mockedFetchBlob).toHaveBeenCalledWith(42);
    });
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    // 트리거한 앵커의 download 속성이 original_name 이어야 한다.
    const anchor = clickSpy.mock.instances[0] as HTMLAnchorElement;
    expect(anchor.getAttribute("download")).toBe("report.pdf");
    expect(anchor.getAttribute("href")).toBe("blob:mock");
    // 오브젝트 URL 은 트리거 직후 해제되어 누수되지 않는다.
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });

  it("404: 안전 placeholder(unavailable)로 폴백하고 깨진 링크로 남기지 않는다", async () => {
    mockedFetchBlob.mockRejectedValue(
      new ApiError({ status: 404, code: "not_found", message: "x" }),
    );

    const user = userEvent.setup();
    render(<AttachmentFileLink attachmentId={1} fileName="gone.txt" />);

    await user.click(screen.getByRole("button", { name: /gone\.txt/ }));

    expect(
      await screen.findByText("이 첨부를 표시할 수 없습니다"),
    ).toBeInTheDocument();
    expect(clickSpy).not.toHaveBeenCalled();
  });

  it("403: 안전 placeholder(unavailable)로 폴백한다", async () => {
    mockedFetchBlob.mockRejectedValue(
      new ApiError({ status: 403, code: "forbidden", message: "x" }),
    );

    const user = userEvent.setup();
    render(<AttachmentFileLink attachmentId={1} fileName="secret.txt" />);

    await user.click(screen.getByRole("button", { name: /secret\.txt/ }));

    expect(
      await screen.findByText("이 첨부를 표시할 수 없습니다"),
    ).toBeInTheDocument();
  });

  it("5xx: 오류를 표시(role=alert)하고 링크는 재시도 가능하게 유지한다", async () => {
    mockedFetchBlob.mockRejectedValue(
      new ApiError({ status: 500, code: "internal", message: "서버 오류" }),
    );

    const user = userEvent.setup();
    render(<AttachmentFileLink attachmentId={1} fileName="report.pdf" />);

    await user.click(screen.getByRole("button", { name: /report\.pdf/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("서버 오류");
    // placeholder(unavailable)가 아니라 오류이며, 링크는 남아 재시도 가능하다.
    expect(
      screen.queryByText("이 첨부를 표시할 수 없습니다"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /report\.pdf/ }),
    ).toBeInTheDocument();
  });
});
