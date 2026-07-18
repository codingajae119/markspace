/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 백엔드 API base URL. `src/config.ts` 단일 지점에서만 읽는다. */
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
