import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "./page";

describe("Home placeholder page", () => {
  it("renders the wordmark and tagline", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: "CASSANDRA" }),
    ).toBeInTheDocument();
    expect(screen.getByText("DATA. MODELS. RESULTS.")).toBeInTheDocument();
  });

  it("notes that the engine is under construction", () => {
    render(<Home />);

    expect(
      screen.getByText(/engine is under construction/i),
    ).toBeInTheDocument();
  });
});
