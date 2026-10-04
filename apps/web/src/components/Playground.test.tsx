import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PRESETS } from "@/lib/presets";
import { answerForSample, findSample, requestFor } from "@/lib/playground";
import { Playground, ResultPanel, type ExampleSelection } from "./Playground";

function renderPlayground(selection: ExampleSelection = { id: PRESETS[0].id, index: 0, nonce: 0 }) {
  return render(<Playground selection={selection} onRequestChange={vi.fn()} onToast={vi.fn()} />);
}

afterEach(() => {
  vi.useRealTimers();
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

  it("switches to Live API on the first edit when no mode was chosen, without calling the API", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    renderPlayground();
    const input = screen.getByLabelText(/your text/i);
    await userEvent.type(input, " more");

    expect(screen.getByRole("button", { name: /live api/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Switched to Live API because you changed the example/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run for free/i })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps custom edits honest when the visitor chose sample mode", async () => {
    renderPlayground();
    await userEvent.click(screen.getByRole("button", { name: /^sample$/i }));
    await userEvent.click(screen.getByRole("button", { name: /live api/i }));
    await userEvent.click(screen.getByRole("button", { name: /^sample$/i }));
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

function abortableFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((_input, options) => new Promise((_resolve, reject) => {
    options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }));
}

async function startLive() {
  fireEvent.click(screen.getByRole("button", { name: /live api/i }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: /run for free/i })); });
}

describe("landing request lifecycle", () => {
  it("cancels a live request without substituting a sample", async () => {
    const fetch = abortableFetch();
    renderPlayground();
    await startLive();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /^cancel$/i })); });
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(screen.getByText("Request cancelled. The server may already have received it.")).toBeInTheDocument();
    expect(document.querySelector(".result-main")).toBeNull();
  });

  it("times out after twenty seconds with the current failure message", async () => {
    vi.useFakeTimers();
    const fetch = abortableFetch();
    renderPlayground();
    await startLive();
    await act(async () => { await vi.advanceTimersByTimeAsync(19_999); });
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetch.mock.calls[0][1]?.signal?.reason).toBe("timeout");
    expect(screen.getByText(/longer than 20 seconds. No sample was substituted/)).toBeInTheDocument();
  });

  it("aborts on unmount and clears the active timeout", async () => {
    vi.useFakeTimers();
    const fetch = abortableFetch();
    const { unmount } = renderPlayground();
    await startLive();
    unmount();
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ignores a response settled after an edit", async () => {
    let resolve!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise((done) => { resolve = done; }));
    renderPlayground();
    await startLive();
    fireEvent.change(screen.getByLabelText(/your text/i), { target: { value: "Changed input" } });
    const response = answerForSample(findSample(requestFor(PRESETS[0]))!);
    await act(async () => { resolve(new Response(JSON.stringify(response), { headers: { "Content-Type": "application/json" } })); });
    expect(screen.queryByText(/Live response received/)).not.toBeInTheDocument();
    expect(screen.getByText("Input updated. Run again to get a new answer.")).toBeInTheDocument();
  });

  it("rejects invalid advanced JSON before any live request", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    renderPlayground();
    fireEvent.click(screen.getByRole("button", { name: /advanced mode/i }));
    fireEvent.change(screen.getByLabelText(/your request - JSON/i), { target: { value: "{" } });
    expect(screen.getByRole("button", { name: /run for free/i })).toBeDisabled();
    expect(screen.getByText(/This JSON is not valid yet/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("result presentation", () => {
  it("renders choice, noul and score answers in request order, with raw and copy controls", () => {
    const request = {
      model: "jev-latest", state: "Test", questions: {
        route: { type: "choice" as const, instructions: "Route", criteria: { yes: "Yes", no: "No" } },
        urgent: { type: "noul" as const, instructions: "Urgent?" },
        rating: { type: "score" as const, instructions: "Rate", criteria: ["Low", "Medium", "High"] },
      },
    };
    const result = {
      model: "jev-test", answers: {
        route: { type: "choice" as const, choice: "yes", probabilities: { yes: 0.8, no: 0.2 }, confidence: 0.6 },
        urgent: { type: "noul" as const, noul: 0.75 },
        rating: { type: "score" as const, score: 1.234, probabilities: { "0": 0.1, "1": 0.7, "2": 0.2 }, confidence: 0.8, legend: { "0": "Low", "1": "Medium", "2": "High" } },
      },
    };
    const onToggleRaw = vi.fn();
    const onCopyResult = vi.fn();
    const props = { request, result, badge: "Live response", live: true, rawVisible: false, nextStep: "Continue", meta: "jev-test", running: false, onToggleRaw, onCopyResult };
    const { container, rerender } = render(<ResultPanel {...props} />);
    expect([...container.querySelectorAll(".result-pretitle")].map((node) => node.textContent)).toEqual(["route", "urgent", "rating"]);
    expect(screen.getByText("1.23")).toBeInTheDocument();
    expect(screen.getByText("yes", { selector: ".unit" })).toBeInTheDocument();
    expect(screen.getByText("Level 1")).toBeInTheDocument();
    expect(container.querySelectorAll(".confidence-line")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "View JSON" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy result" }));
    expect(onToggleRaw).toHaveBeenCalledOnce();
    expect(onCopyResult).toHaveBeenCalledOnce();
    rerender(<ResultPanel {...props} rawVisible />);
    expect(container.querySelector(".raw-result")?.textContent).toBe(JSON.stringify(result, null, 2));
    expect(screen.getByRole("button", { name: "Visual answer" })).toBeInTheDocument();
  });
});
