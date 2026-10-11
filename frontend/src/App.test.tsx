import {
  act,
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
const optionsData = {
  model_whitelist: ["boleromixIllustrious_v402.safetensors"],
  fixed_sizes: [
    { width: 1024, height: 1024 },
    { width: 768, height: 1344 },
    { width: 1344, height: 768 },
  ],
  extra_sizes: [],
};
function stubFetch(handler: (url: string, options?: RequestInit) => unknown) {
  vi.stubGlobal("fetch", (url: string, options?: RequestInit) => {
    if (url === "/api/settings") return Promise.resolve(response(optionsData));
    if (url === "/api/settings/models")
      return Promise.resolve(response({ models: optionsData.model_whitelist }));
    return handler(url, options);
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "#/");
  closeEvents.mockClear();
  eventSource.mockClear();
  vi.stubGlobal("EventSource", eventSource);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("opens the lifetime stream and closes it when unmounted", () => {
  stubFetch(vi.fn().mockImplementation(() => new Promise(() => {})));
  const view = render(<App />);
  expect(eventSource).toHaveBeenCalledWith("/api/events");
  view.unmount();
  expect(closeEvents).toHaveBeenCalledOnce();
});

it("renders the UI and reports API connection", async () => {
  const fetchMock = vi.fn(async (url) =>
    response(url === "/api/health" ? { status: "ok" } : []),
  );
  stubFetch(fetchMock);
  render(<App />);
  expect(
    screen.getByRole("heading", { name: "LoopImageGenerator V2" }).textContent,
  ).toBe("LoopImageGenerator V2");
  const indicator = await screen.findByRole("status", {
    name: "APIに接続しました",
  });
  expect(indicator.getAttribute("data-state")).toBe("connected");
  expect(indicator.textContent).toBe("API:");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
});

it("reports an unavailable API", async () => {
  stubFetch(vi.fn().mockResolvedValue({ ok: false, status: 503 }));
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<App />);
    expect(
      (
        await screen.findByRole("status", {
          name: "APIに接続できません。起動状態を確認してください。",
        })
      ).getAttribute("data-state"),
    ).toBe("disconnected");
    expect(await screen.findByRole("alert")).toBeTruthy();
  } finally {
    log.mockRestore();
  }
});

it("creates a project, then opens another saved project", async () => {
  const fetchMock = vi.fn(async (url, options) => {
    if (String(url).endsWith("/generations")) return response([]);
    if (url === "/api/health") return response({ status: "ok" });
    if (options?.method === "POST") return response(project(2, "海"));
    if (url === "/api/projects/2") return response(project(2, "海"));
    if (url === "/api/projects/1") return response(project(1, "山"));
    return response([project(1, "山")]);
  });
  stubFetch(fetchMock);
  render(<App />);
  await screen.findByRole("button", { name: "山（#1）を開く" });
  fireEvent.click(screen.getByRole("link", { name: "新規プロジェクト" }));
  await screen.findByLabelText("プロジェクト名");
  fireEvent.change(screen.getByLabelText("プロジェクト名"), {
    target: { value: " 海 " },
  });
  fireEvent.click(screen.getByRole("button", { name: "作成する" }));
  expect(await screen.findByRole("heading", { name: "海" })).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "海",
        generation_config: {
          checkpoint: optionsData.model_whitelist[0],
          width: 1024,
          height: 1024,
        },
      }),
    }),
  );
  expect(screen.queryByLabelText("プロジェクト名")).toBeNull();
  expect(window.location.hash).toBe("#/projects/2");
  fireEvent.click(screen.getByRole("link", { name: "LoopImageGenerator V2" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "山（#1）を開く" }),
  );
  expect(await screen.findByRole("heading", { name: "山" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "海" })).toBeNull();
});

it("keeps the newest project selection when responses arrive out of order", async () => {
  let resolveFirst: (value: ReturnType<typeof response>) => void = () => {};
  stubFetch(
    vi.fn((url) => {
      if (String(url).endsWith("/generations"))
        return Promise.resolve(response([]));
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
  fireEvent.click(screen.getByRole("link", { name: "LoopImageGenerator V2" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "海（#2）を開く" }),
  );
  await screen.findByRole("heading", { name: "海" });
  resolveFirst(response(project(1, "山")));
  await waitFor(() =>
    expect(screen.queryByRole("heading", { name: "山" })).toBeNull(),
  );
});

it("reports creation failure and allows retry without adding a project", async () => {
  stubFetch(
    vi.fn(async (url, options) => {
      if (url === "/api/health") return response({ status: "ok" });
      if (options?.method === "POST") return { ok: false, status: 500 };
      return response([]);
    }),
  );
  render(<App />);
  fireEvent.click(screen.getByRole("link", { name: "新規プロジェクト" }));
  await screen.findByLabelText("プロジェクト名");
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

it("opens project URLs directly and navigates to empty settings without closing SSE", async () => {
  window.history.replaceState(null, "", "#/projects/1");
  stubFetch(
    vi.fn(async (url) => {
      if (url === "/api/health") return response({ status: "ok" });
      if (url === "/api/projects/1") return response(project(1, "山"));
      return response([]);
    }),
  );
  render(<App />);
  await screen.findByRole("heading", { name: "山" });
  expect(screen.queryByLabelText("プロジェクト名")).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "設定" }));
  expect(screen.getByRole("heading", { name: "設定" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "山" })).toBeNull();
  expect(closeEvents).not.toHaveBeenCalled();
  window.history.replaceState(null, "", "#/projects/1");
  fireEvent.popState(window);
  await screen.findByRole("heading", { name: "山" });
  expect(eventSource).toHaveBeenCalledOnce();
});

it("confirms deletion, handles cancellation and removes only the deleted project", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const fetchMock = vi.fn(async (url, options) => {
    if (url === "/api/health") return response({ status: "ok" });
    if (options?.method === "DELETE") return { ok: true, status: 204 };
    return response([project(1, "山"), project(2, "海")]);
  });
  stubFetch(fetchMock);
  render(<App />);
  const button = await screen.findByRole("button", { name: "山（#1）を削除" });
  fireEvent.click(button);
  expect(fetchMock).not.toHaveBeenCalledWith("/api/projects/1", {
    method: "DELETE",
  });
  confirm.mockReturnValue(true);
  fireEvent.click(button);
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "山（#1）を開く" })).toBeNull(),
  );
  expect(screen.getByRole("button", { name: "海（#2）を開く" })).toBeTruthy();
  confirm.mockRestore();
});

it("keeps a project listed when deletion is rejected during generation", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  stubFetch(
    vi.fn(async (url, options) => {
      if (url === "/api/health") return response({ status: "ok" });
      if (options?.method === "DELETE") return { ok: false, status: 409 };
      return response([project(1, "山")]);
    }),
  );
  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "山（#1）を削除" }),
  );
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "山（#1）を開く" })).toBeTruthy();
  confirm.mockRestore();
});

it("shows checking, disconnect and reconnection states in the compact API indicator", async () => {
  stubFetch(vi.fn(() => new Promise(() => {})));
  render(<App />);
  const indicator = screen.getByRole("status", {
    name: "接続を確認しています…",
  });
  expect(indicator.getAttribute("data-state")).toBe("checking");
  const events = eventSource.mock.results[0].value as unknown as {
    onopen: () => void;
    onerror: () => void;
  };
  act(() => events.onopen());
  expect(indicator.getAttribute("data-state")).toBe("connected");
  act(() => events.onerror());
  expect(indicator.getAttribute("data-state")).toBe("disconnected");
  expect(indicator.getAttribute("aria-label")).toContain("再接続");
  act(() => events.onopen());
  expect(indicator.getAttribute("data-state")).toBe("connected");
});
