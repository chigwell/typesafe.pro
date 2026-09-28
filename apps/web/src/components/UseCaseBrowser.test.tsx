import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { queryHref, UseCaseBrowser } from "./UseCaseBrowser";

const card = (slug: string) => ({ slug, title: `Title ${slug}`, summary: "Summary", industry: "Support", audience: "Teams", task_type: "routing", question_types: ["noul" as const], has_demo: false, category: null, tags: [], published_at: null, updated_at: "2026-09-25T12:00:00Z" });
const facets = { total: 2, categories: [{ slug: "routing-triage", name: "Routing & triage", description: "", count: 2 }], tags: [{ slug: "support", name: "support", count: 2 }] };
const initial = { items: [card("first")], total: 1, page: 1, page_size: 24 };
const blank = { q: "", category: "", tag: "", page: 1 };

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("UseCaseBrowser", () => {
  it("shows server results without fetching", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<UseCaseBrowser initial={initial} facets={facets} query={blank} />);
    expect(screen.getByText("Title first")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("debounces search, shows skeletons, syncs the URL and renders results", async () => {
    let release: (value: Response) => void = () => {};
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    const { container } = render(<UseCaseBrowser initial={initial} facets={facets} query={blank} debounceMs={20} />);
    await userEvent.type(screen.getByRole("searchbox"), "refund");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain("/v1/use-cases?q=refund&page_size=24");
    expect(container.querySelectorAll(".is-skeleton").length).toBeGreaterThan(0);
    expect(window.location.search).toBe("?q=refund");
    await act(async () => release(respond({ items: [card("refund-case")], total: 1, page: 1, page_size: 24 })));
    expect(await screen.findByText("Title refund-case")).toBeInTheDocument();
    expect(screen.getByText(/1 use case found/)).toBeInTheDocument();
  });
  it("aborts a stale request when the filter changes again", async () => {
    const signals: AbortSignal[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => {
      signals.push(init!.signal!);
      return new Promise(() => {});
    });
    render(<UseCaseBrowser initial={initial} facets={facets} query={blank} />);
    await userEvent.selectOptions(screen.getByRole("combobox"), "routing-triage");
    await userEvent.click(screen.getByRole("button", { name: "support" }));
    await waitFor(() => expect(signals.length).toBe(2));
    expect(signals[0].aborted).toBe(true);
    expect(window.location.search).toBe("?category=routing-triage&tag=support");
  });
  it("offers a retry after an error", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(respond({ detail: "down" }, 503)).mockResolvedValueOnce(respond(initial));
    render(<UseCaseBrowser initial={null} facets={null} query={blank} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Title first")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("builds canonical listing hrefs", () => {
    expect(queryHref(blank)).toBe("/use-cases");
    expect(queryHref({ q: " tone ", category: "", tag: "support", page: 2 })).toBe("/use-cases?q=tone&tag=support&page=2");
  });
});
