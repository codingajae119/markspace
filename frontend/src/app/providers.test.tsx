import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { composeProviders } from "@/app/providers";
import type { ProviderComponent } from "@/app/providers";

afterEach(() => {
  cleanup();
});

/** testid 마커로 감싸는 샘플 Provider 팩토리. DOM 중첩 순서로 합성 순서를 관찰한다. */
function makeMarker(id: string): ProviderComponent {
  return function Marker({ children }) {
    return <div data-testid={id}>{children}</div>;
  };
}

describe("composeProviders — Provider 합성 슬롯 (AC 10.3)", () => {
  it("배열 순서대로 감싼다: [A, B] → <A><B>{children}</B></A> (A 최외곽)", () => {
    const A = makeMarker("prov-a");
    const B = makeMarker("prov-b");

    render(composeProviders([A, B], <span data-testid="leaf">leaf</span>));

    const a = screen.getByTestId("prov-a");
    const b = screen.getByTestId("prov-b");
    const leaf = screen.getByTestId("leaf");

    // A 가 B 를 감싸고, B 가 leaf 를 감싼다.
    expect(a).toContainElement(b);
    expect(b).toContainElement(leaf);
    // B 가 A 를 감싸지 않음(순서 역전 방지).
    expect(b).not.toContainElement(a);
  });

  it("빈 배열이면 children 을 그대로 렌더한다(합성 없음)", () => {
    render(composeProviders([], <span data-testid="leaf">leaf</span>));

    expect(screen.getByTestId("leaf")).toHaveTextContent("leaf");
    expect(screen.queryByTestId("prov-a")).not.toBeInTheDocument();
  });
});
