/**
 * `/lock` 응답을 편집 세션 구동용 프론트 파생 `LockState` 로 매핑하는 순수 함수.
 *
 * 잠금 현재 상태를 조회하는 별도 엔드포인트가 계약에 없으므로(Req 2.4) 입력은 오직
 * `POST /documents/{id}/lock` 의 결과(성공 `DocumentLockRead` 또는 정규화된 `ApiError`)
 * 뿐이며 폴링·추측 조회를 하지 않는다. 잠금 판정(멱등 재획득·타인 충돌)은 백엔드 엔진이
 * 단독 소유하므로 이 함수는 결과를 재판정 없이 표면 상태로만 파생한다.
 *
 * - 200 성공(`{ ok }`) → `{ kind: "self", lock }` (현재 사용자 보유, 멱등 재획득 포함) (Req 2.1)
 * - 409 conflict(`{ error }`) → `{ kind: "other", error }` (타인 보유) (Req 2.2·2.3)
 * - 그 외 오류(403/404/422/500 …) → `{ kind: "error", error }` (Req 2.4)
 *
 * 계약에 없는 보유자 식별 정보를 발명하지 않으며(other/error 는 `ApiError` 만 싣는다),
 * 409 판정은 `code` 문자열이 아니라 `ApiError.status === 409` 로 discriminate 한다.
 * 부수효과가 없어 동일 입력에 동일 출력을 낸다.
 */
import type { DocumentLockRead, LockState } from "../types";
import { ApiError } from "@/shared/api/errors";

export function resolveLockState(
  input: { ok: DocumentLockRead } | { error: ApiError },
): LockState {
  if ("ok" in input) {
    return { kind: "self", lock: input.ok };
  }

  const { error } = input;
  if (error.status === 409) {
    return { kind: "other", error };
  }
  return { kind: "error", error };
}
