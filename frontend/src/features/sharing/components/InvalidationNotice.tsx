/**
 * 무효화·재발급 안내 (design.md §화면 컴포넌트 `InvalidationNotice`, Req 3.4·5.1·5.3).
 *
 * 순수 표시(presentational) 컴포넌트로, 관측된 두 신호(`invalidated`·`reissued`)만
 * 사용자에게 안내한다. 어떤 판단/은퇴(retire) 결정도 하지 않으며(Req 5.2 는 백엔드·
 * useShareManager 소관), 신호 배선은 패널(task 3.4)이 담당한다.
 *
 * - `invalidated === true`: 현재 공유 링크가 무효화되었을 수 있고 다시 공유하려면
 *   **새 토큰 재발급**이 필요하다는 안내. 문서 복구·게이트 재활성화로 이전 토큰이
 *   자동 복원되지 않는다는 점(INV-8)을 함께 알린다(Req 5.1·5.3).
 * - `reissued === true`: 재발급으로 **새 토큰**이 생성되어 이전에 배포한 링크는 더 이상
 *   유효하지 않다는 안내(INV-8)(Req 3.4·5.3).
 * - 둘 다 true → 두 안내 모두 표시. 둘 다 false → 아무것도 렌더하지 않음(`null`).
 */

import type { ReactElement } from "react";

export interface InvalidationNoticeProps {
  /** 현재 공유 링크가 무효화되었을 수 있어 재발급이 필요한 상태. */
  invalidated: boolean;
  /** 재발급으로 새 토큰이 발급되어 이전 링크가 무효가 된 상태. */
  reissued: boolean;
}

/** 관측된 무효화·재발급 신호를 안내. 둘 다 false 면 렌더하지 않음(`null`). */
export function InvalidationNotice({
  invalidated,
  reissued,
}: InvalidationNoticeProps): ReactElement | null {
  if (!invalidated && !reissued) {
    return null;
  }

  return (
    <div
      role="status"
      className="space-y-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
    >
      {invalidated ? (
        <p>
          현재 공유 링크가 무효화되었을 수 있습니다. 다시 공유하려면 새 토큰으로 재발급해야
          합니다. 문서를 복구하거나 공유를 다시 켜더라도 이전 토큰은 자동으로 복원되지 않습니다.
        </p>
      ) : null}
      {reissued ? (
        <p>
          재발급으로 새 토큰이 발급되었습니다. 이전에 배포한 링크는 더 이상 유효하지 않습니다.
        </p>
      ) : null}
    </div>
  );
}
