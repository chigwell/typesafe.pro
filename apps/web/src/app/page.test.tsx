import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminPage from "./admin/page";
import Page from "./page";

afterEach(() => vi.restoreAllMocks());

describe("public page view tracking", () => {
  it("tracks the public home page", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    Object.defineProperty(window.navigator, "sendBeacon", {
      configurable: true,
      value: undefined,
    });

    render(<Page />);

    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([url, options]) =>
            String(url).endsWith("/analytics/view") &&
            options?.method === "POST" &&
            options?.body === JSON.stringify({ path: "/" }) &&
            options.credentials === "omit" &&
            (options.headers as Record<string, string>)["Content-Type"] ===
              "text/plain;charset=UTF-8",
        ),
      ).toBe(true),
    );
  });

  it("does not track the admin page", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Admin session required" }), {
          status: 401,
        }),
      );
    Object.defineProperty(window.navigator, "sendBeacon", {
      configurable: true,
      value: undefined,
    });

    render(<AdminPage />);

    await screen.findByLabelText("Password");
    expect(
      fetch.mock.calls.some(([url]) => String(url).endsWith("/analytics/view")),
    ).toBe(false);
  });
});
