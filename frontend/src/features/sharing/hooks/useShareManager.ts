/**
 * 공유 관리(발급·토글) 오케스트레이션 훅
 * (design.md "features/sharing → useShareManager").
 *
 * 관리자 UI 가 소비하는 단일 상태 표면으로, `shareApi`(조회·발급·토글) 응답으로 링크 상태를
 * 채운다. 마운트/documentId 변경 시 초기 조회(`getLink`)로 문서의 현재 공유 상태를 시드하며
 * (이전 S1 seam 종료 — 이제 사전 링크를 조회할 GET 이 존재한다), 조회 in-flight 동안은
 * `loading` 을 노출해 컨트롤이 확정 라벨 대신 잠정 상태를 표기하도록 한다(Req 2.2). 연속 문서
 * 전환은 `runIdRef` latest-wins 가드로 가장 최근 선택 문서의 결과만 반영한다(Req 2.4). 초기
 * 조회 실패는 `error` 로 표면화하되 링크 상태를 침범하지 않는다(불확실한 상태를 공유 중으로
 * 단정하지 않는다 — Req 2.3).
 *
 * INV-8 격리: 초기 조회 시드는 `link`/`linkRef` 만 채우고 `reissued` 를 절대 set 하지 않는다.
 * `reissued` 는 오직 "이미 링크가 있던 상태의 `issue()`" 에서만 true 이며, 시드는 그 사전 링크
 * 판정의 입력(`linkRef`)만 정직하게 채운다(시드된 링크 위 재발급은 올바르게 `reissued=true`).
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
 * Requirements: 1.3·1.4·2.1·2.2·2.3·2.4·3.1·3.2·3.3·5.1·5.2·5.3·6.1.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  /** 마운트 시 초기 공유 상태 조회가 진행 중이면 true(잠정 표기용, Req 2.2). */
  loading: boolean;
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
  // 초기 조회는 마운트 직후 즉시 시작되므로 loading 은 true 로 출발한다 — freshly-mounted
  // 컨트롤이 첫 조회 해상 전까지 잠정(로딩) 상태를 표기하도록(Req 2.2, false 플래시 방지).
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  // 재발급 판정(INV-8)은 "이 issue 호출 이전에 링크가 있었는가"에 달려 있다. state 는
  // 비동기 갱신이라 in-flight 중 최신 값을 동기적으로 읽기 위해 ref 로 함께 추적한다.
  // 초기 조회 시드도 이 ref 를 채우므로 시드된 링크 위 발급이 정직하게 reissued=true 가 된다.
  const linkRef = useRef<ShareLinkRead | null>(null);

  // latest-wins(Req 2.4): documentId 변경·권위적 쓰기마다 runId 를 증가시켜, 늦게 도착한
  // 이전(stale) 초기 조회 응답이 최신 상태를 덮어쓰지 못하게 한다(DocumentViewer idiom).
  // mountedRef: 언마운트 후 setState 방지.
  const runIdRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // 마운트/documentId 변경 시 초기 조회로 현재 공유 상태를 시드한다(S1 seam 종료).
  // 성공 → link/linkRef 시드(단 reissued 는 절대 건드리지 않음 — INV-8 격리). 실패 → error
  // 표면화 + link 불침범(불확실 상태를 공유 중으로 단정 금지, Req 2.3). runId 불일치·언마운트
  // 시에는 결과를 무시한다(latest-wins·Req 2.4).
  useEffect(() => {
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const fetched = await shareApi.getLink(documentId);
        if (!mountedRef.current || runIdRef.current !== runId) {
          return;
        }
        linkRef.current = fetched;
        setLink(fetched);
        setLoading(false);
      } catch (caught) {
        if (!mountedRef.current || runIdRef.current !== runId) {
          return;
        }
        // 조회 실패는 링크 상태를 침범하지 않는다 — link/linkRef 불변 유지(Req 2.3).
        setError(normalizeError(caught));
        setLoading(false);
      }
    })();
  }, [documentId]);

  const issue = useCallback(async (): Promise<ShareLinkRead | null> => {
    // 발급 이전에 링크가 존재했으면 이번 발급은 재발급(새 토큰·이전 링크 사망).
    const hadLink = linkRef.current !== null;
    // 발급은 권위적 쓰기 — in-flight 초기 조회(latest-wins)를 무효화하고 잠정(loading) 단계를
    // 종료한다(늦게 온 stale 시드가 mutation 결과를 덮어쓰지 않도록).
    runIdRef.current += 1;
    setLoading(false);
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
      // 토글도 권위적 쓰기 — in-flight 초기 조회를 무효화하고 잠정 단계를 종료한다.
      runIdRef.current += 1;
      setLoading(false);
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
    loading,
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
