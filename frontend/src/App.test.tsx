import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("renders the React UI and reports API connection", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  expect(screen.getByRole("heading").textContent).toBe("LoopImageGenerator V2");
  expect(await screen.findByText("APIに接続しました")).toBeTruthy();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
});

it("reports an unavailable API", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<App />);
    expect(
      await screen.findByText(
        "APIに接続できません。起動状態を確認してください。",
      ),
    ).toBeTruthy();
  } finally {
    log.mockRestore();
  }
});
