import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useAttachmentUpload } from "./useAttachmentUpload";
import type { InsertContext } from "./useAttachmentUpload";
import { attachmentApi } from "../api/attachmentApi";
import {
  buildPlaceholderToken,
  buildReferenceMarkdown,
  buildErrorMarker,
} from "../lib/attachmentReference";
import type { AttachmentRead } from "../types";
import { ApiError } from "@/shared/api/errors";

/**
 * useAttachmentUpload 는 업로드 1건마다 uploadId 를 생성해 진행 자리표시자 토큰을
 * InsertContext 로 삽입하고, attachmentApi.uploadAttachment 성공(201) 시 실제 참조
 * markdown 으로 치환하며 AttachmentRead 를 반환한다. 실패(422/404/403) 시 안전한 오류
 * 표시로 치환하고 ApiError 를 UploadItem.error 로 그대로 표면화하며 null 을 반환한다.
 * 여러 업로드는 uploadId 키의 Map 으로 독립 추적되어(해상 순서 무관) 서로 침범하지 않는다.
 * attachmentApi 만 모킹하고 attachmentReference 실제 구현·가짜 InsertContext 를 사용한다
 * (Requirements 1.1·1.3·1.5·2.1·2.2·2.3·2.4·2.5·6.4).
 */
vi.mock("../api/attachmentApi", () => ({
  attachmentApi: {
    uploadAttachment: vi.fn(),
    fetchAttachmentBlob: vi.fn(),
  },
}));

const uploadMock = attachmentApi.uploadAttachment as unknown as Mock;

function makeInsert(): InsertContext {
  return {
    insertPlaceholder: vi.fn(),
    replaceToken: vi.fn(),
  };
}

function att(overrides: Partial<AttachmentRead> = {}): AttachmentRead {
  return {
    id: 100,
    workspace_id: 7,
    document_id: 42,
    kind: "image",
    original_name: "pic.png",
    is_archived: false,
    created_at: "2026-01-01T00:00:00Z",
    url: "/attachments/100",
    ...overrides,
  };
}

/** 외부에서 해상 시점을 제어하는 deferred promise. */
function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  uploadMock.mockReset();
});

describe("useAttachmentUpload", () => {
  it("성공: 자리표시자 삽입→201 실제 참조 치환·AttachmentRead 반환·done 상태(Req 2.1·2.2)", async () => {
    const image = att({ id: 100, kind: "image", original_name: "pic.png", url: "/attachments/100" });
    uploadMock.mockResolvedValue(image);
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    const file = new File(["binary"], "pic.png", { type: "image/png" });
    let returned: AttachmentRead | null = null;
    await act(async () => {
      returned = await result.current.startUpload({
        file,
        fileName: "pic.png",
        kind: "image",
      });
    });

    // uploadId 는 훅 내부 카운터로 결정적: 첫 업로드는 "upload-1".
    const uploadId = "upload-1";
    const token = buildPlaceholderToken(uploadId);

    expect(insert.insertPlaceholder).toHaveBeenCalledWith(uploadId, token);
    expect(insert.replaceToken).toHaveBeenCalledWith(
      uploadId,
      buildReferenceMarkdown(image),
    );
    expect(uploadMock).toHaveBeenCalledWith(42, file, "pic.png", "image");
    expect(returned).toBe(image);

    const entry = result.current.uploads.get(uploadId);
    expect(entry?.status).toBe("done");
    expect(entry?.attachment).toBe(image);
    expect(entry?.error).toBeNull();
    expect(entry?.fileName).toBe("pic.png");
  });

  it("파일(kind:file)도 다운로드 링크 참조로 치환한다(Req 1.3)", async () => {
    const fileAtt = att({ id: 200, kind: "file", original_name: "report.pdf", url: "/attachments/200" });
    uploadMock.mockResolvedValue(fileAtt);
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    await act(async () => {
      await result.current.startUpload({
        file: new Blob(["x"]),
        fileName: "report.pdf",
      });
    });

    expect(insert.replaceToken).toHaveBeenCalledWith(
      "upload-1",
      buildReferenceMarkdown(fileAtt),
    );
    // kind 미지정 → uploadAttachment 에 undefined 로 위임(백엔드 추론).
    expect(uploadMock).toHaveBeenCalledWith(42, expect.any(Blob), "report.pdf", undefined);
  });

  it("422 실패: 오류 표시 치환·ApiError 표면화·null 반환·error 상태(Req 2.3·2.5·6.4)", async () => {
    const err = new ApiError({ status: 422, code: "unprocessable", message: "too large" });
    uploadMock.mockRejectedValue(err);
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    let returned: AttachmentRead | null = att();
    await act(async () => {
      returned = await result.current.startUpload({
        file: new Blob(["x"]),
        fileName: "big.png",
        kind: "image",
      });
    });

    const uploadId = "upload-1";
    expect(insert.replaceToken).toHaveBeenCalledWith(
      uploadId,
      buildErrorMarker(uploadId),
    );
    expect(returned).toBeNull();

    const entry = result.current.uploads.get(uploadId);
    expect(entry?.status).toBe("error");
    expect(entry?.error).toBe(err);
    expect(entry?.attachment).toBeNull();
  });

  it("404 실패도 동일하게 오류 표시·ApiError 표면화한다(Req 2.5)", async () => {
    const err = new ApiError({ status: 404, code: "not_found", message: "문서 없음" });
    uploadMock.mockRejectedValue(err);
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    let returned: AttachmentRead | null = att();
    await act(async () => {
      returned = await result.current.startUpload({
        file: new Blob(["x"]),
        fileName: "x.png",
      });
    });

    expect(returned).toBeNull();
    const entry = result.current.uploads.get("upload-1");
    expect(entry?.status).toBe("error");
    expect(entry?.error).toBe(err);
  });

  it("403 실패도 동일하게 ApiError 를 표면화한다(Req 2.5)", async () => {
    const err = new ApiError({ status: 403, code: "forbidden", message: "권한 없음" });
    uploadMock.mockRejectedValue(err);
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    await act(async () => {
      await result.current.startUpload({ file: new Blob(["x"]), fileName: "x.png" });
    });

    const entry = result.current.uploads.get("upload-1");
    expect(entry?.status).toBe("error");
    expect(entry?.error).toBe(err);
  });

  it("동시 업로드: 역순 해상에도 각 uploadId 독립 추적·치환(비침범, Req 2.4)", async () => {
    const d1 = deferred<AttachmentRead>();
    const d2 = deferred<AttachmentRead>();
    const first = att({ id: 100, original_name: "first.png", url: "/attachments/100" });
    const second = att({ id: 200, original_name: "second.png", url: "/attachments/200" });
    uploadMock.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise);
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    // 두 업로드를 연달아 시작(각각 promise 는 아직 미해상).
    let p1!: Promise<AttachmentRead | null>;
    let p2!: Promise<AttachmentRead | null>;
    act(() => {
      p1 = result.current.startUpload({ file: new Blob(["a"]), fileName: "first.png", kind: "image" });
      p2 = result.current.startUpload({ file: new Blob(["b"]), fileName: "second.png", kind: "image" });
    });

    // 둘 다 진행 중 자리표시자가 자신의 uploadId 로 삽입됨.
    expect(insert.insertPlaceholder).toHaveBeenCalledWith("upload-1", buildPlaceholderToken("upload-1"));
    expect(insert.insertPlaceholder).toHaveBeenCalledWith("upload-2", buildPlaceholderToken("upload-2"));

    await waitFor(() => {
      expect(result.current.uploads.get("upload-1")?.status).toBe("uploading");
      expect(result.current.uploads.get("upload-2")?.status).toBe("uploading");
    });

    // 역순 해상: 두 번째가 먼저 완료.
    await act(async () => {
      d2.resolve(second);
      await p2;
    });
    await act(async () => {
      d1.resolve(first);
      await p1;
    });

    // 각 uploadId 는 자기 참조로만 치환됨(교차 오염 없음).
    expect(insert.replaceToken).toHaveBeenCalledWith("upload-2", buildReferenceMarkdown(second));
    expect(insert.replaceToken).toHaveBeenCalledWith("upload-1", buildReferenceMarkdown(first));

    const e1 = result.current.uploads.get("upload-1");
    const e2 = result.current.uploads.get("upload-2");
    expect(e1?.status).toBe("done");
    expect(e1?.attachment).toBe(first);
    expect(e2?.status).toBe("done");
    expect(e2?.attachment).toBe(second);
  });

  it("동시 업로드 중 하나만 실패해도 다른 업로드는 영향받지 않는다(Req 2.4)", async () => {
    const d1 = deferred<AttachmentRead>();
    const d2 = deferred<AttachmentRead>();
    const ok = att({ id: 100, original_name: "ok.png", url: "/attachments/100" });
    const err = new ApiError({ status: 422, code: "unprocessable", message: "too large" });
    uploadMock.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise);
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    let p1!: Promise<AttachmentRead | null>;
    let p2!: Promise<AttachmentRead | null>;
    act(() => {
      p1 = result.current.startUpload({ file: new Blob(["a"]), fileName: "ok.png", kind: "image" });
      p2 = result.current.startUpload({ file: new Blob(["b"]), fileName: "bad.png", kind: "image" });
    });

    await act(async () => {
      d2.reject(err);
      await p2;
    });
    await act(async () => {
      d1.resolve(ok);
      await p1;
    });

    const e1 = result.current.uploads.get("upload-1");
    const e2 = result.current.uploads.get("upload-2");
    expect(e1?.status).toBe("done");
    expect(e1?.attachment).toBe(ok);
    expect(e1?.error).toBeNull();
    expect(e2?.status).toBe("error");
    expect(e2?.error).toBe(err);
    expect(e2?.attachment).toBeNull();
  });

  it("비-ApiError throw 도 방어적으로 ApiError 로 정규화해 표면화한다(Req 6.4)", async () => {
    uploadMock.mockRejectedValue(new TypeError("boom"));
    const insert = makeInsert();

    const { result } = renderHook(() => useAttachmentUpload(42, insert));

    let returned: AttachmentRead | null = att();
    await act(async () => {
      returned = await result.current.startUpload({ file: new Blob(["x"]), fileName: "x.png" });
    });

    expect(returned).toBeNull();
    const entry = result.current.uploads.get("upload-1");
    expect(entry?.status).toBe("error");
    expect(entry?.error).toBeInstanceOf(ApiError);
    expect(insert.replaceToken).toHaveBeenCalledWith("upload-1", buildErrorMarker("upload-1"));
  });
});
