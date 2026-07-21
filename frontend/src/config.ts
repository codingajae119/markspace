/**
 * 애플리케이션 전역 설정의 단일 소스.
 *
 * 환경별 값(API base URL 등)은 오직 이 파일에서만 읽고 노출한다.
 * 코드 전역에 하드코딩 base URL 상수를 흩뿌리지 않으며(AC 1.3),
 * 새 환경 값이 필요하면 별도 설정 파일 신설 없이 이 파일을 확장한다(AC 1.4).
 *
 * 모든 환경 값은 단일 Vite env 소스(`import.meta.env.VITE_*`)에서만 읽는다.
 */

/**
 * `.env` 없이도 부팅되도록 하는 유일한 base URL 기본값(단일 지점).
 * 백엔드는 모든 API 를 버전 네임스페이스(`/api/1.0`) 하위에 마운트하므로 base URL 에
 * 그 prefix 를 포함한다(feature 호출부는 `/auth/login` 등 논리 경로만 넘기고, 이 base 가
 * origin+prefix 를 책임진다). dev 는 `.env.development` 가 same-origin 상대경로로 덮어쓴다.
 */
const DEFAULT_API_BASE_URL = "http://localhost:8000/api/1.0";

function resolveApiBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL;
  return fromEnv !== undefined && fromEnv.length > 0
    ? fromEnv
    : DEFAULT_API_BASE_URL;
}

export interface ApiConfig {
  /** 공용 API 클라이언트가 사용하는 백엔드 API base URL. */
  readonly baseUrl: string;
}

/** 공용 API 클라이언트가 소비하는 단일 설정 객체. */
export const apiConfig: ApiConfig = {
  baseUrl: resolveApiBaseUrl(),
};
