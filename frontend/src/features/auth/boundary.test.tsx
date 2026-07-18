/**
 * 경계·미제공 범위·타입 가드 테스트 (s17-fe-auth, task 5.2).
 *
 * 세 축을 동결한다:
 *  (A) import 경계(Req 6.4): `features/auth/*` 는 s16 `@/app`·`@/shared`(+`@/config`) 와
 *      intra-feature 상대 경로만 소비한다. 다른 feature(`@/features/*`)나 auth 디렉터리를 벗어나는
 *      상대 경로는 금지(교차 관심사는 반드시 `@/` 를 통해서만).
 *  (B) 미제공 범위(Req 6.2·6.3): 게스트 화면(LoginPage)에 self sign-up / 비밀번호 분실 재설정
 *      진입점이 없다(렌더 단언 primary + 정적 소스 grep soft 보완).
 *  (C) strict 타입·`any` 미사용(Req 6.4·6.5): `npm run typecheck` 0 errors 와
 *      `grep any src/features/auth` empty 로 별도 검증한다(이 파일이 아닌 커맨드 산출물).
 *
 * 로직 부하(load-bearing) 증명:
 *  import 경계 매처는 (A) 절대 스펙이 `@/app`/`@/shared`/`@/config` prefix 를 벗어나면(예: 다른
 *  feature 를 절대 경로로 당겨오면) `isAllowedAbsolute` 가 false 를 돌려 실패하고, (B) 상대 스펙이
 *  auth 루트를 벗어나면(예: `../../workspace/...`) `relative(AUTH_ROOT, resolved)` 가 `..` 로 시작해
 *  실패한다. 아래 "매처 부하 증명" 테스트가 합성 입력으로 두 갈래를 직접 확인한다(실파일 오염 없음).
 *
 * Requirements: 6.2, 6.3, 6.4, 6.5
 */

import { describe, it, expect, afterEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve, relative, dirname, isAbsolute } from "node:path";

import { LoginPage } from "./pages/LoginPage";

// features/auth 루트. vitest 는 frontend 패키지 루트(process.cwd())에서 실행되므로 거기에 상대 결합한다.
const AUTH_ROOT = join(process.cwd(), "src", "features", "auth");

// --- 정적 스캔 헬퍼 (모두 명시 타입, any 미사용) -----------------------------

/** auth 루트 하위 모든 `.ts`/`.tsx` 파일의 절대 경로를 재귀 수집한다(테스트 파일 포함). */
function collectSourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...collectSourceFiles(full));
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * 주석을 제거한다(블록 → 라인). 라인 주석 제거는 `://`(URL) 를 보호하기 위해 `//` 앞이
 * 인용부호/콜론/역슬래시가 아닐 때만 자른다. import 스펙 오탐(주석 속 예시 문자열)을 배제한다.
 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
}

/**
 * 소스에서 모듈 스펙(정적 import/export + type-only + side-effect + dynamic import)을 뽑는다.
 * `from "X"` / `import "X"` / `import("X")` 세 형태를 커버하며 멀티라인 import 도 매치한다.
 */
function extractSpecifiers(source: string): string[] {
  const stripped = stripComments(source);
  const specs: string[] = [];
  const patterns: RegExp[] = [
    /(?:import|export)\b[^;]*?\bfrom\s*["']([^"']+)["']/g, // import/export ... from "X" (type-only 포함)
    /\bimport\s*["']([^"']+)["']/g, //                       import "X" (side-effect)
    /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g, //             import("X") (dynamic)
  ];
  for (const re of patterns) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(stripped)) !== null) {
      specs.push(m[1]);
    }
  }
  return specs;
}

/** 절대 `@/...` 스펙이 허용 레이어(s16 app·shared + config)에 속하는지. `@/features/*` 는 false. */
function isAllowedAbsolute(spec: string): boolean {
  return (
    spec === "@/app" ||
    spec.startsWith("@/app/") ||
    spec === "@/shared" ||
    spec.startsWith("@/shared/") ||
    spec === "@/config" ||
    spec.startsWith("@/config/")
  );
}

/** 상대 스펙을 파일 위치 기준으로 해석해 auth 루트 안에 머무는지. 벗어나면(../ 로 시작) false. */
function relativeStaysUnderAuth(fromFile: string, spec: string): boolean {
  const resolved = resolve(dirname(fromFile), spec);
  const rel = relative(AUTH_ROOT, resolved);
  return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
}

interface ImportViolation {
  file: string;
  spec: string;
  reason: string;
}

afterEach(() => {
  cleanup();
});

// ---------------------------------------------------------------------------
// (A) import 경계 (Req 6.4)
// ---------------------------------------------------------------------------

describe("import 경계 — features/auth 는 s16 app·shared(+config)·intra-feature 만 소비 (Req 6.4)", () => {
  const files = collectSourceFiles(AUTH_ROOT);

  it("스캔 대상 파일이 실제로 존재한다(빈 glob 의 vacuous 통과 방지)", () => {
    // auth 루트에는 api/components/hooks/pages/routes + 이 테스트까지 다수 파일이 있어야 한다.
    expect(files.length).toBeGreaterThan(0);
    expect(files.length).toBeGreaterThanOrEqual(10);
  });

  it("모든 절대/상대 import 가 허용 경계를 지킨다(위반 시 파일+스펙 열거)", () => {
    const violations: ImportViolation[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf8");
      for (const spec of extractSpecifiers(source)) {
        if (spec.startsWith("@/")) {
          // 절대 alias: app/shared/config 만 허용. 특히 @/features/* 는 교차-feature 위반.
          if (!isAllowedAbsolute(spec)) {
            violations.push({
              file: relative(AUTH_ROOT, file),
              spec,
              reason: "absolute alias 는 @/app·@/shared·@/config 만 허용(다른 feature 금지)",
            });
          }
        } else if (spec.startsWith(".")) {
          // 상대 경로: auth 루트 밖으로 나가면(다른 feature/상위 app·shared 침투) 위반.
          if (!relativeStaysUnderAuth(file, spec)) {
            violations.push({
              file: relative(AUTH_ROOT, file),
              spec,
              reason: "상대 import 가 features/auth 를 벗어남(교차 관심사는 @/ 로만)",
            });
          }
        }
        // 그 외 bare 스펙(react, vitest, react-router-dom, node:* 등)은 외부 패키지로 허용.
      }
    }

    const message =
      violations.length === 0
        ? ""
        : "import 경계 위반:\n" +
          violations.map((v) => `  - ${v.file}: "${v.spec}" (${v.reason})`).join("\n");
    expect(violations, message).toEqual([]);
  });

  it("매처 부하 증명 — 교차-feature 절대/이탈 상대 스펙을 실제로 잡아낸다", () => {
    // (A) 다른 feature 절대 import 는 거부된다.
    expect(isAllowedAbsolute("@/features/workspace/api")).toBe(false);
    expect(isAllowedAbsolute("@/features/auth/pages/LoginPage")).toBe(false); // self-absolute 도 금지
    // 허용 레이어는 통과한다.
    expect(isAllowedAbsolute("@/app/routes")).toBe(true);
    expect(isAllowedAbsolute("@/shared/ui")).toBe(true);
    expect(isAllowedAbsolute("@/config")).toBe(true);

    // (B) auth 를 벗어나는 상대 경로는 거부, intra-feature 는 통과.
    const componentFile = join(AUTH_ROOT, "components", "LoginForm.tsx");
    expect(relativeStaysUnderAuth(componentFile, "../../workspace/api")).toBe(false);
    expect(relativeStaysUnderAuth(componentFile, "../../../app/routes")).toBe(false);
    expect(relativeStaysUnderAuth(componentFile, "../hooks/useLogin")).toBe(true);
    expect(relativeStaysUnderAuth(componentFile, "./LoginForm")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// (B) self sign-up / 비밀번호 분실 재설정 부재 (Req 6.2, 6.3)
// ---------------------------------------------------------------------------

// LoginPage → LoginForm → useLogin → useSession(s16). 게스트 화면 렌더를 위해 세션 훅만 모킹한다
// (컴포넌트 자체는 실제 렌더). unauthenticated + no-op refresh 로 s16 세션 계약을 최소 충족한다.
vi.mock("@/app/session/useSession", () => ({
  useSession: () => ({ status: "unauthenticated", refresh: vi.fn() }),
}));

describe("미제공 범위 — 게스트 화면에 self sign-up / 비밀번호 재설정 진입점 없음 (Req 6.2, 6.3)", () => {
  it("LoginPage 에 가입/비밀번호 찾기 링크·텍스트가 없다(렌더 단언 primary)", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>,
    );

    // 정상 로그인 화면임을 먼저 확인(렌더가 실제로 일어났는지 앵커).
    expect(screen.getByRole("button", { name: "로그인" })).toBeInTheDocument();

    // 가입/비밀번호 분실 재설정 affordance 부재: link role 과 text 양쪽으로 확인.
    expect(
      screen.queryByRole("link", {
        name: /가입|회원가입|sign\s?up|비밀번호.*(찾기|재설정|분실|초기화)|forgot|reset/i,
      }),
    ).toBeNull();
    expect(
      screen.queryByText(/회원가입|sign\s?up|비밀번호.*(찾기|재설정|분실)|forgot password/i),
    ).toBeNull();
  });

  it("(soft 보완) auth 소스에 signup/register/forgot·reset password 화면·경로가 없다", () => {
    // self-service 재설정 화면만 금지. 인증된 본인 변경(ChangePasswordPage)은 정상 기능이라
    // "password" 일반어는 잡지 않고, 재설정/분실/가입 형태만 겨냥한다.
    const FORBIDDEN =
      /(sign[-_ ]?up|\bregister\b|forgot[-_ ]?password|reset[-_ ]?password|password[-_ ]?reset|forgotPassword|passwordReset)/i;

    const offenders: string[] = [];
    for (const file of collectSourceFiles(AUTH_ROOT)) {
      // 이 가드 파일 자신은 금지어를 (부재 단언 목적으로) 필연적으로 포함하므로 자기참조 제외.
      if (file.endsWith("boundary.test.tsx")) continue;
      const stripped = stripComments(readFileSync(file, "utf8"));
      if (FORBIDDEN.test(stripped)) {
        offenders.push(relative(AUTH_ROOT, file));
      }
    }

    expect(offenders, `self sign-up/재설정 흔적 발견: ${offenders.join(", ")}`).toEqual([]);
  });
});
