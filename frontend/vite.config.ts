/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * 개발 프록시: 백엔드는 모든 API 를 단일 버전 네임스페이스(`/api/1.0`) 하위에 마운트하고,
 * 프론트(`.env.development`)는 `VITE_API_BASE_URL=/api/1.0` 로 same-origin 상대 호출을 낸다.
 * 그래서 `/api` 로 시작하는 요청만 백엔드(:8000)로 중계하면 되고, SPA 라우트(`/login`·
 * `/documents`·`/admin`·`/share/:token` 등)와 경로가 겹치지 않는다(네임스페이싱으로 충돌 제거).
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
  },
});
