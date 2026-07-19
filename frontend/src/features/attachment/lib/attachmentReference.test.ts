import { describe, it, expect } from "vitest";

import {
  buildReferenceMarkdown,
  buildPlaceholderToken,
  replacePlaceholder,
  buildErrorMarker,
  resolveAttachmentReference,
} from "./attachmentReference";
import type { AttachmentRead } from "../types";

/**
 * attachmentReference 는 첨부 응답(`AttachmentRead`)의 `kind`·`url`(서버 산정 파생값)로부터
 * 콘텐츠 참조 markdown 을 조립하고, 업로드 진행 자리표시자 토큰을 생성/치환하는 순수 함수
 * 모음이다. 부수효과·첨부 상태 판정이 없어 단위 테스트만으로 계약을 고정한다
 * (Requirements 1.3, 2.1, 2.2, 2.3, 3.5, 7.2).
 */
function sampleAtt(partial: Partial<AttachmentRead> = {}): AttachmentRead {
  return {
    id: 42,
    workspace_id: 1,
    document_id: 7,
    kind: "image",
    original_name: "photo.png",
    is_archived: false,
    created_at: "2026-01-01T00:00:00Z",
    url: "/attachments/42",
    ...partial,
  };
}

describe("buildReferenceMarkdown", () => {
  it("image kind → 이미지 참조(`![name](url)`), url 은 응답값 그대로 사용", () => {
    const att = sampleAtt({ kind: "image", original_name: "photo.png", url: "/attachments/42" });
    expect(buildReferenceMarkdown(att)).toBe("![photo.png](/attachments/42)");
  });

  it("file kind → 다운로드 링크(`[name](url)`)", () => {
    const att = sampleAtt({ kind: "file", original_name: "report.pdf", url: "/attachments/99" });
    expect(buildReferenceMarkdown(att)).toBe("[report.pdf](/attachments/99)");
  });

  it("url 을 재구성하지 않고 응답값을 그대로 사용한다(Req 7.2)", () => {
    // id 와 무관한 임의 url 을 주어도 재구성(`/attachments/${id}`)하지 않고 그대로 써야 한다.
    const att = sampleAtt({ id: 42, kind: "image", url: "/attachments/12345?v=abc", original_name: "x y.png" });
    expect(buildReferenceMarkdown(att)).toBe("![x y.png](/attachments/12345?v=abc)");
  });
});

describe("buildPlaceholderToken / replacePlaceholder", () => {
  it("uploadId 별 토큰은 서로 구별된다", () => {
    expect(buildPlaceholderToken("a")).not.toBe(buildPlaceholderToken("b"));
  });

  it("같은 uploadId 는 결정적으로 동일한 토큰을 낸다", () => {
    expect(buildPlaceholderToken("u1")).toBe(buildPlaceholderToken("u1"));
  });

  it("대상 uploadId 의 토큰만 치환하고 다른 uploadId 토큰은 침범하지 않는다", () => {
    const tokA = buildPlaceholderToken("A");
    const tokB = buildPlaceholderToken("B");
    const content = `intro ${tokA} middle ${tokB} end`;
    const out = replacePlaceholder(content, "A", "![a](/attachments/1)");
    expect(out).toBe(`intro ![a](/attachments/1) middle ${tokB} end`);
    expect(out).toContain(tokB);
    expect(out).not.toContain(tokA);
  });

  it("대상 토큰이 여러 번 등장하면 모두 치환한다", () => {
    const tokA = buildPlaceholderToken("A");
    const content = `${tokA} and again ${tokA}`;
    const out = replacePlaceholder(content, "A", "R");
    expect(out).toBe("R and again R");
  });

  it("정규식 메타문자를 포함한 uploadId 도 안전하게 치환한다(주입 방지)", () => {
    const weird = "a.*+?(b)[c]";
    const tok = buildPlaceholderToken(weird);
    const content = `x ${tok} y`;
    const out = replacePlaceholder(content, weird, "OK");
    expect(out).toBe("x OK y");
  });

  it("대상 토큰이 없으면 원본을 그대로 반환한다", () => {
    const content = "no tokens here";
    expect(replacePlaceholder(content, "missing", "R")).toBe(content);
  });
});

describe("buildErrorMarker", () => {
  it("깨진 이미지 markdown 이 아니다(안전한 오류 표시)", () => {
    const marker = buildErrorMarker("A");
    expect(marker).not.toMatch(/!\[[^\]]*\]\([^)]*\)/); // ![...](...) 이미지 아님
  });

  it("uploadId 에 대해 결정적이다", () => {
    expect(buildErrorMarker("A")).toBe(buildErrorMarker("A"));
  });

  it("uploading 토큰을 오류 표시로 치환하는 데 사용할 수 있다", () => {
    const tok = buildPlaceholderToken("A");
    const content = `x ${tok} y`;
    const out = replacePlaceholder(content, "A", buildErrorMarker("A"));
    expect(out).toContain(buildErrorMarker("A"));
    expect(out).not.toContain(tok);
  });
});

describe("resolveAttachmentReference", () => {
  it("`/attachments/{id}` → { attachmentId: number }", () => {
    expect(resolveAttachmentReference("/attachments/42")).toEqual({ attachmentId: 42 });
    expect(resolveAttachmentReference("/attachments/1")).toEqual({ attachmentId: 1 });
  });

  it("비대상 href 는 null", () => {
    expect(resolveAttachmentReference("/documents/1")).toBeNull();
    expect(resolveAttachmentReference("https://x/attachments/1")).toBeNull();
    expect(resolveAttachmentReference("/attachments/abc")).toBeNull();
    expect(resolveAttachmentReference("")).toBeNull();
    expect(resolveAttachmentReference("/attachments/")).toBeNull();
    expect(resolveAttachmentReference("/attachments/1/extra")).toBeNull();
    expect(resolveAttachmentReference("/attachments/42?x=1")).toBeNull();
  });

  it("0·음수·선행영은 대상 규약(양의 정수)이 아니므로 null", () => {
    expect(resolveAttachmentReference("/attachments/0")).toBeNull();
    expect(resolveAttachmentReference("/attachments/-1")).toBeNull();
    expect(resolveAttachmentReference("/attachments/042")).toBeNull();
  });
});
