import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Generations from "./Generations";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const generation = (id: number, count: number) => ({
  id,
  parameters: { width: 64, height: 96 },
  images: Array.from({ length: count }, (_, position) => ({
    id: id * 100 + position,
    position,
    url: `/images/${id}/${position}`,
  })),
});

it("supports variable counts, exclusive ratings, toggling and dislikes alone without writes", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [generation(1, 1), generation(2, 11)],
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<Generations projectId={1} />);
  await screen.findByAltText("候補画像 11");
  fireEvent.click(screen.getByRole("button", { name: "評価を確認" }));
  expect(screen.getByRole("alert").textContent).toContain("最低1枚");
  const card = within(screen.getByRole("article", { name: "画像 1" }));
  fireEvent.click(card.getByRole("button", { name: "好き" }));
  expect(
    card.getByRole("button", { name: "好き" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(card.getByRole("button", { name: "嫌い" }));
  expect(
    card.getByRole("button", { name: "好き" }).getAttribute("aria-pressed"),
  ).toBe("false");
  fireEvent.click(screen.getByRole("button", { name: "評価を確認" }));
  expect(screen.getByRole("status").textContent).toContain(
    "評価を確認しました",
  );
  fireEvent.click(card.getByRole("button", { name: "嫌い" }));
  expect(
    card.getByRole("button", { name: "未評価" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(card.getByRole("button", { name: "好き" }));
  fireEvent.click(card.getByRole("button", { name: "未評価" }));
  expect(screen.getByText("好き 0枚 · 嫌い 0枚 · 未評価 11枚")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("表示するGeneration"), {
    target: { value: "1" },
  });
  expect(screen.getAllByRole("img")).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledOnce();
});

it("clears drafts when unmounted and handles empty and failed retrieval with retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValue({ ok: true, json: async () => [generation(1, 1)] }),
  );
  let view = render(<Generations projectId={1} />);
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "再試行" }));
  await screen.findByText("保存済みのGenerationはまだありません。");
  view.unmount();
  view = render(<Generations projectId={1} />);
  fireEvent.click(await screen.findByRole("button", { name: "好き" }));
  view.unmount();
  render(<Generations projectId={1} />);
  expect(
    (await screen.findByRole("button", { name: "未評価" })).getAttribute(
      "aria-pressed",
    ),
  ).toBe("true");
});
