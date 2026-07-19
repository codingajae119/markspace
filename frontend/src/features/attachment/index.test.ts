/**
 * s21 첨부 feature 소비 진입점(index.ts) 배럴 export 계약 테스트 (task 5.1).
 *
 * 이 배럴은 s20 편집 표면·s19/s22 읽기·공유 뷰가 단일 진입점으로 소비하는 업로드/렌더
 * 브리지 + 렌더 컴포넌트 + 공개 타입을 노출한다(비행동적 re-export surface). 런타임 값
 * export 의 존재/종류를 고정하고, 타입 전용 export 는 컴파일 시 usage(아래 타입 참조)로
 * typecheck 가 보증한다(Req 6.6·7.3·7.4·7.5).
 */
import { describe, expect, it } from "vitest";

import * as attachment from "./index";
import type {
  AttachmentKind,
  AttachmentRead,
  AttachmentResourceState,
  AttachmentFileLinkProps,
  AttachmentImageProps,
  AttachmentPlaceholderProps,
  InsertContext,
  UploadItem,
  UploadStatus,
} from "./index";

describe("features/attachment/index (배럴 소비 진입점)", () => {
  it("업로드 브리지 + 업로드 훅을 노출한다", () => {
    expect(attachment.useEditorUploadBridge).toBeTypeOf("function");
    expect(attachment.useAttachmentUpload).toBeTypeOf("function");
    expect(attachment.useAttachmentResource).toBeTypeOf("function");
    expect(attachment.locateToken).toBeTypeOf("function");
  });

  it("렌더 브리지 + 4개 렌더 컴포넌트를 노출한다", () => {
    expect(attachment.buildAttachmentRenderers).toBeTypeOf("function");
    expect(attachment.AttachmentImage).toBeTypeOf("function");
    expect(attachment.AttachmentFileLink).toBeTypeOf("function");
    expect(attachment.AttachmentPlaceholder).toBeTypeOf("function");
  });

  it("api·순수 참조 유틸을 노출한다", () => {
    expect(attachment.attachmentApi).toBeTypeOf("object");
    expect(attachment.attachmentApi.uploadAttachment).toBeTypeOf("function");
    expect(attachment.attachmentApi.fetchAttachmentBlob).toBeTypeOf("function");
    expect(attachment.buildReferenceMarkdown).toBeTypeOf("function");
    expect(attachment.buildPlaceholderToken).toBeTypeOf("function");
    expect(attachment.buildErrorMarker).toBeTypeOf("function");
    expect(attachment.replacePlaceholder).toBeTypeOf("function");
    expect(attachment.resolveAttachmentReference).toBeTypeOf("function");
  });

  it("실수로 undefined 를 export 하지 않는다", () => {
    for (const value of Object.values(attachment)) {
      expect(value).toBeDefined();
    }
  });

  it("공개 타입을 컴파일 시 소비할 수 있다(typecheck 보증)", () => {
    // 런타임 값이 아닌 타입은 여기서 구조적 usage 로 존재를 고정한다(verbatimModuleSyntax).
    const kind: AttachmentKind = "image";
    const read: AttachmentRead = {
      id: 1,
      workspace_id: 1,
      document_id: 1,
      kind,
      original_name: "a.png",
      is_archived: false,
      created_at: "2026-01-01T00:00:00Z",
      url: "/attachments/1",
    };
    const item: UploadItem = {
      uploadId: "upload-1",
      status: "done" satisfies UploadStatus,
      fileName: "a.png",
      attachment: read,
      error: null,
    };
    const resourceState: AttachmentResourceState = { status: "loading" };
    const insert: InsertContext = {
      insertPlaceholder: () => undefined,
      replaceToken: () => undefined,
    };
    const imageProps: AttachmentImageProps = { attachmentId: 1 };
    const fileProps: AttachmentFileLinkProps = { attachmentId: 1, fileName: "a" };
    const placeholderProps: AttachmentPlaceholderProps = { variant: "uploading" };

    expect(item.attachment?.url).toBe("/attachments/1");
    expect(resourceState.status).toBe("loading");
    expect(insert.insertPlaceholder).toBeTypeOf("function");
    expect(imageProps.attachmentId).toBe(1);
    expect(fileProps.fileName).toBe("a");
    expect(placeholderProps.variant).toBe("uploading");
  });
});
