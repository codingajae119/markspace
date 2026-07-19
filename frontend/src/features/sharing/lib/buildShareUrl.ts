/**
 * 게스트 공유 링크 구성 순수 함수.
 *
 * 관리자에게 표시·복사되는 대상은 백엔드 `share_url`(`/public/{token}` 공개 API 경로)이
 * 아니라 게스트가 브라우저로 여는 프론트 링크(`<origin>/share/<token>`)다. 경로 세그먼트는
 * s16 `ROUTES.share`(정적 문자열 `"/share/:token"`, 경로 빌더 함수가 아님)의 `:token`
 * 자리표시자를 직접 치환하여 파생하므로, 라우트 경로 상수의 단일 소스에서만 `/share/` 리터럴이
 * 나온다. `window.location.origin` 읽기 외에는 부수효과가 없어 단위 테스트로 계약을 고정한다
 * (Requirements 2.2, 4.1).
 */
import { ROUTES } from "@/app/routes";

/**
 * 게스트가 여는 프론트 공유 링크(`<origin>/share/<token>`)를 구성한다(Req 2.2, 4.1).
 *
 * `origin`은 `window.location.origin`에서 취하고, 경로는 `ROUTES.share`의 `:token`을
 * 인자 `token`으로 치환한다. 백엔드 공개 API 경로(`/public/{token}`)는 노출하지 않는다.
 */
export function buildShareUrl(token: string): string {
  const origin = window.location.origin;
  return `${origin}${ROUTES.share.replace(":token", token)}`;
}
