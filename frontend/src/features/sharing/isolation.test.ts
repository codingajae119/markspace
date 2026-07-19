/**
 * feature 격리 정적 스캔 검증 (task 5.2, Req 8.5).
 *
 * `src/features/sharing/**` 아래 모든 소스 파일(테스트 제외)이 다른 feature 폴더
 * (`auth`·`workspace`·`document`·`editor`·`attachment` 등)를 **직접 import 하지 않음**을
 * 정적으로 보증한다. 교차 관심사(fetch·에러·라우팅 가드·에디터)는 s16 공통 레이어(`@/shared`,
 * `@/app`, `@/config`)로만 소비해야 하며, feature 간 직접 결합은 격리 경계를 깨뜨린다.
 *
 * 판정 규칙:
 * - `@/features/<other>...` (자기 자신 `@/features/sharing` 제외) → 위반
 * - 다른 feature 로 탈출하는 상대 경로(정규화 결과가 sharing 루트 밖으로 나감) → 위반
 * - 같은 feature 내부 상대 경로(`./`·`../api` 등)와 `@/shared/*`·`@/app/*`·`@/config` → 허용
 *
 * Vite 의 `import.meta.glob({ query: '?raw', eager: true })` 로 소스 원문을 모아 import 문의
 * 경로 지정자만 파싱해 실제 검사한다(자명 통과 방지).
 */

import { describe, it, expect } from "vitest";

/** 이 테스트 파일 기준(= sharing 루트) 하위 모든 ts/tsx 소스 원문. */
const rawModules = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** 테스트 파일 제외(검사 대상은 SOURCE 파일만). */
function isTestFile(relPath: string): boolean {
  return /\.test\.tsx?$/.test(relPath);
}

/** posix 경로 정규화(`.`/`..` 해소). 결과가 루트 밖이면 선두에 `..` 세그먼트가 남는다. */
function normalizePosix(segments: string[]): string[] {
  const out: string[] = [];
  for (const seg of segments) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") {
      if (out.length > 0 && out[out.length - 1] !== "..") {
        out.pop();
      } else {
        out.push("..");
      }
    } else {
      out.push(seg);
    }
  }
  return out;
}

/** importer 파일 경로(sharing 루트 기준)의 디렉터리 세그먼트. 예: `api/shareApi.ts` → [`api`]. */
function dirSegments(relPath: string): string[] {
  const clean = relPath.replace(/^\.\//, "");
  const parts = clean.split("/");
  parts.pop(); // 파일명 제거
  return parts;
}

/**
 * import 경로 지정자가 sharing 격리를 위반하는지 판정.
 * @returns 위반 사유 문자열, 위반 아니면 null.
 */
function violationReason(importerRelPath: string, spec: string): string | null {
  // 별칭 경로: @/features/<other> 만 위반(자기 자신 및 shared/app/config 는 허용).
  if (spec.startsWith("@/")) {
    const featureMatch = /^@\/features\/([^/]+)/.exec(spec);
    if (featureMatch !== null && featureMatch[1] !== "sharing") {
      return `다른 feature 별칭 import: '${spec}'`;
    }
    return null;
  }

  // 상대 경로: 정규화 결과가 sharing 루트 밖(선두 `..`)이면 위반.
  if (spec.startsWith(".")) {
    const combined = [...dirSegments(importerRelPath), ...spec.split("/")];
    const normalized = normalizePosix(combined);
    if (normalized[0] === "..") {
      return `sharing 루트를 벗어나는 상대 import: '${spec}'`;
    }
    return null;
  }

  // 그 외(bare 모듈 지정자: react 등) — 노드 모듈로 격리와 무관.
  return null;
}

/** 한 소스 파일에서 import/export/dynamic-import 의 경로 지정자를 (라인번호와 함께) 추출. */
function extractImportSpecs(source: string): { line: number; spec: string }[] {
  const results: { line: number; spec: string }[] = [];
  const lines = source.split(/\r?\n/);
  // `import ... from "x"`, `export ... from "x"`, `import "x"`, `import("x")` 를 커버.
  const fromRe = /\b(?:import|export)\b[^\n]*?\bfrom\s*["']([^"']+)["']/;
  const sideEffectRe = /^\s*import\s+["']([^"']+)["']/;
  const dynamicRe = /\bimport\s*\(\s*["']([^"']+)["']/;
  lines.forEach((text, idx) => {
    const from = fromRe.exec(text);
    if (from !== null) {
      results.push({ line: idx + 1, spec: from[1] });
      return;
    }
    const side = sideEffectRe.exec(text);
    if (side !== null) {
      results.push({ line: idx + 1, spec: side[1] });
      return;
    }
    const dyn = dynamicRe.exec(text);
    if (dyn !== null) {
      results.push({ line: idx + 1, spec: dyn[1] });
    }
  });
  return results;
}

describe("features/sharing 격리 (Req 8.5)", () => {
  const sourceEntries = Object.entries(rawModules).filter(
    ([relPath]) => !isTestFile(relPath),
  );

  it("스캔 대상 소스 파일이 실제로 존재한다(자명 통과 방지)", () => {
    // sharing feature 는 다수의 소스 파일을 갖는다 — 0개면 glob/필터가 깨진 것.
    expect(sourceEntries.length).toBeGreaterThan(5);
  });

  it("어떤 소스 파일도 다른 feature 를 직접 import 하지 않는다", () => {
    const violations: string[] = [];
    for (const [relPath, source] of sourceEntries) {
      for (const { line, spec } of extractImportSpecs(source)) {
        const reason = violationReason(relPath, spec);
        if (reason !== null) {
          violations.push(`${relPath}:${line} — ${reason}`);
        }
      }
    }
    expect(violations, `feature 격리 위반:\n${violations.join("\n")}`).toEqual([]);
  });
});
