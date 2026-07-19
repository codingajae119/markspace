/**
 * 공유 관리(발급·토글) 오케스트레이션 훅
 * (design.md "features/sharing → useShareManager").
 *
 * 관리자 UI 가 소비하는 단일 상태 표면으로, `shareApi`(발급·토글) 응답만으로 링크 상태를
 * 채운다. 백엔드에는 문서의 기존 링크를 조회하는 GET 엔드포인트가 없으므로(S1 seam),
 * `link` 는 항상 null 로 시작하며 오직 mutation 응답으로만 채워진다(사전 링크 상태를
 * 가정·발명하지 않는다).
 *
 * INV-8(재발급 통일): 발급(`issue`)은 상태 무관하게 항상 새 토큰을 발급하므로, 이미 링크가
 * 존재하던 상태에서의 재발급은 `reissued=true` 로 표면화한다(이전에 배포된 링크는 사망 —
 * Req 2.3). 토글(`toggle`)은 토큰을 유지하는 유일한 상태 기반 예외이므로 `reissued` 를
 * 건드리지 않는다(Req 3.1).
 *
 * 관측 기반 무효화(Req 5.1·5.2): `invalidated` 는 훅이 스스로 판단·회수하는 값이 아니라
 * 관측 신호(`documentStatus`·`isShareable`)에서 순수 파생하는 값이다. 실제 링크 무효화·회수는
 * 백엔드가 소유하며, 이 훅은 그 신호를 UI 로 표면화만 한다.
 *
 * 교차 관심사(fetch·base URL·credentials·`ApiError` 정규화·전역 401)는 s16 `apiClient` 가
 * 단일 소유하므로 여기서 재구현하지 않는다. 실패 시 `shareApi` 가 전파한 `ApiError` 를
 * 그대로 `error` 로 표면화하고 링크 상태는 침범하지 않는다(Req 2.4·3.2·3.3).
 *
 * Requirements: 1.3·1.4·2.1·2.3·2.4·3.1·3.2·3.3·5.1·5.2·5.3.
 */

import { useCallback, useMemo, useRef, useState } from "react";

import { shareApi } from "../api/shareApi";
import { buildShareUrl } from "../lib/buildShareUrl";
import type { ShareLinkRead } from "../api/types";
import { useCurrentWorkspace } from "@/app/workspace-context/useCurrentWorkspace";
import { ApiError } from "@/shared/api/errors";

/** useShareManager 가 노출하는 읽기 상태(design.md §useShareManager). */
export interface ShareManagerState {
  /** 세션 확인된 링크(S1: 사전 링크 열거 불가 → 초기 null). */
  link: ShareLinkRead | null;
  /** 링크가 있으면 `buildShareUrl(link.token)`, 없으면 null(게스트 프론트 링크). */
  frontShareUrl: string | null;
  /** 직전 연산이 재발급(이미 링크가 있던 상태의 issue)이었으면 true — INV-8. */
  reissued: boolean;
  /** 관측 신호 파생: `documentStatus !== "active" || !isShareable`. */
  invalidated: boolean;
  /** 발급/토글이 진행 중이면 true. */
  pending: boolean;
  /** 직전 연산의 `ApiError`(성공 시 null). */
  error: ApiError | null;
}

/** useShareManager 입력 — 대상 문서 식별자와 관측된 문서 상태(s19). */
export interface UseShareManagerInput {
  documentId: number;
  /** s19 관측 신호(active-ness). */
  documentStatus: string;
}

/** 읽기 상태 + 발급/토글 액션. */
export type UseShareManagerResult = ShareManagerState & {
  issue(): Promise<ShareLinkRead | null>;
  toggle(enabled: boolean): Promise<ShareLinkRead | null>;
};

export function useShareManager(
  input: UseShareManagerInput,
): UseShareManagerResult {
  const { documentId, documentStatus } = input;
  const { isShareable } = useCurrentWorkspace();

  const [link, setLink] = useState<ShareLinkRead | null>(null);
  const [reissued, setReissued] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  // 재발급 판정(INV-8)은 "이 issue 호출 이전에 링크가 있었는가"에 달려 있다. state 는
  // 비동기 갱신이라 in-flight 중 최신 값을 동기적으로 읽기 위해 ref 로 함께 추적한다.
  const linkRef = useRef<ShareLinkRead | null>(null);

  const issue = useCallback(async (): Promise<ShareLinkRead | null> => {
    // 발급 이전에 링크가 존재했으면 이번 발급은 재발급(새 토큰·이전 링크 사망).
    const hadLink = linkRef.current !== null;
    setPending(true);
    try {
      const issued = await shareApi.issueLink(documentId);
      linkRef.current = issued;
      setLink(issued);
      setReissued(hadLink);
      setError(null);
      return issued;
    } catch (caught) {
      // shareApi 가 정규화해 던진 ApiError 를 그대로 표면화한다. link 는 침범하지 않는다.
      setError(normalizeError(caught));
      return null;
    } finally {
      setPending(false);
    }
  }, [documentId]);

  const toggle = useCallback(
    async (enabled: boolean): Promise<ShareLinkRead | null> => {
      setPending(true);
      try {
        const updated = await shareApi.toggleLink(documentId, {
          is_enabled: enabled,
        });
        // 토글은 토큰을 유지하는 상태 전환 — reissued 는 건드리지 않는다(INV-8 예외).
        linkRef.current = updated;
        setLink(updated);
        setError(null);
        return updated;
      } catch (caught) {
        setError(normalizeError(caught));
        return null;
      } finally {
        setPending(false);
      }
    },
    [documentId],
  );

  // 링크가 있을 때만 게스트 프론트 링크를 파생한다(토큰 변화 시 재계산).
  const frontShareUrl = useMemo(
    () => (link ? buildShareUrl(link.token) : null),
    [link],
  );

  // 관측 신호 파생 — 훅은 판단하지 않고 신호만 표면화한다(백엔드가 무효화 소유).
  const invalidated = documentStatus !== "active" || !isShareable;

  return {
    link,
    frontShareUrl,
    reissued,
    invalidated,
    pending,
    error,
    issue,
    toggle,
  };
}

/**
 * 던져진 값을 `ApiError` 로 정규화한다. `shareApi`(apiClient)는 이미 `ApiError` 를 던지므로
 * 통상 그대로 통과하지만, 방어적으로 비-`ApiError` throw 도 안정적 internal 로 감싼다.
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
