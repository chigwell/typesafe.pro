import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminDashboard from "./AdminDashboard";

const sample = {
  at: 1700000000,
  cpu_percent: 42,
  memory: { percent: 60, used_bytes: 600000000, total_bytes: 1000000000 },
  disk: { percent: 35, used_bytes: 3500000000, total_bytes: 10000000000 },
  load: [0.5, 0.4, 0.3],
};
const system = {
  status: "ok",
  release: "abcdef123456",
  current: sample,
  history: [sample],
  redis: { ok: true, latency_ms: 2 },
  postgres: { ok: true, latency_ms: 3 },
  queue: {
    inflight: 1,
    max_inflight: 32,
    pending: { anonymous: 2 },
    body_bytes: 0,
  },
  telemetry: {
    dropped_errors: 0,
    dropped_activity: 0,
    last_flush_at: 1700000000,
  },
};
const summary = {
  window: "24h",
  from: 0,
  to: 1700000000,
  totals: {
    requests: 120,
    unique_ips: 26,
    errors: 4,
    rate_limited: 2,
    usage_tokens: 500,
    estimated_tokens: 700,
    usage_reported_requests: 100,
    upstream_requests: 118,
    avg_duration_ms: 10,
    avg_upstream_ms: 8,
  },
  tiers: [{ name: "anonymous", requests: 120 }],
  masters: [{ name: "1", requests: 118, avg_upstream_ms: 8 }],
  paths: [{ name: "/v1/systemone", requests: 120 }],
  status_codes: { "200": 116, "502": 4 },
  status_classes: { "2xx": 116 },
  upstream_statuses: { "200": 114 },
  telemetry: { dropped: 0, last_flush_at: 1700000000 },
};

function mockApi({
  session = true,
  summaryStatus = 200,
  seoStatus = 200,
  generationStatus = "prepared",
}: { session?: boolean; summaryStatus?: number; seoStatus?: number; generationStatus?: "prepared" | "failed" | "skipped" } = {}) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, options) => {
      const url = new URL(String(input));
      const reply = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), { status });
      if (url.pathname.endsWith("/auth/session"))
        return reply({ authenticated: session }, session ? 200 : 401);
      if (
        url.pathname.endsWith("/auth/login") ||
        url.pathname.endsWith("/auth/logout")
      )
        return reply({ authenticated: true });
      if (url.pathname.endsWith("/system")) return reply(system);
      if (url.pathname.includes("/seo/")) {
        if (seoStatus !== 200) return reply({ detail: "Generated pages unavailable" }, seoStatus);
        const run = {
          run_id: "run-123", source_sha: "a".repeat(40), status: "published",
          generation_status: generationStatus,
          reason: null, started_at: "2026-09-25T11:00:00Z",
          finished_at: "2026-09-25T11:05:00Z", published_at: "2026-09-25T11:10:00Z",
          duration_seconds: 300, seed: 42, rounds: 2, api_calls: 75,
          input_tokens: 12000, output_tokens: 2500, generated_count: 3,
          rejected_count: 1, rejections: { duplicate: 1 }, catalog_hash: "b".repeat(64),
        };
        if (url.pathname.endsWith("/seo/summary")) return reply({
          total_pages: 27, added_last_deploy: 3,
          latest_publication: { published_at: run.published_at }, latest_attempt: run,
          totals: { runs: 4, api_calls: 200, input_tokens: 30000, output_tokens: 5000 },
        });
        const page = Number(url.searchParams.get("page") || 1);
        return reply({
          items: url.pathname.endsWith("/pages") ? [{
            slug: `support-${page}`, title: `Support routing ${page}`, path: `/use-cases/support-${page}`,
            created_at: run.started_at, updated_at: run.finished_at,
            published_at: run.published_at, unique_visitors: 19, total_hits: 31,
          }] : [run],
          total: 27, page, page_size: 25,
        });
      }
      if (url.pathname.endsWith("/summary"))
        return reply(
          summaryStatus === 200 ? summary : { detail: "Activity unavailable" },
          summaryStatus,
        );
      const page = Number(url.searchParams.get("page") || 1);
      if (url.pathname.endsWith("/ip-activity"))
        return reply({
          items: [
            {
              ip: `203.0.113.${page}`,
              requests: 12,
              errors: 1,
              last_seen: 1700000000,
            },
          ],
          total: 26,
          page,
          page_size: 25,
        });
      if (url.pathname.endsWith("/page-views"))
        return reply({
          items: [
            {
              date: "2026-09-25",
              path: "/",
              unique_visitors: 9,
              total_hits: 14,
              first_seen_at: "2026-09-25T10:00:00Z",
              last_seen_at: "2026-09-25T12:00:00Z",
            },
          ],
          total: 26,
          page,
          page_size: 25,
        });
      if (url.pathname.endsWith("/errors"))
        return reply({
          items: [
            {
              id: String(page),
              created_at: "2026-09-21T12:00:00Z",
              request_id: `request-${page}`,
              client_ip: "203.0.113.1",
              client_tier: "anonymous",
              method: "POST",
              path: "/v1/systemone",
              status: 502,
              error_code: "upstream_error",
              duration_ms: 33,
              upstream_status: 502,
              master_key_id: "1",
              error_detail: "Unavailable",
              raw_response: "[redacted]",
              response_truncated: false,
            },
          ],
          total: 26,
          page,
          page_size: 25,
        });
      throw new Error(`Unexpected request ${input} ${options?.method}`);
    });
}

afterEach(() => vi.restoreAllMocks());

describe("AdminDashboard", () => {
  it("signs in with credentials and renders system and activity", async () => {
    const fetch = mockApi({ session: false });
    const user = userEvent.setup();
    render(<AdminDashboard />);
    await user.type(await screen.findByLabelText("Password"), "admin-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("42%");
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
    expect(screen.getByText("Usage tokens")).toBeInTheDocument();
    expect(screen.getByText("Page views")).toBeInTheDocument();
    expect(screen.getByText("Unique visitors")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    const login = fetch.mock.calls.find(([url]) =>
      String(url).endsWith("/auth/login"),
    );
    expect(login?.[1]).toMatchObject({
      credentials: "include",
      method: "POST",
      body: JSON.stringify({ password: "admin-password" }),
    });
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByLabelText("Password")).toHaveValue("");
  });

  it("returns to login and clears private data on 401", async () => {
    mockApi({ summaryStatus: 401 });
    render(<AdminDashboard />);
    expect(
      await screen.findByText("Session expired. Sign in again."),
    ).toBeInTheDocument();
    expect(screen.queryByText("IP activity")).not.toBeInTheDocument();
  });

  it("paginates IPs, page views and errors and resets IP page when the window changes", async () => {
    const fetch = mockApi();
    const user = userEvent.setup();
    render(<AdminDashboard />);
    await screen.findByText("42%");
    await user.click(screen.getByRole("button", { name: "Next IP page" }));
    await screen.findByText("203.0.113.2");
    expect(
      fetch.mock.calls.some(([url]) =>
        String(url).includes("ip-activity?window=24h&page=2"),
      ),
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: "Next errors page" }));
    await screen.findByText("request-2");
    expect(
      fetch.mock.calls.some(([url]) => String(url).includes("errors?page=2")),
    ).toBe(true);
    await user.click(
      screen.getByRole("button", { name: "Next page views page" }),
    );
    expect(
      fetch.mock.calls.some(([url]) =>
        String(url).includes("page-views?from=") && String(url).includes("page=2"),
      ),
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: "7d" }));
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) =>
          String(url).includes("ip-activity?window=7d&page=1"),
        ),
      ).toBe(true),
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Error status" }),
      "502",
    );
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) =>
          String(url).includes("errors?page=1&page_size=25&status=502"),
        ),
      ).toBe(true),
    );
  });

  it("shows unavailable activity without hiding working system metrics", async () => {
    mockApi({ summaryStatus: 503 });
    render(<AdminDashboard />);
    expect(
      await screen.findByText("Activity: Activity unavailable"),
    ).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("paginates generated pages and history and shows publication counts", async () => {
    const fetch = mockApi();
    const user = userEvent.setup();
    render(<AdminDashboard />);
    await screen.findByRole("link", { name: "Support routing 1" });
    expect(screen.getByText("Added in last successful deploy")).toBeInTheDocument();
    expect(screen.getAllByText("published")).toHaveLength(2);
    expect(screen.getAllByText("duplicate: 1")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Next generated pages page" }));
    await screen.findByRole("link", { name: "Support routing 2" });
    await user.click(screen.getByRole("button", { name: "Next generation history page" }));
    expect(fetch.mock.calls.some(([url]) => String(url).includes("/seo/runs?page=2"))).toBe(true);
  });

  it("keeps the dashboard working when SEO endpoints are unavailable", async () => {
    mockApi({ seoStatus: 503 });
    render(<AdminDashboard />);
    await screen.findByText("Generated pages: Generated pages unavailable");
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Page views")).toBeInTheDocument();
  });

  it.each(["failed", "skipped"] as const)("preserves a %s generation result after publishing the existing catalog", async (generationStatus) => {
    mockApi({ generationStatus });
    render(<AdminDashboard />);
    await screen.findByRole("link", { name: "Support routing 1" });
    expect(screen.getAllByText(`Generation ${generationStatus}; deployment confirmed.`)).toHaveLength(2);
  });

  it("honors Retry-After on login lockout", async () => {
    const fetch = mockApi({ session: false });
    const original = fetch.getMockImplementation()!;
    fetch.mockImplementation((input, options) =>
      String(input).endsWith("/auth/login")
        ? Promise.resolve(
            new Response(
              JSON.stringify({ detail: "Too many login attempts" }),
              { status: 429, headers: { "Retry-After": "60" } },
            ),
          )
        : original(input, options),
    );
    const user = userEvent.setup();
    render(<AdminDashboard />);
    await user.type(await screen.findByLabelText("Password"), "bad-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Too many login attempts");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    expect(screen.getByText(/Try again in/)).toBeInTheDocument();
  });
});
