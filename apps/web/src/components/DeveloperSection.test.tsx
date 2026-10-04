import { act, fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PRESETS } from "@/lib/presets";
import { requestFor } from "@/lib/playground";
import { makeCode } from "@/lib/codegen";
import { DeveloperSection } from "./DeveloperSection";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("developer code presentation", () => {
  const request = requestFor(PRESETS[0]);
  it("renders complete highlighted code in initial HTML", () => {
    const html = renderToString(<DeveloperSection request={request} valid onToast={vi.fn()} />);
    expect(html).toContain("urllib");
    expect(html).toContain("token-keyword");
    expect(html).toContain("line-number");
    expect(html).not.toContain("typing-cursor");
  });
  it("keeps copying full code during animation and cancels animation on replacement/unmount", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: false }));
    vi.stubGlobal("isSecureContext", true);
    const requestFrame = vi.spyOn(globalThis, "requestAnimationFrame").mockReturnValue(17);
    const cancelFrame = vi.spyOn(globalThis, "cancelAnimationFrame");
    const write = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    const toast = vi.fn();
    const { container, rerender, unmount } = render(<DeveloperSection request={request} valid onToast={toast} />);
    expect(container.querySelector(".typing-cursor")).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy" })); });
    expect(write).toHaveBeenCalledWith(makeCode("python", request));
    expect(toast).toHaveBeenCalledWith("Complete code copied");
    rerender(<DeveloperSection request={{ ...request, state: "Another state" }} valid onToast={toast} />);
    expect(cancelFrame).toHaveBeenCalledWith(17);
    unmount();
    expect(cancelFrame).toHaveBeenCalledTimes(2);
    expect(requestFrame).toHaveBeenCalledTimes(2);
  });
});
