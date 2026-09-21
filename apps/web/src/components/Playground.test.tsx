import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PRESETS } from "@/lib/presets";
import { requestFor } from "@/lib/playground";
import { Playground, type ExampleSelection } from "./Playground";

function renderPlayground(selection: ExampleSelection = { id: PRESETS[0].id, index: 0, nonce: 0 }) {
  return render(<Playground selection={selection} onRequestChange={vi.fn()} onToast={vi.fn()} />);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Playground", () => {
  it("shows authored samples without calling fetch", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    renderPlayground();

    expect((await screen.findAllByText("refund")).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /run example/i }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/illustrative values/i)).toBeInTheDocument();
  });

  it("performs a live API call and renders the typed response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          model: "jev-1.13.0",
          answers: {
            request_type: {
              type: "choice",
              choice: "delivery",
              probabilities: { refund: 0.02, delivery: 0.96, other: 0.02 },
              confidence: 0.91,
            },
          },
          usage: { input_tokens: 42, output_tokens: 8 },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderPlayground();
    await userEvent.click(screen.getByRole("button", { name: /live api/i }));
    await userEvent.click(screen.getByRole("button", { name: /run for free/i }));

    await waitFor(() => expect(screen.getAllByText("delivery").length).toBeGreaterThan(0));
    expect(screen.getByText(/Live response received/i)).toBeInTheDocument();
  });

  it("keeps custom edits honest in sample mode", async () => {
    renderPlayground();
    const input = screen.getByLabelText(/your text/i);
    await userEvent.clear(input);
    await userEvent.type(input, "A completely new input.");
    await userEvent.click(screen.getByRole("button", { name: /run example/i }));

    expect(screen.getByText(/No invented answer/i)).toBeInTheDocument();
  });

  it("loads a selected external example", async () => {
    const { rerender } = renderPlayground();
    rerender(<Playground selection={{ id: "spot-urgency", index: 0, nonce: 1 }} onRequestChange={vi.fn()} onToast={vi.fn()} />);

    expect(await screen.findByDisplayValue(/checkout stopped working/i)).toBeInTheDocument();
    expect(screen.getAllByText(/98%/).length).toBeGreaterThan(0);
  });
});
