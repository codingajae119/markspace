/**
 * 라우트 경로 상수 및 returnTo 규약의 정규(단일) 소스.
 *
 * design.md "app / router → Router & ProtectedRoute" 의 routes.ts 계약을 구현한다.
 * 여기 정의된 {@link ROUTES}·{@link RETURN_TO_PARAM}·{@link buildLoginPath}·
 * {@link resolveReturnTo} 가 라우트 경로 상수와 returnTo 보존/복귀 규약의 **단일 소스**다.
 *
 * NavSeam(`shared/api/navigation.ts`, task 2.2)은 라우팅을 정적으로 import 하지 않기 위해
 * 동일한 `/login` 기본값·`returnTo` 키를 자립적으로 갖고 있으나, 앱 부팅(task 7.1)에서
 * 이 파일의 {@link buildLoginPath} 를 `setLoginPathBuilder` 로 주입해 런타임 단일 소스로
 * 수렴한다. 그러므로 이 모듈은 seam 을 **import 하지 않는** 순수 모듈로 유지한다.
 *
 * Requirements: 2.2(진입하려던 경로를 returnTo 로 보존 후 로그인 리다이렉트),
 * 2.3(로그인 성공 시 보존된 returnTo 로 복귀, 없으면 기본 경로로 이동).
 */

/**
 * 정규 라우트 경로 상수. 라우트 경로 문자열의 단일 소스이며 `as const` 로 리터럴 고정한다.
 * - `login`: 미인증 리다이렉트 목적지(returnTo 쿼리 부착).
 * - `root`: 인증 후 기본 복귀 경로.
 * - `share`: `/share/:token` 게스트 라우트(인증 가드 없음, 뷰는 s22 소유).
 */
export const ROUTES = {
  login: "/login",
  root: "/",
  share: "/share/:token",
} as const;

/**
 * returnTo 쿼리 파라미터 키. NavSeam 기본 빌더(task 2.2)가 쓰는 문자열과 동일해야
 * returnTo 가 왕복(round-trip)한다.
 */
export const RETURN_TO_PARAM = "returnTo";

/**
 * returnTo 를 보존한 로그인 경로를 만든다.
 *
 * `returnTo` 가 비었거나 루트(`/`)면 `?returnTo=%2F` 잡음을 피하기 위해 쿼리 없이
 * {@link ROUTES.login} 만 반환한다(복귀 기본값이 어차피 루트이므로 정보 손실 없음).
 * 그 외에는 `${ROUTES.login}?${RETURN_TO_PARAM}=<encodeURIComponent(returnTo)>` 를 반환한다.
 */
export function buildLoginPath(returnTo: string): string {
  if (returnTo === "" || returnTo === ROUTES.root) {
    return ROUTES.login;
  }
  return `${ROUTES.login}?${RETURN_TO_PARAM}=${encodeURIComponent(returnTo)}`;
}

/**
 * 주어진 location search 문자열에서 보존된 returnTo 복귀 경로를 복원한다.
 *
 * `URLSearchParams` 로 {@link RETURN_TO_PARAM} 를 읽어 디코드한다. 파라미터가 없거나
 * 비었으면 기본 {@link ROUTES.root} 를 반환한다.
 *
 * 오픈 리다이렉트 방지: 동일 출처 상대 경로(`/` 로 시작)만 허용하고, 프로토콜 상대
 * (`//host` 또는 백슬래시 변종 `/\`, `\\`)나 절대 URL 은 거부하고 {@link ROUTES.root} 로
 * 폴백한다. 이 게이팅은 편의가 아니라 안전 경계다.
 */
export function resolveReturnTo(search: string): string {
  const query = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(query);
  const returnTo = params.get(RETURN_TO_PARAM);

  if (returnTo === null || returnTo === "") {
    return ROUTES.root;
  }

  if (!isSafeRelativePath(returnTo)) {
    return ROUTES.root;
  }

  return returnTo;
}

/**
 * 오픈 리다이렉트 안전 판정: 동일 출처 상대 경로만 참.
 *
 * - 반드시 `/` 로 시작한다(절대 URL·상대 세그먼트 거부).
 * - 두 번째 문자가 `/` 또는 `\` 이면 프로토콜 상대(`//evil.com`, `/\evil.com`)로 간주해 거부.
 * - 첫 문자가 백슬래시(`\\evil.com`)인 경우도 `/` 로 시작하지 않으므로 거부된다.
 */
function isSafeRelativePath(path: string): boolean {
  if (!path.startsWith("/")) {
    return false;
  }
  const second = path.charAt(1);
  if (second === "/" || second === "\\") {
    return false;
  }
  return true;
}
