import { describe, it, expect, beforeEach, vi } from "vitest";

import { buildLoginPath } from "@/app/routes";
import { installNavigation } from "@/app/installNavigation";
import {
  redirectToLogin,
  resetNavigation,
} from "@/shared/api/navigation";

// 401→라우터 결선(installNavigation)의 단위 테스트. 데이터 라우터를 full-render 하지 않고
// (jsdom/undici AbortSignal realm 비호환 — router.tsx 주석 참조) MOCK 라우터 `{ navigate }` 를
// 주입해, NavSeam(`redirectToLogin`)이 실제로 주입된 navigator + 정규 buildLoginPath 로 결선됐음을
// 관찰한다. 모듈 스코프 싱글턴 누수 방지를 위해 매 테스트 전 seam 상태를 리셋한다.
beforeEach(() => {
  resetNavigation();
});

describe("installNavigation — 401 인터셉터를 실제 라우터로 결선", () => {
  it("navigator 를 주입해 redirectToLogin 이 라우터 navigate 로 라우팅된다 (AC 4.1, 4.2)", () => {
    const navigate = vi.fn();

    installNavigation({ navigate });
    redirectToLogin("/docs/5");

    // 주입된 navigator(=라우터 navigate)를 통해 정확히 1회 이동한다.
    expect(navigate).toHaveBeenCalledTimes(1);
    // 이동 경로는 정규 buildLoginPath 로 만든 returnTo 보존 로그인 경로이며 replace 이동이다.
    expect(navigate).toHaveBeenCalledWith(buildLoginPath("/docs/5"), { replace: true });
    // 정규 규약의 구체 형태(3.1 canonical): /login?returnTo=%2Fdocs%2F5.
    expect(navigate).toHaveBeenCalledWith("/login?returnTo=%2Fdocs%2F5", { replace: true });
  });

  it("정규 buildLoginPath 를 주입해 seam 자립 기본 빌더를 대체한다 (AC 10.1 — 단일 소스 수렴)", () => {
    const navigate = vi.fn();

    installNavigation({ navigate });
    // 루트("/") 는 정규 buildLoginPath 가 returnTo 없이 "/login" 으로 접는다(seam 기본 빌더는
    // "/login?returnTo=%2F" 를 만들었을 것). 이 차이가 정규 빌더 주입을 판별한다.
    redirectToLogin("/");

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/login", { replace: true });
    expect(navigate).toHaveBeenCalledWith(buildLoginPath("/"), { replace: true });
  });
});
