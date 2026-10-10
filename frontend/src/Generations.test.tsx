import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Generations from "./Generations";

beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const generation = (
  id: number,
  count: number,
  parent: number | null = null,
) => ({
  id,
  parent_id: parent,
  selection: parent ? { liked: [], disliked: [parent * 100] } : null,
  parameters: { width: 64, height: 96 },
  images: Array.from({ length: count }, (_, position) => ({
    id: id * 100 + position,
    position,
    url: `/images/${id}/${position}`,
  })),
});

it("reopens only the active ancestors and switches sibling snapshots", async () => {
  const branch = [
    generation(1, 1),
    generation(2, 1, 1),
    generation(3, 1, 2),
    { ...generation(4, 1, 1), selection: { liked: [100], disliked: [] } },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => branch }),
  );
  const view = render(<Generations projectId={1} />);
  await screen.findByRole("region", { name: "Generation #4の画像評価" });
  expect(
    screen.queryByRole("region", { name: "Generation #2の画像評価" }),
  ).toBeNull();
  let root = within(
    screen.getByRole("region", { name: "Generation #1の画像評価" }),
  );
  expect(
    root.getByRole("button", { name: "好き" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "枝 #2を開く" }));
  root = within(
    screen.getByRole("region", { name: "Generation #1の画像評価" }),
  );
  expect(
    root.getByRole("button", { name: "嫌い" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.change(screen.getByLabelText("表示するGeneration"), {
    target: { value: "3" },
  });
  expect(screen.getAllByRole("img")).toHaveLength(3);
  expect(screen.getByText(/表示中の経路: #1 → #2 → #3/)).toBeTruthy();
  view.unmount();
  render(<Generations projectId={1} />);
  await screen.findByRole("region", { name: "Generation #4の画像評価" });
  fireEvent.change(screen.getByLabelText("表示するGeneration"), {
    target: { value: "3" },
  });
  expect(screen.getAllByRole("img")).toHaveLength(3);
});

it("creates a sibling from a past ancestor and hides the previous branch", async () => {
  const original = [generation(1, 1), generation(2, 1, 1), generation(3, 1, 2)];
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => original })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 4 }) })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => [...original, generation(4, 1, 1)],
    });
  vi.stubGlobal("fetch", fetchMock);
  render(<Generations projectId={1} />);
  const root = within(
    await screen.findByRole("region", { name: "Generation #1の画像評価" }),
  );
  fireEvent.click(
    root.getByRole("button", { name: "評価を確定して次世代を生成" }),
  );
  await screen.findByRole("region", { name: "Generation #4の画像評価" });
  expect(
    screen.queryByRole("region", { name: "Generation #3の画像評価" }),
  ).toBeNull();
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).parent_id).toBe(1);
  fireEvent.change(screen.getByLabelText("表示するGeneration"), {
    target: { value: "3" },
  });
  expect(screen.getAllByRole("img")).toHaveLength(3);
});

it("submits a dislike snapshot once and appends the completed child", async () => {
  let resolve: (value: unknown) => void = () => {};
  const pending = new Promise((value) => {
    resolve = value;
  });
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => [generation(1, 2)] })
    .mockReturnValueOnce(pending)
    .mockResolvedValueOnce({
      ok: true,
      json: async () => [generation(1, 2), generation(2, 2, 1)],
    });
  vi.stubGlobal("fetch", fetchMock);
  render(<Generations projectId={1} registered />);
  fireEvent.click((await screen.findAllByRole("button", { name: "嫌い" }))[0]);
  const button = screen.getByRole("button", {
    name: "評価を確定して次世代を生成",
  });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
    parent_id: 1,
    selection: { liked: [], disliked: [100] },
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  resolve({ ok: true, json: async () => ({ id: 2 }) });
  await screen.findByRole("region", { name: "Generation #2の画像評価" });
  expect(screen.getAllByRole("img")).toHaveLength(4);
});

it("starts from the reference and retains ratings after a generation failure", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => [generation(1, 1)] })
    .mockResolvedValueOnce({ ok: false });
  vi.stubGlobal("fetch", fetchMock);
  render(<Generations projectId={1} registered />);
  fireEvent.click(
    await screen.findByRole("button", { name: "参考画像から候補を生成" }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "好き" }));
  fireEvent.click(
    screen.getByRole("button", { name: "評価を確定して次世代を生成" }),
  );
  await screen.findByRole("alert");
  expect(
    screen.getByRole("button", { name: "好き" }).getAttribute("aria-pressed"),
  ).toBe("true");
});

it("supports variable counts, exclusive ratings, toggling and dislikes alone without writes", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [generation(1, 1), generation(2, 11)],
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<Generations projectId={1} />);
  await screen.findByAltText("候補画像 11");
  fireEvent.click(
    screen.getByRole("button", { name: "評価を確定して次世代を生成" }),
  );
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
