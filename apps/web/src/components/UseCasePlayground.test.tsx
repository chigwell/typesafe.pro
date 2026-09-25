import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UseCasePlayground } from "./UseCasePlayground";
import { useCaseFixture } from "@/test/use-case-fixture";
import { LANGUAGE_ORDER, LANGUAGES } from "@/lib/codegen";

afterEach(() => vi.restoreAllMocks());

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
