import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";

const closeEvents = vi.fn();
const eventSource = vi.fn(function () {
  return { close: closeEvents };
});
const project = (id: number, name: string) => ({
  id,
  name,
  initial_image_path: null,
  created_at: "2026-10-10T00:00:00Z",
  updated_at: "2026-10-10T00:00:00Z",
  generation_count: 0,
});
const response = (data: unknown) => ({ ok: true, json: async () => data });

beforeEach(() => {
  closeEvents.mockClear();
  eventSource.mockClear();
  vi.stubGlobal("EventSource", eventSource);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("opens the lifetime stream and closes it when unmounted", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => new Promise(() => {})),
  );
  const view = render(<App />);
  expect(eventSource).toHaveBeenCalledWith("/api/events");
  view.unmount();
  expect(closeEvents).toHaveBeenCalledOnce();
});

it("renders the UI and reports API connection", async () => {
  const fetchMock = vi.fn(async (url) =>
    response(url === "/api/health" ? { status: "ok" } : []),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  expect(
    screen.getByRole("heading", { name: "LoopImageGenerator V2" }).textContent,
  ).toBe("LoopImageGenerator V2");
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
    expect(await screen.findByRole("alert")).toBeTruthy();
  } finally {
    log.mockRestore();
  }
});

it("creates a project, then opens another saved project", async () => {
  const fetchMock = vi.fn(async (url, options) => {
    if (url === "/api/health") return response({ status: "ok" });
    if (options?.method === "POST") return response(project(2, "海"));
    if (url === "/api/projects/1") return response(project(1, "山"));
    return response([project(1, "山")]);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  await screen.findByRole("button", { name: "山（#1）を開く" });
  fireEvent.change(screen.getByLabelText("プロジェクト名"), {
    target: { value: " 海 " },
  });
  fireEvent.click(screen.getByRole("button", { name: "作成する" }));
  expect(await screen.findByRole("heading", { name: "海" })).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects",
    expect.objectContaining({ method: "POST", body: '{"name":"海"}' }),
  );
  fireEvent.click(screen.getByRole("button", { name: "山（#1）を開く" }));
  expect(await screen.findByRole("heading", { name: "山" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "海" })).toBeNull();
});

it("keeps the newest project selection when responses arrive out of order", async () => {
  let resolveFirst: (value: ReturnType<typeof response>) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn((url) => {
      if (url === "/api/health")
        return Promise.resolve(response({ status: "ok" }));
      if (url === "/api/projects")
        return Promise.resolve(response([project(1, "山"), project(2, "海")]));
      if (url === "/api/projects/1")
        return new Promise((resolve) => {
          resolveFirst = resolve;
        });
      return Promise.resolve(response(project(2, "海")));
    }),
  );
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "山（#1）を開く" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "海（#2）を開く" }));
  await screen.findByRole("heading", { name: "海" });
  resolveFirst(response(project(1, "山")));
  await waitFor(() =>
    expect(screen.queryByRole("heading", { name: "山" })).toBeNull(),
  );
});

it("reports creation failure and allows retry without adding a project", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, options) => {
      if (url === "/api/health") return response({ status: "ok" });
      if (options?.method === "POST") return { ok: false, status: 500 };
      return response([]);
    }),
  );
  render(<App />);
  fireEvent.change(screen.getByLabelText("プロジェクト名"), {
    target: { value: "海" },
  });
  fireEvent.click(screen.getByRole("button", { name: "作成する" }));
  await screen.findByRole("alert");
  expect(
    (screen.getByRole("button", { name: "作成する" }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
  expect(screen.queryByRole("heading", { name: "海" })).toBeNull();
});
