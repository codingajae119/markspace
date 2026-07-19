import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { InvalidationNotice } from "./InvalidationNotice";

afterEach(() => {
  cleanup();
});

describe("InvalidationNotice — 무효화·재발급 안내 (Req 3.4, 5.1, 5.3)", () => {
  it("invalidated=true 이면 재발급 필요 안내를 표시한다 (Req 5.1, 5.3)", () => {
    render(<InvalidationNotice invalidated reissued={false} />);
    // 재발급이 필요하다는 안내가 실제 렌더 텍스트로 보인다.
    expect(screen.getByText(/재발급/)).toBeInTheDocument();
  });

  it("invalidated=true 안내는 복구/재활성화로 이전 토큰이 자동 복원되지 않음을 알린다 (INV-8)", () => {
    render(<InvalidationNotice invalidated reissued={false} />);
    // 자동 복원되지 않는다는 핵심 메시지를 표면화한다.
    expect(screen.getByText(/복원되지 않/)).toBeInTheDocument();
  });

  it("reissued=true 이면 이전 링크 무효 안내를 표시한다 (Req 3.4, 5.3)", () => {
    render(<InvalidationNotice invalidated={false} reissued />);
    // 새 토큰 발급으로 이전 링크가 더 이상 유효하지 않음을 알린다.
    expect(screen.getByText(/이전.*링크.*(무효|유효하지)/)).toBeInTheDocument();
  });

  it("둘 다 false 이면 아무것도 렌더하지 않는다", () => {
    const { container } = render(
      <InvalidationNotice invalidated={false} reissued={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("둘 다 true 이면 두 안내를 모두 표시한다", () => {
    render(<InvalidationNotice invalidated reissued />);
    // invalidated 전용 문구(자동 복원 안 됨)와 reissued 전용 문구(이전 링크 무효)가 모두 보인다.
    expect(screen.getByText(/복원되지 않/)).toBeInTheDocument();
    expect(screen.getByText(/이전.*링크.*(무효|유효하지)/)).toBeInTheDocument();
  });

  it("role=status 로 접근 가능한 안내 영역을 렌더한다", () => {
    render(<InvalidationNotice invalidated reissued={false} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
