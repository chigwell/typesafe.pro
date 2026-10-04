import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UseCasePlayground } from "./UseCasePlayground";
import { useCaseFixture } from "@/test/use-case-fixture";
import { LANGUAGE_ORDER, LANGUAGES } from "@/lib/codegen";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("use-case playground", () => {
  it("renders complete Python in initial HTML and makes no automatic call", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const examples = useCaseFixture().examples;
    expect(renderToString(<UseCasePlayground examples={examples} />)).toContain("urllib");
    render(<UseCasePlayground examples={examples} />);
    expect(screen.getByText("Previous verification")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "edge input" }));
    expect(fetch).not.toHaveBeenCalled();
    for (const language of LANGUAGE_ORDER) expect(screen.getByRole("tab", { name: LANGUAGES[language].label })).toBeInTheDocument();
  });
  it("sends edited request only on click and displays a real response", async () => {
    const examples = useCaseFixture().examples;
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(examples[0].response), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<UseCasePlayground examples={examples} />);
    const edited = { ...examples[0].request, state: "A pipe is dripping." };
    fireEvent.change(screen.getByLabelText("Request JSON"), { target: { value: JSON.stringify(edited) } });
    expect(fetch).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Try online" }));
    await waitFor(() => expect(screen.getByText(/Live response received/)).toBeInTheDocument());
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual(edited);
    expect(fetch.mock.calls[0][1]?.credentials).toBe("omit");
  });
  it("blocks invalid JSON and does not substitute a saved answer for failure", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 429 }));
    render(<UseCasePlayground examples={useCaseFixture().examples} />);
    fireEvent.change(screen.getByLabelText("Request JSON"), { target: { value: "{" } });
    expect(screen.getByRole("button", { name: "Try online" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Reset example" }));
    await userEvent.click(screen.getByRole("button", { name: "Try online" }));
    expect(await screen.findByText(/free rate limit was reached/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("ignores a completed response after the user edits another example", async () => {
    const examples = useCaseFixture().examples;
    let resolveResponse!: (value: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise((resolve) => { resolveResponse = resolve; }));
    render(<UseCasePlayground examples={examples} />);
    await userEvent.click(screen.getByRole("button", { name: "Try online" }));
    await userEvent.click(screen.getByRole("button", { name: "edge input" }));
    resolveResponse(new Response(JSON.stringify(examples[0].response), { status: 200, headers: { "Content-Type": "application/json" } }));
    await waitFor(() => expect(screen.getByText("Previous verification")).toBeInTheDocument());
    expect(screen.queryByText(/Live response received/)).not.toBeInTheDocument();
  });
});

describe("use-case request lifecycle", () => {
  function pendingFetch() {
    return vi.spyOn(globalThis, "fetch").mockImplementation((_input, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
  }
  async function run() {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Try online" })); });
  }
  it("cancels on demand and aborts on unmount", async () => {
    const fetch = pendingFetch();
    const { unmount } = render(<UseCasePlayground examples={useCaseFixture().examples} />);
    await run();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancel" })); });
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(screen.getByText("Request cancelled.")).toBeInTheDocument();
    await run();
    unmount();
    expect(fetch.mock.calls[1][1]?.signal?.aborted).toBe(true);
  });
  it("uses its own twenty-second timeout and leaves the answer empty", async () => {
    vi.useFakeTimers();
    const fetch = pendingFetch();
    render(<UseCasePlayground examples={useCaseFixture().examples} />);
    await run();
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(fetch.mock.calls[0][1]?.signal?.reason).toBe("timeout");
    expect(screen.getByText("The request timed out after 20 seconds. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Ready when you are.")).toBeInTheDocument();
  });
  it("reports invalid response JSON without showing the saved answer", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{", { headers: { "Content-Type": "application/json" } }));
    render(<UseCasePlayground examples={useCaseFixture().examples} />);
    await run();
    expect(await screen.findByText("The gateway returned invalid JSON.")).toBeInTheDocument();
    expect(screen.getByText("Ready when you are.")).toBeInTheDocument();
  });
  it("copies exact result bytes with the use-case message", async () => {
    vi.stubGlobal("isSecureContext", true);
    const write = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    const examples = useCaseFixture().examples;
    render(<UseCasePlayground examples={examples} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy result" }));
    expect(await screen.findByText("Copied to clipboard.")).toBeInTheDocument();
    expect(write).toHaveBeenCalledWith(JSON.stringify(examples[0].response, null, 2));
  });
});
