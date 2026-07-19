/**
 * 첨부 콘텐츠 참조·업로드 자리표시자 토큰의 순수(부수효과 없음) 변환 함수 모음.
 *
 * `AttachmentRead.kind`로 콘텐츠 참조 형태를 결정하고(image→이미지 참조, file→다운로드 링크),
 * 업로드 진행 자리표시자 토큰을 `uploadId`로 생성/치환하며, 콘텐츠 내 `/attachments/{id}` 참조를
 * 파싱한다. `url`은 서버가 응답 시 산정하는 파생 참조값이므로 프론트에서 재구성하지 않고 응답값을
 * 그대로 사용한다(Req 7.2). 첨부 상태 판정·DOM·네트워크·난수/시간 등 부수효과가 없어 단위
 * 테스트만으로 계약을 고정한다(Requirements 1.3, 2.1, 2.2, 2.3, 3.5, 7.2).
 */
import type { AttachmentRead } from "../types";

/**
 * 업로드 진행 자리표시자 토큰의 센티넬 래퍼.
 *
 * 일반 markdown·다른 uploadId 토큰과 충돌하지 않도록 `⟦attachment-uploading:{uploadId}⟧`
 * 형태로 uploadId 를 감싼다. 치환은 이 문자열 리터럴에 대한 split/join 으로만 수행하여
 * (정규식 미사용) uploadId 에 정규식 메타문자가 섞여도 주입이 발생하지 않는다.
 */
const UPLOADING_PREFIX = "⟦attachment-uploading:";
const UPLOADING_SUFFIX = "⟧";

/** 실패 시 안전 오류 표시(깨진 이미지/링크가 아닌 센티넬) 래퍼. */
const ERROR_PREFIX = "⟦attachment-error:";
const ERROR_SUFFIX = "⟧";

/** `/attachments/{정수}` 정확 일치(질의·추가 경로 불허). id 는 캡처 후 양의 정수 검증. */
const ATTACHMENT_HREF_RE = /^\/attachments\/(\d+)$/;

/**
 * `AttachmentRead.kind`로 콘텐츠 참조 markdown 을 조립한다(Req 1.3, 7.2).
 *
 * image → `![name](url)`, file → `[name](url)`. `url`은 응답값을 그대로 사용하며
 * (`/attachments/${att.id}` 형태로 재구성하지 않는다) `name`은 `original_name`을 쓴다.
 */
export function buildReferenceMarkdown(att: AttachmentRead): string {
  const name = att.original_name;
  const url = att.url; // 서버 산정 파생값 그대로 사용(재구성 금지, Req 7.2).
  if (att.kind === "image") {
    return `![${name}](${url})`;
  }
  return `[${name}](${url})`;
}

/**
 * 업로드 진행 자리표시자 토큰을 `uploadId`로 결정적으로 생성한다(Req 2.1).
 *
 * 동시 다중 업로드가 서로 다른 uploadId 로 구별되도록 uploadId 를 센티넬로 감싼다.
 */
export function buildPlaceholderToken(uploadId: string): string {
  return `${UPLOADING_PREFIX}${uploadId}${UPLOADING_SUFFIX}`;
}

/**
 * 실패 시 사용할 안전한 오류 표시를 `uploadId`로 결정적으로 생성한다(Req 2.3).
 *
 * 깨진 이미지(`![...]()`)·깨진 링크가 아니라 렌더러가 안전하게 처리할 센티넬을 반환한다.
 */
export function buildErrorMarker(uploadId: string): string {
  return `${ERROR_PREFIX}${uploadId}${ERROR_SUFFIX}`;
}

/**
 * `uploadId`의 자리표시자 토큰을 `replacement`로 치환한다(Req 2.2, 2.3, 비침범).
 *
 * 정확히 그 uploadId 의 토큰 리터럴에 대해서만 split/join 치환하여 다른 uploadId 토큰을
 * 침범하지 않으며, 여러 번 등장하면 모두 치환한다. 정규식을 쓰지 않아 uploadId 에 정규식
 * 메타문자가 있어도 주입이 없다. 대상 토큰이 없으면 원본을 그대로 반환한다.
 */
export function replacePlaceholder(content: string, uploadId: string, replacement: string): string {
  const token = buildPlaceholderToken(uploadId);
  return content.split(token).join(replacement);
}

/**
 * 콘텐츠 내 첨부 참조 `href`를 `/attachments/{id}` 규약으로만 파싱한다(Req 3.5, 7.2).
 *
 * 정확히 `/attachments/{양의 정수}`(선행영·질의·추가 경로·절대 URL 불허)에만 일치하며
 * `{ attachmentId }`(number)를 반환하고, 비대상 href 는 `null`을 반환한다.
 */
export function resolveAttachmentReference(href: string): { attachmentId: number } | null {
  const match = ATTACHMENT_HREF_RE.exec(href);
  if (match === null) {
    return null;
  }
  const digits = match[1];
  const attachmentId = Number(digits);
  // 양의 정수 규약: 0·선행영("042")·비정상 파싱을 배제(캐노니컬 형태만 허용).
  if (!Number.isInteger(attachmentId) || attachmentId <= 0 || String(attachmentId) !== digits) {
    return null;
  }
  return { attachmentId };
}
