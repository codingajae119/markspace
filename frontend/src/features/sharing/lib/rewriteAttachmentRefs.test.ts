import { describe, it, expect } from "vitest";

import { rewriteAttachmentRefs } from "./rewriteAttachmentRefs";

/**
 * rewriteAttachmentRefs 는 공개 렌더 HTML 안의 링크 스코프 첨부 참조
 * (`/public/{token}/attachments/{id}`)의 origin 만 절대화하는 순수 문자열 변환이다.
 * 숫자 id 경계 보존(`5`가 `50` 안으로 오염되지 않음)·토큰 특정성·중복 접두 방지를
 * 단위 테스트로 고정한다(Requirements 7.1, 7.5).
 */
const BASE = "https://api.example.com";

describe("rewriteAttachmentRefs", () => {
  it("root-relative 이미지 참조 앞에 baseUrl origin 을 절대 접두한다(Req 7.1)", () => {
    const html = `<img src="/public/tok/attachments/5">`;
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(
      `<img src="https://api.example.com/public/tok/attachments/5">`,
    );
  });

  it("동일 토큰의 id 5 와 50 이 서로 오염되지 않고 각자 정확히 접두된다(id 경계, Req 7.5)", () => {
    const html = `<img src="/public/tok/attachments/5"><img src="/public/tok/attachments/50">`;
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(
      `<img src="https://api.example.com/public/tok/attachments/5">` +
        `<img src="https://api.example.com/public/tok/attachments/50">`,
    );
  });

  it("id 5 는 50 안에서 부분 일치하지 않는다(순서 무관, 50 먼저 등장해도)", () => {
    const html = `<a href="/public/tok/attachments/50"></a><a href="/public/tok/attachments/5"></a>`;
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(
      `<a href="https://api.example.com/public/tok/attachments/50"></a>` +
        `<a href="https://api.example.com/public/tok/attachments/5"></a>`,
    );
  });

  it("baseUrl 의 후행 슬래시를 제거해 `//public` 을 내지 않는다", () => {
    const html = `<img src="/public/tok/attachments/7">`;
    expect(rewriteAttachmentRefs(html, "tok", "https://api.example.com/")).toBe(
      `<img src="https://api.example.com/public/tok/attachments/7">`,
    );
  });

  it("`/public/{token}/` 스코프가 아닌 bare `/attachments/50`(s21 인증 경로)은 건드리지 않는다(Req 7.5)", () => {
    const html = `<img src="/attachments/50">`;
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(html);
  });

  it("다른 토큰의 참조는 재작성하지 않고 자기 토큰만 재작성한다(토큰 특정성)", () => {
    const html = `<img src="/public/tok/attachments/5"><img src="/public/other/attachments/9">`;
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(
      `<img src="https://api.example.com/public/tok/attachments/5">` +
        `<img src="/public/other/attachments/9">`,
    );
  });

  it("이미 절대화된 참조는 다시 접두하지 않는다(멱등·이중 접두 방지)", () => {
    const html = `<img src="https://api.example.com/public/tok/attachments/5">`;
    // root-relative 만 대상이므로 이미 origin 이 붙은 참조는 그대로 유지된다.
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(html);
    // 재실행해도 결과가 변하지 않는다(멱등).
    const once = rewriteAttachmentRefs(`<img src="/public/tok/attachments/5">`, "tok", BASE);
    expect(rewriteAttachmentRefs(once, "tok", BASE)).toBe(once);
  });

  it("첨부 참조가 없는 HTML 은 원본을 그대로 반환한다", () => {
    const html = `<p>hello <strong>world</strong></p>`;
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(html);
  });

  it("작은따옴표 속성값도 재작성한다", () => {
    const html = `<a href='/public/tok/attachments/3'>x</a>`;
    expect(rewriteAttachmentRefs(html, "tok", BASE)).toBe(
      `<a href='https://api.example.com/public/tok/attachments/3'>x</a>`,
    );
  });

  it("정규식 메타문자를 포함한 토큰도 자기 리터럴만 안전하게 일치시킨다(주입 방지)", () => {
    const weird = "a.+b";
    const html = `<img src="/public/a.+b/attachments/5"><img src="/public/aXXb/attachments/5">`;
    expect(rewriteAttachmentRefs(html, weird, BASE)).toBe(
      `<img src="https://api.example.com/public/a.+b/attachments/5">` +
        `<img src="/public/aXXb/attachments/5">`,
    );
  });
});
