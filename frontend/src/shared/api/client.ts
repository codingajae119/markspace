/**
 * 공용 fetch 래퍼(단일 API 클라이언트).
 *
 * 모든 백엔드 호출은 이 모듈을 통과한다. base URL(`apiConfig.baseUrl`) 결선, 서명 쿠키
 * 세션 전송(`credentials:"include"`), JSON/바이너리 응답 분기, 오류 본문의 단일 정규화
 * ({@link ApiError}), 그리고 전역 401 인터셉터를 여기 단일 지점에만 둔다. 각 feature
 * 호출부는 fetch 설정·에러 해석·401 처리를 중복 구현하지 않는다.
 *
 * Requirements:
 * - 3.1 단일 base URL 기준 호출 / 3.2 credentials 포함 / 3.5 타입 안전 결과(JSON·Blob)
 * - 4.1 401 → returnTo 보존 후 로그인 리다이렉트 / 4.2 401 처리 단일 지점 /
 *   4.3 비-401 정상 흐름(게스트 라우트 포함)은 강제 리다이렉트 없음 /
 *   4.4 skip(부트스트랩 /auth/me)·이미-로그인 경로면 리다이렉트 루프 없이 미인증 전이
 *
 * 오류 본문의 `ErrorResponse` 파싱·정규화(3.3/3.4)는 {@link parseErrorResponse} 소유이며
 * 이 모듈은 그것을 소비한다(발명 금지).
 */

import { apiConfig } from "@/config";
import { parseErrorResponse } from "@/shared/api/errors";
import { redirectToLogin } from "@/shared/api/navigation";

/** 공용 API 요청 옵션(design.md ApiClient 계약). */
export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  /** JSON 직렬화 대상, 또는 그대로 전송되는 `FormData`(multipart). */
  body?: unknown;
  /** 응답 해석 방식. 기본 `json`; 첨부 서빙 등 바이너리는 `blob`. */
  responseType?: "json" | "blob";
  signal?: AbortSignal;
  /** 부트스트랩 `/auth/me` 등에서 401 리다이렉트를 제외(미인증 전이만). */
  skipAuthRedirect?: boolean;
}

/**
 * 로그인 경로 판정용 기본값. NavSeam 의 `DEFAULT_LOGIN_PATH` 와 동일 문자열을 미러링한다.
 * 정규 로그인 경로 상수는 `app/routes.ts`(task 3.1)이며 부팅 시(task 7.1) seam 에 주입된다.
 * `shared → app` 정적 의존 금지 규칙상 여기서 직접 import 할 수 없어 로컬 상수로 둔다.
 */
const LOGIN_PATH_PREFIX = "/login";

/** `apiConfig.baseUrl` + path 로 절대 URL 구성. base URL 을 하드코딩하지 않는다. */
function buildUrl(path: string): string {
  const base = apiConfig.baseUrl.replace(/\/+$/, "");
  return `${base}${path}`;
}

/** 현재 앱이 로그인 경로에 체류 중인가(401 루프 방지 판정, AC 4.4). */
function isOnLoginRoute(): boolean {
  return window.location.pathname.startsWith(LOGIN_PATH_PREFIX);
}

/** returnTo 보존용 현재 경로(pathname + search). */
function currentPath(): string {
  return `${window.location.pathname}${window.location.search}`;
}

/** 성공 응답의 JSON 파싱. 204/빈 본문은 `undefined` 로 우아하게 처리. */
async function parseJsonBody(res: Response): Promise<unknown> {
  if (res.status === 204) {
    return undefined;
  }
  const text = await res.text();
  if (text.length === 0) {
    return undefined;
  }
  return JSON.parse(text) as unknown;
}

/** 오류 응답 본문 판독: JSON 우선, 실패 시 원문 텍스트, 빈 본문은 undefined. */
async function readErrorBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (text.length === 0) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/**
 * 공용 fetch 래퍼. 2xx → 타입 `T`(json) 또는 `Blob`(responseType:"blob");
 * 그 외 → 단일 정규화된 {@link ApiError} throw. 401(비-skip·비-로그인경로)이면 throw
 * 전에 로그인 리다이렉트를 트리거한다.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, responseType = "json", signal, skipAuthRedirect } = options;

  const headers: Record<string, string> = {};
  let requestBody: BodyInit | undefined;
  if (body !== undefined) {
    if (body instanceof FormData) {
      // multipart 경계는 브라우저가 설정하므로 Content-Type 을 지정하지 않는다.
      requestBody = body;
    } else {
      headers["Content-Type"] = "application/json";
      requestBody = JSON.stringify(body);
    }
  }

  const res = await fetch(buildUrl(path), {
    method,
    credentials: "include",
    headers,
    body: requestBody,
    signal,
  });

  if (res.ok) {
    if (responseType === "blob") {
      return (await res.blob()) as T;
    }
    return (await parseJsonBody(res)) as T;
  }

  const errorBody = await readErrorBody(res);

  // 전역 401 인터셉터 — 이 단일 지점에만 존재(AC 4.2). 그 외 상태는 정규화 후 throw 만(AC 4.3).
  if (res.status === 401 && skipAuthRedirect !== true && !isOnLoginRoute()) {
    redirectToLogin(currentPath());
  }

  throw parseErrorResponse(res.status, errorBody);
}

/** design.md ApiClient 편의 메서드 계약. */
export interface ApiClient {
  get<T>(path: string, options?: RequestOptions): Promise<T>;
  post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T>;
  patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T>;
  del<T>(path: string, options?: RequestOptions): Promise<T>;
}

/** 하위 feature 데이터 훅·세션 부트스트랩이 소비하는 단일 클라이언트 인스턴스. */
export const apiClient: ApiClient = {
  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return apiRequest<T>(path, { ...options, method: "GET" });
  },
  post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return apiRequest<T>(path, { ...options, method: "POST", body });
  },
  patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return apiRequest<T>(path, { ...options, method: "PATCH", body });
  },
  del<T>(path: string, options?: RequestOptions): Promise<T> {
    return apiRequest<T>(path, { ...options, method: "DELETE" });
  },
};
