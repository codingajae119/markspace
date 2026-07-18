import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import App from "@/App";

afterEach(() => {
  cleanup();
});

describe("App scaffold", () => {
  it("renders the app root heading", () => {
    render(<App />);
    const heading = screen.getByRole("heading", { name: "Notion-lite" });
    expect(heading).toBeInTheDocument();
  });

  it("resolves the @/ path alias under Vitest", () => {
    expect(App).toBeTypeOf("function");
  });
});
