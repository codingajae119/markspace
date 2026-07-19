/**
 * 공개 렌더 HTML 의 링크 스코프 첨부 참조 절대 경로 재작성 순수(부수효과 없음) 함수.
 *
 * 백엔드는 게스트 뷰 `content_html` 안의 첨부 참조를 이미 링크 스코프 형태
 * (`/public/{token}/attachments/{id}`, root-relative)로 재작성해 내려준다. 이 함수는 그
 * 참조의 origin 만 단일 설정의 API base URL 로 절대화하여 게스트 브라우저가 무인증 공개
 * 서빙 엔드포인트에서 이미지·파일을 로드할 수 있게 한다. 참조 범위·격리·보관 판정은
 * 재구현하지 않으며(백엔드 소유) 오직 경로 접두만 수행한다(Requirements 7.1, 7.5).
 *
 * 정규식 사용 시 두 가지를 방어한다.
 * 1) 숫자 id 경계 보존: `(\d+)` 는 연속 숫자 전체를 탐욕적으로 소비하므로
 *    `/attachments/5"` 와 `/attachments/50"` 가 서로 부분 일치·오염되지 않는다(id `5` 가
 *    `50` 안으로 침범하지 않음).
 * 2) 토큰 주입 방지: 인자 `token` 을 정규식 리터럴로 이스케이프하여, 토큰에 정규식
 *    메타문자가 섞여도 다른 토큰의 참조를 잘못 일치시키지 않는다.
 *
 * 또한 참조 바로 앞의 속성값 경계 문자(`"` `'` `(`)를 함께 일치시켜, root-relative 참조만
 * 대상으로 삼는다. 이미 origin 이 붙은 절대 참조(예: `https://host/public/...`)는 `/public`
 * 앞이 호스트 문자라 일치하지 않으므로 이중 접두가 발생하지 않는다(멱등).
 */

/** 정규식 메타문자를 리터럴로 이스케이프한다(토큰 주입 방지). */
function escapeRegExp(literal: string): string {
  return literal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 후행 슬래시를 1개 제거해 `//public` 이중 슬래시 산출을 막는다. */
function stripTrailingSlash(baseUrl: string): string {
  return baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
}

/**
 * 공개 렌더 HTML 의 `/public/{token}/attachments/{id}` 참조를
 * `${baseUrl}/public/{token}/attachments/{id}` 절대 경로로 재작성한다(Req 7.1, 7.5).
 *
 * - `token` 은 해당 문서 링크의 특정 토큰이며 그 토큰의 참조만 재작성한다(토큰 특정성).
 * - 숫자 id 경계를 보존해 `5`/`50` 이 상호 오염되지 않는다.
 * - root-relative 참조만 대상이므로 이미 절대화된 참조·다른 토큰·bare `/attachments/{id}`
 *   (s21 인증 경로)는 그대로 둔다.
 */
export function rewriteAttachmentRefs(html: string, token: string, baseUrl: string): string {
  const base = stripTrailingSlash(baseUrl);
  const escapedToken = escapeRegExp(token);
  // 선행 경계(`"` `'` `(`) + root-relative 링크 스코프 참조 + 탐욕적 숫자 id.
  const pattern = new RegExp(`(["'(])/public/${escapedToken}/attachments/(\\d+)`, "g");
  // 함수 치환기로 replacement 내 `$` 특수 해석을 피하고 경계 문자·id 를 그대로 재조립한다.
  return html.replace(
    pattern,
    (_full, delimiter: string, digits: string) =>
      `${delimiter}${base}/public/${token}/attachments/${digits}`,
  );
}
