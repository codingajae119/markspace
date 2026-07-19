/**
 * 첨부 서빙(blob) 취득 → 오브젝트 URL·상태 관리·해제 훅
 * (design.md "features/attachment — hooks → useAttachmentResource").
 *
 * `attachmentApi.fetchAttachmentBlob(id)` 로 인증·WS 격리 경유 바이너리를 받아
 * `URL.createObjectURL` 로 오브젝트 URL 을 생성하고 상태를 `loading→ready` 로 전이한다.
 * 언마운트·id 변경 시 생성했던 오브젝트 URL 을 `revokeObjectURL` 로 해제해 누수를 막는다.
 * 오브젝트 URL 의 생성/해제는 이 훅 단일 지점에서만 일어난다(Req 3.4·design invariant).
 *
 * 상태 매핑은 서빙 응답의 HTTP status 만 관측한다. 첨부의 보관·소멸 여부를 프론트에서
 * 재판정하지 않는다(Req 5.3):
 * - 404 → `unavailable`(not_found): 참조 소멸·보관 이동 등(안전 placeholder 근거).
 * - 403 → `unavailable`(forbidden): 권한 미달·차단(안전 placeholder 근거).
 * - 그 외(5xx·네트워크·401 포함) → `error`: 일시 오류(재시도 여지), 정규화 `ApiError` 보존.
 * 401 은 `apiClient` 전역 401 인터셉터가 리다이렉트를 이미 처리하므로 여기서 특수 처리하지
 * 않고 `error` 로 떨어진다(Req 6.3).
 *
 * Requirements: 3.1·3.2·3.3·3.4·4.1·4.4·5.1·5.2·5.4·6.2·6.3·6.4
 */

import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/shared/api/errors";
import { attachmentApi } from "../api/attachmentApi";
import type { AttachmentKind, AttachmentResourceState } from "../types";

/** meta 부재 시 `ready` 필수 필드 기본값(판별 유니온 계약 충족). */
const DEFAULT_KIND: AttachmentKind = "file";
const DEFAULT_FILE_NAME = "";

/**
 * 첨부 서빙 리소스 로딩 훅.
 *
 * `attachmentId` 만 재요청 트리거이며, `meta`(kind·fileName)는 표시 정보라 재요청을
 * 유발하지 않는다(객체 아이덴티티 churn 방지). 최신 meta 는 ref 로 캡처해 성공 시 읽는다.
 */
export function useAttachmentResource(
  attachmentId: number,
  meta?: { kind?: AttachmentKind; fileName?: string },
): AttachmentResourceState {
  const [state, setState] = useState<AttachmentResourceState>({
    status: "loading",
  });

  // meta 는 재요청 dep 에서 제외하되 성공 시 최신값을 읽기 위해 ref 로 보관한다.
  const metaRef = useRef(meta);
  metaRef.current = meta;

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;

    setState({ status: "loading" });

    attachmentApi
      .fetchAttachmentBlob(attachmentId)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        // 언마운트·id 변경으로 이미 취소되었으면 즉시 해제하고 상태를 갱신하지 않는다.
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        createdUrl = url;
        setState({
          status: "ready",
          objectUrl: url,
          kind: metaRef.current?.kind ?? DEFAULT_KIND,
          fileName: metaRef.current?.fileName ?? DEFAULT_FILE_NAME,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        if (err instanceof ApiError) {
          if (err.status === 404) {
            setState({ status: "unavailable", reason: "not_found" });
            return;
          }
          if (err.status === 403) {
            setState({ status: "unavailable", reason: "forbidden" });
            return;
          }
          setState({ status: "error", error: err });
          return;
        }
        // apiClient 는 항상 ApiError 를 throw 하지만 방어적으로 정규화한다.
        setState({
          status: "error",
          error: new ApiError({
            status: 0,
            code: "internal",
            message: "예기치 못한 오류가 발생했습니다.",
          }),
        });
      });

    return () => {
      cancelled = true;
      if (createdUrl !== null) {
        URL.revokeObjectURL(createdUrl);
      }
    };
  }, [attachmentId]);

  return state;
}
