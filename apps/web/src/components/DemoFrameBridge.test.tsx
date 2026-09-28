import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoFrameBridge } from "./DemoFrameBridge";

function mount() {
  const frame = document.createElement("iframe");
  frame.id = "test-frame";
  document.body.appendChild(frame);
  const post = vi.fn();
  Object.defineProperty(frame, "contentWindow", { value: { postMessage: post }, configurable: true });
  const view = render(<DemoFrameBridge frameId="test-frame" />);
  return { frame, post, view };
}

afterEach(() => {
  document.body.innerHTML = "";
  document.documentElement.dataset.theme = "light";
});

describe("DemoFrameBridge", () => {
  it("sends the theme and asks for a height on mount, on frame load and on theme changes", async () => {
    const { frame, post } = mount();
    expect(post).toHaveBeenCalledWith({ type: "typesafe-demo:theme", value: "light" }, "*");
    expect(post).toHaveBeenCalledWith({ type: "typesafe-demo:measure" }, "*");
    act(() => { frame.dispatchEvent(new Event("load")); });
    expect(post).toHaveBeenCalledTimes(4);
    document.documentElement.dataset.theme = "dark";
    await act(async () => { await Promise.resolve(); });
    expect(post).toHaveBeenLastCalledWith({ type: "typesafe-demo:theme", value: "dark" }, "*");
  });
  it("resizes only from messages sent by its own frame and clamps the height", () => {
    const { frame, post } = mount();
    const send = (source: unknown, data: unknown) => act(() => { window.dispatchEvent(new MessageEvent("message", { data, source: source as Window })); });
    send(window, { type: "typesafe-demo:height", height: 900 });
    expect(frame.style.height).toBe("");
    send(frame.contentWindow, { type: "typesafe-demo:height", height: 900.4 });
    expect(frame.style.height).toBe("901px");
    send(frame.contentWindow, { type: "typesafe-demo:height", height: 10 });
    expect(frame.style.height).toBe("120px");
    send(frame.contentWindow, { type: "typesafe-demo:height", height: 99999 });
    expect(frame.style.height).toBe("4000px");
    send(frame.contentWindow, { type: "typesafe-demo:height", height: "tall" });
    expect(frame.style.height).toBe("4000px");
    send(frame.contentWindow, { type: "typesafe-demo:ready" });
    expect(post).toHaveBeenLastCalledWith({ type: "typesafe-demo:theme", value: "light" }, "*");
  });
  it("does nothing without a frame", () => {
    expect(() => render(<DemoFrameBridge frameId="missing" />)).not.toThrow();
  });
});
