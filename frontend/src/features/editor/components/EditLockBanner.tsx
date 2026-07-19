/**
 * 편집 잠금 상태 배너 (design.md "features/editor → 화면 컴포넌트 → EditLockBanner").
 *
 * `LockState` 를 표시만 한다(재판정 없음):
 * - `self`(Req 2.1): "내가 편집 중" + 획득 시각(`lock_acquired_at`) 표시. 여기에는 강제 해제
 *   조작이 없다 — 자기 잠금 해제는 EditorPane 의 cancel 경로(`/cancel`)가 소유한다(Req 5.3).
 * - `other`(Req 2.2·2.3): "다른 사용자가 편집 중" 안내 + 백엔드 `ApiError` 를 그대로 표면화한다
 *   (계약에 없는 보유자 식별 정보를 발명하지 않는다). owner/admin 에게만 강제 해제 조작을
 *   노출한다(아래).
 * - `error`(Req 2.x): 획득 실패(403/404 등) `ApiError` 를 `ErrorMessage` 로 표시한다.
 *
 * **강제 해제 노출 게이팅(Req 5.1·5.5)**: 노출 판정은 오직 s16 게이팅 경로로 수행하며 컴포넌트에서
 * role 을 직접 비교하지 않는다. 조작을 `<RequireRole minimum={Role.OWNER} currentRole={...}>` 로
 * 감싸 viewer/editor 에게는 숨기고(admin bypass 는 RequireRole 내부 `useSession` 이 처리),
 * 실제 호출은 `useForceUnlock(documentId, currentRole, isAdmin)` 으로 수행한다. 성공(`true`)
 * 시 `onRetry()`(재획득 유도, Req 5.2)를 호출하고, 실패(403/404)는 `useForceUnlock` 의
 * `state.error` 를 `ErrorMessage` 로 표면화한다(Req 5.4).
 *
 * **보안 경계 아님(Req 5.5)**: 클라이언트 게이팅은 UI 노출 편의일 뿐이며, 서버측 OWNER 강제
 * (백엔드 403)가 최종 권한 경계다. 게이팅을 우회해도 실제 해제는 백엔드가 다시 판정한다.
 *
 * Requirements: 2.1, 2.2, 2.3, 5.1, 5.3, 5.4, 5.5.
 */

import type { ReactElement } from "react";
import { useCallback } from "react";

import { RequireRole } from "@/shared/auth/RequireRole";
import { Role } from "@/shared/auth/roles";
import { ErrorMessage, Button } from "@/shared/ui";
import { useForceUnlock } from "../hooks/useForceUnlock";
import type { LockState } from "../types";

export interface EditLockBannerProps {
  /** 편집 세션에서 파생된 현재 잠금 상태(응답 아님). */
  lockState: LockState;
  /** 강제 해제 대상 문서 id(`useForceUnlock` 에 전달). */
  documentId: number;
  /** 현재 WS 에서의 role — RequireRole + useForceUnlock(s16 게이팅 경로). 비멤버·미확정이면 null. */
  currentRole: Role | null;
  /** 세션 `is_admin` — useForceUnlock 의 admin bypass 판정용(RequireRole 은 useSession 으로 취득). */
  isAdmin: boolean;
  /** 강제 해제 성공 후 재획득 유도 콜백(`session.retryAcquire`, Req 5.2). */
  onRetry(): void;
}

/** 획득 시각을 사람이 읽을 수 있는 로컬 문자열로 포맷한다(dateTime 은 원본 ISO 유지). */
function formatAcquiredAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString();
}

/**
 * `other` 상태에서 owner/admin 에게만 노출되는 강제 해제 조작. `useForceUnlock` 으로 호출하고
 * 성공 시 `onRetry`, 실패 시 `ErrorMessage` 로 오류를 표면화한다. 노출 게이팅은 상위
 * `<RequireRole>` 이 담당하므로 여기서는 role 비교를 하지 않는다.
 */
function ForceUnlockControl({
  documentId,
  currentRole,
  isAdmin,
  onRetry,
}: {
  documentId: number;
  currentRole: Role | null;
  isAdmin: boolean;
  onRetry(): void;
}): ReactElement {
  const { forceUnlock, state } = useForceUnlock(documentId, currentRole, isAdmin);

  const handleClick = useCallback(async () => {
    const ok = await forceUnlock();
    if (ok) {
      onRetry();
    }
  }, [forceUnlock, onRetry]);

  return (
    <div className="mt-3 space-y-2">
      <Button
        type="button"
        variant="secondary"
        onClick={handleClick}
        disabled={state.pending}
      >
        강제 해제
      </Button>
      <ErrorMessage error={state.error} />
    </div>
  );
}

/** 잠금 상태(self/other/error)를 표시하고, other 일 때 owner/admin 에게 강제 해제를 노출한다. */
export function EditLockBanner({
  lockState,
  documentId,
  currentRole,
  isAdmin,
  onRetry,
}: EditLockBannerProps): ReactElement | null {
  if (lockState.kind === "self") {
    return (
      <div
        role="status"
        className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
      >
        <p className="font-medium">내가 편집 중</p>
        <p className="mt-1 text-emerald-700">
          획득 시각{": "}
          <time data-testid="lock-acquired-at" dateTime={lockState.lock.lock_acquired_at}>
            {formatAcquiredAt(lockState.lock.lock_acquired_at)}
          </time>
        </p>
      </div>
    );
  }

  if (lockState.kind === "other") {
    return (
      <div className="space-y-3">
        <div
          role="status"
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          <p className="font-medium">다른 사용자가 편집 중</p>
        </div>
        {/* 타인 잠금 충돌 안내는 백엔드 ApiError 를 그대로 표면화한다(보유자 식별 정보 미발명, Req 2.3). */}
        <ErrorMessage error={lockState.error} />
        {/* 강제 해제 노출은 오직 s16 게이팅(RequireRole OWNER, admin bypass 포함)으로만 판정한다(Req 5.1·5.5). */}
        <RequireRole minimum={Role.OWNER} currentRole={currentRole}>
          <ForceUnlockControl
            documentId={documentId}
            currentRole={currentRole}
            isAdmin={isAdmin}
            onRetry={onRetry}
          />
        </RequireRole>
      </div>
    );
  }

  if (lockState.kind === "error") {
    return <ErrorMessage error={lockState.error} />;
  }

  // acquiring 등 그 외 상태는 이 배너가 소유하지 않는다(페이지가 로딩/획득 UI 를 표시).
  return null;
}
