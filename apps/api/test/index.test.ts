import { describe, expect, it } from "vitest";
import worker from "../src/index";

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  return worker.fetch(
    new Request(`https://api.typesafe.pro${path}`, init),
    {},
    {} as ExecutionContext
  );
}

describe("typesafe-pro-api", () => {
  it("returns the hello world payload", async () => {
    const response = await fetchApi("/");

    await expect(response.json()).resolves.toEqual({
      ok: true,
      message: "Hello from api.typesafe.pro",
      service: "typesafe-pro-api"
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/json");
  });

  it("returns health status", async () => {
    const response = await fetchApi("/health");

    await expect(response.json()).resolves.toEqual({
      ok: true,
      status: "healthy"
    });
    expect(response.status).toBe(200);
  });

  it("returns JSON 404s", async () => {
    const response = await fetchApi("/missing");

    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "Not found"
    });
    expect(response.status).toBe(404);
  });
});
