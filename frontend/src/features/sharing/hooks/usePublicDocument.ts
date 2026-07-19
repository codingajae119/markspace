/**
 * 공개(게스트) 렌더 로드 훅
 * (design.md "features/sharing → usePublicDocument").
 *
 * 공유 토큰으로 `publicApi.getPublicDocument(token)`(무가드 게스트 경로)를 호출해 공개 트리를
 * 로드하고, 트리의 모든 노드(root+하위 계층)의 `content_html` 안 링크 스코프 첨부 참조
 * (`/public/{token}/attachments/{id}`)를 `rewriteAttachmentRefs` 로 단일 설정 base URL 기준
 * 절대 경로로 재작성한 뒤 `ready` 로 표면화한다(Req 6.3·7.1).
 *
 * 존재 추정 차단(Req 5.4·6.5): 404 는 사유(무효 토큰·삭제 문서·보관·게이트 off)를 구분하지
 * 않고 모두 `unavailable` 하나로 통일한다. 리다이렉트하지 않고 에러 객체도 노출하지 않는다
 * (사유가 새면 존재 여부를 역추정할 수 있으므로 단일 표면으로 봉인). 트리가 없으면 그 하위
 * 첨부 참조도 렌더되지 않으므로 문서·첨부는 자연히 결합 차단된다(Req 7.4).
 *
 * 공개(무가드) 호출 규약(Req 6.2): 어댑터(`publicApi`)가 이미 `skipAuthRedirect: true` 로
 * 호출하므로 미인증이어도 전역 401 리다이렉트를 유발하지 않는다. 여기서 fetch·credentials·
 * 401 인터셉터를 재구현하지 않는다(s16 단일 소유). 404 외 오류(5xx·비404 ApiError)는
 * `error` 로 `ApiError` 를 그대로 보존한다.
 *
 * Requirements: 5.4·6.2·6.3·6.5·7.1·7.4.
 */

import { useEffect, useState } from "react";

import { publicApi } from "../api/publicApi";
import { rewriteAttachmentRefs } from "../lib/rewriteAttachmentRefs";
import type { PublicDocumentNode } from "../api/types";
import { apiConfig } from "@/config";
import { ApiError } from "@/shared/api/errors";

/** usePublicDocument 가 노출하는 판별 유니온 상태(design.md §usePublicDocument). */
export type PublicDocState =
  | { status: "loading" }
  | { status: "ready"; root: PublicDocumentNode } // content_html 이 절대 경로로 재작성됨
  | { status: "unavailable" } // 404 통일(사유 미노출 — 존재 추정 차단)
  | { status: "error"; error: ApiError };

/**
 * 한 노드와 그 하위 전체의 `content_html` 을 절대 경로로 재작성한 새 트리를 만든다(재귀·불변).
 *
 * 응답 객체를 제자리 변형하지 않고 매 노드를 얕게 복제하면서 `content_html` 만 재작성하고
 * `children` 도 재귀로 새 배열을 구성한다(원본 응답 불변 유지).
 */
function rewriteNode(node: PublicDocumentNode, token: string): PublicDocumentNode {
  return {
    ...node,
    content_html: rewriteAttachmentRefs(
      node.content_html,
      token,
      apiConfig.baseUrl,
    ),
    children: node.children.map((child) => rewriteNode(child, token)),
  };
}

/**
 * 공유 토큰으로 공개 문서 트리를 로드하는 훅.
 *
 * `token` 변경 시 `loading` 으로 재시작하며, 응답 도착 시 최신 요청인지 확인해 이전 토큰의
 * 뒤늦은 응답(stale)이나 언마운트 후 setState 를 무시한다(경합·누수 방지).
 */
export function usePublicDocument(token: string): PublicDocState {
  const [state, setState] = useState<PublicDocState>({ status: "loading" });

  useEffect(() => {
    // 이 이펙트 실행에 귀속된 요청만 유효로 취급(토큰 변경·언마운트 시 이전 요청 무시).
    let active = true;
    setState({ status: "loading" });

    publicApi
      .getPublicDocument(token)
      .then((doc) => {
        if (!active) {
          return;
        }
        setState({ status: "ready", root: rewriteNode(doc.root, token) });
      })
      .catch((caught: unknown) => {
        if (!active) {
          return;
        }
        // 404 는 사유 불문 unavailable 로 통일(존재 추정 차단). 그 외는 ApiError 표면화.
        if (caught instanceof ApiError && caught.status === 404) {
          setState({ status: "unavailable" });
          return;
        }
        setState({ status: "error", error: normalizeError(caught) });
      });

    return () => {
      active = false;
    };
  }, [token]);

  return state;
}

/**
 * 던져진 값을 `ApiError` 로 정규화한다. 어댑터(apiClient)는 이미 `ApiError` 를 던지므로 통상
 * 그대로 통과하지만, 방어적으로 비-`ApiError` throw 도 안정적 internal 로 감싼다.
 */
function normalizeError(caught: unknown): ApiError {
  if (caught instanceof ApiError) {
    return caught;
  }
  return new ApiError({
    status: 0,
    code: "internal",
    message: "예기치 못한 오류가 발생했습니다.",
  });
}
