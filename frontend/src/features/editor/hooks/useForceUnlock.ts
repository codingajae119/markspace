/**
 * 강제 해제(owner/admin) 조작 훅 (design.md "features/editor/hooks → useForceUnlock").
 *
 * 두 가지만 소유한다:
 * - `canForceUnlock` 노출 판정: **오직** s16 `hasWorkspaceRole`
 *   ({minimum: Role.OWNER}, admin bypass 포함) 단일 경로로 파생한다. 컴포넌트/훅에서 role
 *   을 직접 비교하지 않는다(INV-1·3, Req 5.1). admin bypass 는 `hasWorkspaceRole` 내부에
 *   있다.
 * - `forceUnlock()`: `lockVersionApi.forceUnlock(id)`(204) 호출. 성공 시 `true` 를 반환해
 *   호출자(EditLockBanner/DocumentEditPage)가 `useEditSession.retryAcquire` 로 재획득을
 *   유도하게 하고(Req 5.2), 실패(403/404 `ApiError`) 시 `state.error` 로 표면화하고 `false`
 *   를 반환한다(Req 5.4). `pending` 은 호출 전후로 토글하며 항상 정리한다.
 *
 * **시그니처 결정(design §useForceUnlock + Req 5.1)**: design 의 한 줄 계약 스케치는
 * `(documentId)` 만 보이지만, `hasWorkspaceRole` 은 세션/멤버십을 스스로 조회하지 않고
 * `currentRole`·`isAdmin` 을 **주입받는** 순수 함수다. 그 값의 단일 소유자는 호출자
 * (`useEditorScope` → EditLockBanner/DocumentEditPage)이므로 여기서 파라미터로 받는다
 * (`useForceUnlock(documentId, currentRole, isAdmin)`). 이렇게 하면 role 해석이 s16 게이팅
 * 단일 경로에 남고, 훅이 컨텍스트로 손을 뻗지 않는다.
 *
 * **보안 경계 아님(Req 5.5)**: 클라이언트 게이팅(`canForceUnlock`)은 UI 노출 편의일 뿐이며,
 * 서버측 OWNER 강제(백엔드 403)가 최종 권한 경계다. 게이팅을 우회해도 실제 해제는 백엔드가
 * 다시 판정한다.
 *
 * Requirements: 5.1, 5.2, 5.4, 5.5.
 */
import { useCallback, useMemo, useState } from "react";

import { lockVersionApi } from "../api/lockVersionApi";
import { ApiError } from "@/shared/api/errors";
import { hasWorkspaceRole } from "@/shared/auth/permissions";
import { Role } from "@/shared/auth/roles";

/** 강제 해제 조작의 진행/오류 상태. */
export interface ForceUnlockState {
  pending: boolean;
  error: ApiError | null;
}

/** {@link useForceUnlock} 반환 계약(design §useForceUnlock). */
export interface UseForceUnlock {
  /** `hasWorkspaceRole(OWNER)`(admin bypass 포함)로만 파생한 노출 판정. */
  canForceUnlock: boolean;
  /** `POST /force-unlock`(204) → `true`; 실패 → `false` + `state.error`. */
  forceUnlock(): Promise<boolean>;
  state: ForceUnlockState;
}

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

export function useForceUnlock(
  documentId: number,
  currentRole: Role | null,
  isAdmin: boolean,
): UseForceUnlock {
  const [state, setState] = useState<ForceUnlockState>({
    pending: false,
    error: null,
  });

  // 노출 판정은 오직 s16 게이팅 유틸 단일 경로로 파생한다(role 직접 비교 금지, Req 5.1).
  const canForceUnlock = useMemo(
    () => hasWorkspaceRole({ currentRole, isAdmin, minimum: Role.OWNER }),
    [currentRole, isAdmin],
  );

  const forceUnlock = useCallback(async (): Promise<boolean> => {
    setState({ pending: true, error: null });
    try {
      await lockVersionApi.forceUnlock(documentId);
      // 204 성공 — 호출자가 useEditSession.retryAcquire 로 재획득을 유도한다(Req 5.2).
      setState({ pending: false, error: null });
      return true;
    } catch (cause) {
      // 403/404 등 실패 — ApiError 를 표면화하고 false 로 알린다(Req 5.4). 서버 403 이
      // 최종 권한 경계다(Req 5.5).
      setState({ pending: false, error: toApiError(cause) });
      return false;
    }
  }, [documentId]);

  return { canForceUnlock, forceUnlock, state };
}
