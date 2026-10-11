import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import CreateProjectPage from "./CreateProjectPage";
import SettingsPage from "./SettingsPage";

const defaults = {
  model_whitelist: ["model-a"],
  fixed_sizes: [
    { width: 1024, height: 1024 },
    { width: 768, height: 1344 },
    { width: 1344, height: 768 },
  ],
  extra_sizes: [{ width: 640, height: 960 }],
};
const response = (data: unknown) => ({ ok: true, json: async () => data });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows only available whitelisted models and submits the selected preset", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) =>
      response(
        url === "/api/settings" ? defaults : { models: ["model-a", "model-b"] },
      ),
    ),
  );
  const create = vi.fn().mockResolvedValue(undefined);
  render(<CreateProjectPage busy={false} onCreate={create} />);
  await screen.findByLabelText("モデル");
  expect(
    screen.getByLabelText("モデル").querySelectorAll("option"),
  ).toHaveLength(1);
  expect(
    screen.getByLabelText("画像サイズ").querySelectorAll("option"),
  ).toHaveLength(4);
  fireEvent.change(screen.getByLabelText("プロジェクト名"), {
    target: { value: " test " },
  });
  fireEvent.change(screen.getByLabelText("画像サイズ"), {
    target: { value: "768x1344" },
  });
  fireEvent.click(screen.getByRole("button", { name: "作成する" }));
  expect(create).toHaveBeenCalledWith("test", {
    checkpoint: "model-a",
    width: 768,
    height: 1344,
  });
});

it("blocks creation when no whitelisted model exists and reports offline inventory", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) =>
      response(url === "/api/settings" ? defaults : { models: [] }),
    ),
  );
  const create = vi.fn();
  const view = render(<CreateProjectPage busy={false} onCreate={create} />);
  await screen.findByRole("alert");
  expect(
    (screen.getByRole("button", { name: "作成する" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  view.unmount();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
  render(<CreateProjectPage busy={false} onCreate={create} />);
  expect((await screen.findByRole("alert")).textContent).toContain("ComfyUI");
  expect(create).not.toHaveBeenCalled();
});

it("edits and persists whitelist and extra sizes, keeps fixed presets and rejects duplicates", async () => {
  const fetchMock = vi.fn(async (url, options) => {
    if (options?.method === "PUT") return response({});
    return response(
      url === "/api/settings" ? defaults : { models: ["model-a", "model-b"] },
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<SettingsPage />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "model-b" }));
  fireEvent.change(screen.getByLabelText("幅"), { target: { value: "1024" } });
  fireEvent.change(screen.getByLabelText("高さ"), {
    target: { value: "1024" },
  });
  fireEvent.click(screen.getByRole("button", { name: "サイズを追加" }));
  expect(screen.getByRole("alert").textContent).toContain("重複");
  fireEvent.change(screen.getByLabelText("幅"), { target: { value: "896" } });
  fireEvent.change(screen.getByLabelText("高さ"), {
    target: { value: "1152" },
  });
  fireEvent.click(screen.getByRole("button", { name: "サイズを追加" }));
  expect(
    screen.queryByRole("button", { name: "1024 × 1024を削除" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "640 × 960を削除" }));
  fireEvent.click(screen.getByRole("button", { name: "設定を保存" }));
  await waitFor(() =>
    expect(screen.getByRole("status").textContent).toBe("設定を保存しました。"),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/settings",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({
        model_whitelist: ["model-a", "model-b"],
        extra_sizes: [{ width: 896, height: 1152 }],
      }),
    }),
  );
});
