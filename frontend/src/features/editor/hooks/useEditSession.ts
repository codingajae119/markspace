/**
 * 편집 세션 생명주기 오케스트레이션 훅 (design.md "features/editor/hooks → useEditSession").
 *
 * 진입(마운트) → 잠금 획득(`lockDocument`) → `resolveLockState` 로 파생 → `self` 면
 * 초기 콘텐츠 로드(`getDocument`) 후 편집 활성(`EditorHandle` 바인딩) → 이탈(언마운트/
 * 라우트 전환) cleanup 에서 잠금 보유·미취소·미저장·핸들 바인딩 시에만 `saveDocument`
 * 를 **정확히 1회** 호출하는 생명주기를 오케스트레이션한다.
 *
 * 핵심 불변식(Req 3):
 * - 이탈 저장은 세션당 최대 1회다(중복 방지 `savedRef`). 취소(`released`)·미획득
 *   (`acquired=false`)·핸들 미바인딩이면 저장을 억제한다(Req 3.5·3.6).
 * - 주기 타이머·키입력 debounce 기반 저장을 두지 않는다(Req 3.2, 버전 폭증 회피).
 * - 저장 억제·1회 판정 플래그는 **ref** 로 보관한다 — cleanup 클로저는 최신 값을 읽어야
 *   하며 state 재렌더에 의존하면 오래된 값을 캡처할 수 있기 때문이다.
 *
 * 잠금·저장·취소 판정(멱등 재획득·타인 충돌·저장 원자성)은 백엔드 엔진 단독 소유이므로
 * 이 훅은 결과를 재판정 없이 상태로 표면화만 한다. cleanup 은 동기 실행이라 저장은
 * fire-and-forget 이며(await 불가), 재진입 방지를 위해 호출 **직전** `savedRef=true` 를
 * 세팅한다. 언마운트 후 상태 가시성은 제한적이다(design §Error Handling).
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6,
 *               4.1, 4.2, 4.3, 4.5.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { lockVersionApi } from "../api/lockVersionApi";
import { resolveLockState } from "../lib/resolveLockState";
import type {
  EditSessionStatus,
  EditableDocument,
  LockState,
} from "../types";
import { ApiError } from "@/shared/api/errors";
import type { EditorHandle } from "@/shared/editor/EditorWrapper";

/** 편집 세션 상태(design 계약). `document` 는 self 진입 시 초기 콘텐츠. */
export interface EditSessionState {
  status: EditSessionStatus;
  lockState: LockState;
  document: EditableDocument | null;
  error: ApiError | null;
}

/** {@link EditSessionState} 에 편집 활성/취소/재획득 조작을 더한 반환 계약. */
export type UseEditSession = EditSessionState & {
  /** EditorWrapper `onReady` 핸들 결선(이탈 저장의 `getMarkdown` 소스). */
  bindHandle(handle: EditorHandle): void;
  /** `POST /cancel` 후 `released` 설정(이탈 저장 억제) + 읽기 복귀 신호. */
  cancel(): Promise<void>;
  /** 강제 해제(204) 이후 억제/1회 플래그 리셋 후 잠금 재획득. */
  retryAcquire(): Promise<void>;
};

/** throw 된 원인을 `ApiError` 로 정규화(계약상 apiClient 는 ApiError 를 throw 한다). */
function toApiError(cause: unknown): ApiError {
  if (cause instanceof ApiError) {
    return cause;
  }
  return new ApiError({
    status: 0,
    code: "internal",
    message: "예기치 못한 오류가 발생했습니다.",
  });
}

export function useEditSession(documentId: number): UseEditSession {
  const [status, setStatus] = useState<EditSessionStatus>("idle");
  const [lockState, setLockState] = useState<LockState>({ kind: "acquiring" });
  const [documentState, setDocumentState] = useState<EditableDocument | null>(
    null,
  );
  const [error, setError] = useState<ApiError | null>(null);

  // cleanup 클로저가 최신 값을 읽도록 억제/1회 판정 상태는 ref 로 보관한다.
  const acquiredRef = useRef(false); // 잠금 보유 여부(self 진입 성공)
  const releasedRef = useRef(false); // 취소/저장으로 이미 해제됨(이탈 저장 억제)
  const savedRef = useRef(false); // 이탈 저장 1회 실행 가드
  const handleRef = useRef<EditorHandle | null>(null); // 이탈 저장의 getMarkdown 소스
  const mountedRef = useRef(true);

  const bindHandle = useCallback((handle: EditorHandle): void => {
    handleRef.current = handle;
  }, []);

  /**
   * 잠금 획득 → 파생 → self 면 초기 콘텐츠 로드 후 편집 활성. mount·retryAcquire 공용.
   * 언마운트 이후에는 상태 갱신을 억제한다(mountedRef 가드).
   */
  const acquire = useCallback(async (): Promise<void> => {
    setStatus("acquiring");
    setLockState({ kind: "acquiring" });
    setError(null);

    let resolved: LockState;
    try {
      const lock = await lockVersionApi.lockDocument(documentId);
      resolved = resolveLockState({ ok: lock });
    } catch (cause) {
      resolved = resolveLockState({ error: toApiError(cause) });
    }

    if (!mountedRef.current) {
      // 잠금은 서버에 설정됐을 수 있으나 세션이 이미 종료됐다 — 상태만 억제한다.
      if (resolved.kind === "self") {
        acquiredRef.current = true;
      }
      return;
    }

    setLockState(resolved);

    if (resolved.kind === "self") {
      // 잠금 보유 확정 — 이탈 저장 대상이 된다(핸들 바인딩 시에만 실제 저장).
      acquiredRef.current = true;
      try {
        const doc = await lockVersionApi.getDocument(documentId);
        if (!mountedRef.current) {
          return;
        }
        setDocumentState(doc);
        setStatus("editing");
      } catch (cause) {
        if (!mountedRef.current) {
          return;
        }
        setError(toApiError(cause));
        setStatus("error");
      }
      return;
    }

    if (resolved.kind === "other") {
      setStatus("blocked");
      return;
    }

    if (resolved.kind === "error") {
      setError(resolved.error);
      setStatus("error");
    }
    // "acquiring" 은 resolveLockState 가 산출하지 않는다(타입 완결용 no-op).
  }, [documentId]);

  useEffect(() => {
    mountedRef.current = true;
    acquiredRef.current = false;
    releasedRef.current = false;
    savedRef.current = false;

    void acquire();

    return () => {
      mountedRef.current = false;
      // 이탈 저장은 잠금 보유·미취소·미저장·핸들 바인딩일 때만 **정확히 1회**.
      const handle = handleRef.current;
      if (
        acquiredRef.current &&
        !releasedRef.current &&
        !savedRef.current &&
        handle !== null
      ) {
        // 재진입 방지를 위해 호출 직전에 1회 가드를 세운다(cleanup 은 await 불가).
        savedRef.current = true;
        releasedRef.current = true;
        const content = handle.getMarkdown();
        void lockVersionApi
          .saveDocument(documentId, { content })
          .catch((cause) => {
            // 언마운트 이후 가시성은 제한적(best-effort) — 마운트 중일 때만 표면화.
            if (mountedRef.current) {
              setError(toApiError(cause));
            }
          });
      }
    };
  }, [documentId, acquire]);

  const cancel = useCallback(async (): Promise<void> => {
    try {
      await lockVersionApi.cancelEdit(documentId);
      // 취소 성공 → 이후 이탈 저장 억제(Req 3.5). 잠금은 서버에서 해제됐다.
      releasedRef.current = true;
      if (mountedRef.current) {
        setStatus("released");
      }
    } catch (cause) {
      if (mountedRef.current) {
        setError(toApiError(cause));
      }
    }
  }, [documentId]);

  const retryAcquire = useCallback(async (): Promise<void> => {
    // 강제 해제 후 재획득 — 억제/1회 플래그를 리셋하고 잠금 획득 흐름을 재실행한다.
    releasedRef.current = false;
    savedRef.current = false;
    acquiredRef.current = false;
    await acquire();
  }, [acquire]);

  return {
    status,
    lockState,
    document: documentState,
    error,
    bindHandle,
    cancel,
    retryAcquire,
  };
}
