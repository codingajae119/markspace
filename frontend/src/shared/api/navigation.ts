/**
 * 401 인터셉터용 네비게이션 주입 seam.
 *
 * 전역 401 인터셉터(공용 API 클라이언트, task 2.3)는 세션 만료 시 로그인 경로로
 * 리다이렉트해야 하지만, `shared/` 레이어는 라우팅(`src/app/*`)을 정적으로 import 하지
 * 않는다(design.md "Dependency Direction (강제)": `shared → app` 역방향 정적 의존 금지).
 * 이를 위해 라우터의 네비게이션 핸들을 **런타임에 주입**받는 seam 을 둔다. 앱 부팅 시점
 * (task 7.1)에 라우터가 {@link setNavigator} 로 실제 navigate 함수를 주입하고, 선택적으로
 * {@link setLoginPathBuilder} 로 `app/routes.ts` 의 정규 `buildLoginPath` 를 주입해
 * 로그인 경로 규약을 런타임 단일 소스로 유지한다.
 *
 * Requirements: 4.1(현재 경로를 returnTo 로 보존 후 로그인 리다이렉트), 4.2(401 처리
 * 단일 지점), 4.4(리다이렉트 루프 방지 — seam 은 요청받을 때만 이동하며 skip/이미-로그인
 * 판정은 API 클라이언트/부트스트랩 소유).
 */

/** 라우터가 주입하는 네비게이션 핸들. React Router `navigate` 시그니처와 동형. */
export type Navigate = (to: string, options?: { replace?: boolean }) => void;

/** 현재 경로로부터 returnTo 보존 로그인 경로를 만드는 빌더. */
export type LoginPathBuilder = (currentPath: string) => string;

/** 기본 로그인 경로. 라우터 주입 빌더가 없을 때 seam 이 자립적으로 사용한다. */
const DEFAULT_LOGIN_PATH = "/login";
/** returnTo 쿼리 파라미터 키. `app/routes.ts` 규약(task 3.1)과 동일 문자열. */
const RETURN_TO_PARAM = "returnTo";

/**
 * 자립형 기본 로그인 경로 빌더: `/login?returnTo=<encodeURIComponent(currentPath)>`.
 * 라우터가 정규 빌더를 주입하기 전(또는 미주입)에도 seam 이 독립적으로 동작하게 한다.
 */
function defaultLoginPathBuilder(currentPath: string): string {
  return `${DEFAULT_LOGIN_PATH}?${RETURN_TO_PARAM}=${encodeURIComponent(currentPath)}`;
}

// 모듈 스코프 싱글턴 — 앱 부팅 시 1회 주입된다.
let navigator: Navigate | null = null;
let loginPathBuilder: LoginPathBuilder | null = null;

/**
 * 라우터 네비게이션 핸들을 주입한다(앱 부팅 시 1회). 주입 전에는 {@link redirectToLogin}
 * 이 안전한 no-op 이다.
 */
export function setNavigator(nav: Navigate): void {
  navigator = nav;
}

/**
 * 로그인 경로 빌더를 주입한다(선택). 앱 부팅 시 `app/routes.ts` 의 정규 `buildLoginPath`
 * 를 주입하면 로그인 경로 규약이 런타임 단일 소스가 된다. 미주입 시 자립형 기본 빌더 사용.
 */
export function setLoginPathBuilder(fn: LoginPathBuilder): void {
  loginPathBuilder = fn;
}

/**
 * returnTo 를 보존한 로그인 경로로 이동을 요청한다.
 *
 * - navigator 가 주입되지 않았으면 안전하게 무시한다(no-op, 던지지 않음). skip/이미-로그인
 *   판정은 호출부(API 클라이언트·부트스트랩) 소유이며 이 seam 은 순수 "로그인으로 이동"만 한다.
 * - navigator 가 있으면 (주입 빌더 ?? 기본 빌더)로 경로를 계산해 `replace` 이동한다.
 */
export function redirectToLogin(currentPath: string): void {
  if (navigator === null) {
    return;
  }
  const build = loginPathBuilder ?? defaultLoginPathBuilder;
  const to = build(currentPath);
  navigator(to, { replace: true });
}

/**
 * 주입된 모듈 상태를 초기화한다. 모듈 스코프 싱글턴이 테스트 간 누수하지 않도록 하는
 * 테스트 전용 헬퍼(프로덕션 코드는 부팅 시 1회 주입하므로 호출하지 않는다).
 */
export function resetNavigation(): void {
  navigator = null;
  loginPathBuilder = null;
}
