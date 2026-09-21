import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it } from "vitest";
import { FAQ } from "./FAQ";

describe("FAQ", () => {
  it("toggles answers accessibly", async () => {
    render(<FAQ />);
    const question = screen.getByRole("button", { name: /Do I need an account/i });

    expect(question).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(question);

    expect(question).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/anonymous HTTP access/i)).toBeInTheDocument();
  });
});
