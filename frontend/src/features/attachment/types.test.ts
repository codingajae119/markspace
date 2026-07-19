/**
 * s21 attachment feature 계약 미러 타입의 컴파일-타임 형태 가드.
 *
 * 백엔드 `app/attachment/schemas.py`(`AttachmentRead`·`AttachmentKind`)와 프론트 파생
 * 상태 타입(`UploadItem`·`UploadStatus`·`AttachmentResourceState`)이 명세된 형태와 1:1로
 * 대응함을 유효 리터럴 구성으로 증명한다(새 필드 발명 없음).
 */
import { describe, expect, it } from "vitest";

import { ApiError } from "@/shared/api/errors";

import type {
  AttachmentKind,
  AttachmentRead,
  AttachmentResourceState,
  UploadItem,
  UploadStatus,
} from "./types";

describe("attachment 계약 미러 타입", () => {
  it("AttachmentRead 는 백엔드 스키마 필드와 1:1로 구성된다", () => {
    const read: AttachmentRead = {
      id: 1,
      workspace_id: 2,
      document_id: 3,
      kind: "image",
      original_name: "photo.png",
      is_archived: false,
      created_at: "2026-07-19T00:00:00Z",
      url: "/attachments/1",
    };

    expect(read.kind).toBe("image");
    expect(read.url).toBe("/attachments/1");
    // url 은 서버 산정 파생값(재구성 금지) — 문자열 규약만 검증.
    expect(typeof read.created_at).toBe("string");
  });

  it("AttachmentKind 는 image|file 유니온이다", () => {
    const kinds: AttachmentKind[] = ["image", "file"];
    expect(kinds).toEqual(["image", "file"]);
  });

  it("UploadItem 은 업로드 자리표시자 파생 상태를 담는다", () => {
    const statuses: UploadStatus[] = ["uploading", "done", "error"];
    const item: UploadItem = {
      uploadId: "u-1",
      status: "uploading",
      fileName: "photo.png",
      attachment: null,
      error: null,
    };

    expect(statuses).toContain(item.status);
    expect(item.attachment).toBeNull();
    expect(item.error).toBeNull();
  });

  it("AttachmentResourceState 는 4개 판별 변형을 표현한다", () => {
    const loading: AttachmentResourceState = { status: "loading" };
    const ready: AttachmentResourceState = {
      status: "ready",
      objectUrl: "blob:x",
      kind: "file",
      fileName: "doc.pdf",
    };
    const unavailable: AttachmentResourceState = {
      status: "unavailable",
      reason: "not_found",
    };
    const error: AttachmentResourceState = {
      status: "error",
      error: new ApiError({ status: 500, code: "internal", message: "boom" }),
    };

    expect(loading.status).toBe("loading");
    expect(ready.status).toBe("ready");
    expect(unavailable.status === "unavailable" && unavailable.reason).toBe(
      "not_found",
    );
    expect(error.status === "error" && error.error).toBeInstanceOf(ApiError);
  });
});
