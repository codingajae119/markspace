/**
 * 인증·WS 격리 경유 첨부 이미지 렌더 컴포넌트
 * (design.md "features/attachment — AttachmentImage" ~499-501·518, Requirements 3.1·3.3·5.1·5.2·5.5).
 *
 * `useAttachmentResource(id, { kind: "image" })` 가 관측한 서빙 리소스 상태만 보고 렌더한다.
 * - `loading`: 공용 {@link Spinner}(role=status)로 로딩 상태를 노출한다(Req 3.3).
 * - `ready`: 훅이 생성한 blob 오브젝트 URL 을 `<img src>` 로 렌더한다. 이 오브젝트 URL 이
 *   인증·WS 격리·404 감지를 거친 유일한 허용 경로이며, `/attachments/{id}` 원시 `src` 를
 *   직접 만들지 않는다(Req 3.1·3.2).
 * - `unavailable`(404/403): 깨진 이미지가 아니라 안전 {@link AttachmentPlaceholder}(`unavailable`)로
 *   폴백한다. admin 이 보관(아카이브) 첨부를 열람해도 백엔드가 role 무관 404 로 차단하므로 동일하게
 *   placeholder 로 표현된다(Req 5.1·5.2·5.5).
 * - `error`: 일시 오류(5xx·네트워크)는 `error` 변형 placeholder 로 표현해 서빙 불가(placeholder)와
 *   구분한다(Req 5.4 관측 근거).
 *
 * 이 컴포넌트는 첨부의 보관·소멸 여부를 프론트에서 재판정하지 않고 훅이 관측한 HTTP 결과 상태만
 * 반영한다(Req 5.3). admin 특수 분기를 두지 않는다.
 */

import type { ReactElement } from "react";

import { Spinner } from "@/shared/ui";

import { useAttachmentResource } from "../hooks/useAttachmentResource";
import { AttachmentPlaceholder } from "./AttachmentPlaceholder";

export interface AttachmentImageProps {
  /** 렌더할 첨부 식별자(문서 본문 참조 `/attachments/{id}` 에서 파싱된 값). */
  attachmentId: number;
  /** 접근성 대체 텍스트(미지정 시 빈 문자열 — 장식 이미지로 취급). */
  alt?: string;
}

/** 인증 blob 오브젝트 URL 기반 첨부 이미지. 원시 `src` 를 만들지 않는다. */
export function AttachmentImage({
  attachmentId,
  alt,
}: AttachmentImageProps): ReactElement {
  const state = useAttachmentResource(attachmentId, { kind: "image" });

  if (state.status === "loading") {
    return <Spinner />;
  }

  if (state.status === "ready") {
    // state.objectUrl(blob:) 은 인증·WS 격리를 거친 유일한 허용 경로다(원시 src 금지, Req 3.2).
    return <img src={state.objectUrl} alt={alt ?? ""} />;
  }

  if (state.status === "unavailable") {
    return <AttachmentPlaceholder variant="unavailable" />;
  }

  return <AttachmentPlaceholder variant="error" />;
}
