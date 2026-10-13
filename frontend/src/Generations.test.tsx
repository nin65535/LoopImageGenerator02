import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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

it("recovers a running generation after reload without submitting again", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ "X-Generation-Running": "true" }),
      json: async () => [],
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        running: true,
        percent: 50,
        completed: 5,
        elapsed_seconds: 120,
        stage: "generating",
        generated: 10,
        image_count: 10,
      }),
    })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ running: false }) })
    .mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ "X-Generation-Running": "false" }),
      json: async () => [generation(1, 1)],
    });
  vi.stubGlobal("fetch", fetchMock);
  render(<Generations projectId={1} registered />);
  await screen.findByRole("status");
  expect(screen.getByRole("progressbar").hasAttribute("aria-valuenow")).toBe(
    true,
  );
  expect(
    (
      screen.getByRole("button", {
        name: "参考画像から候補を生成",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await waitFor(
    () =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("50"),
    { timeout: 2500 },
  );
  expect(screen.getByRole("status").textContent).toContain("経過 120秒");
  await screen.findByRole(
    "region",
    { name: "Generation #1の画像評価" },
    { timeout: 2500 },
  );
  expect(fetchMock.mock.calls.every((call) => call[1]?.method !== "POST")).toBe(
    true,
  );
  expect(screen.queryByRole("progressbar")).toBeNull();
});

it("renders a long ancestor chain and retains access to every generation", async () => {
  const chain = Array.from({ length: 500 }, (_, i) =>
    generation(i + 1, 1, i || null),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => chain }),
  );
  const { container } = render(<Generations projectId={1} />);
  await waitFor(() =>
    expect(container.querySelector('[data-generation="500"]')).toBeTruthy(),
  );
  expect(container.querySelectorAll("img")).toHaveLength(500);
  fireEvent.change(screen.getByLabelText("表示するGeneration"), {
    target: { value: "1" },
  });
  expect(container.querySelectorAll("img")).toHaveLength(1);
});

it("shows confirmed percentage and tagging count while a POST is pending", async () => {
  let finish!: (response: unknown) => void;
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, options?: RequestInit) => {
      if (options?.method === "POST") return pending;
      if (url.endsWith("generation-status"))
        return Promise.resolve({
          ok: true,
          json: async () => ({
            running: true,
            percent: 40,
            stage: "tagging",
            generated: 10,
            tagged: 4,
            completed: 4,
            elapsed_seconds: 37,
            image_count: 10,
          }),
        });
      return Promise.resolve({ ok: true, json: async () => [] });
    }),
  );
  render(<Generations projectId={1} registered />);
  fireEvent.click(
    await screen.findByRole("button", { name: "参考画像から候補を生成" }),
  );
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
    "0",
  );
  await waitFor(
    () =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("40"),
    { timeout: 2500 },
  );
  expect(screen.getByRole("status").textContent).toContain("タグ付け 4/10枚");
  expect(screen.getByRole("status").textContent).toContain("完了 4/10枚");
  expect(screen.getByRole("status").textContent).toContain("経過 37秒");
  expect(
    (screen.getByRole("progressbar").firstChild as HTMLElement).style.width,
  ).toBe("40%");
  finish({ ok: true, json: async () => ({ id: 1 }) });
  await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull());
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
  const breadcrumbs = within(
    screen.getByRole("navigation", { name: "Generationの祖先経路" }),
  );
  expect(
    breadcrumbs
      .getAllByRole("listitem")
      .map((item) => item.textContent?.replace("›", "")),
  ).toEqual(["Generation #1", "Generation #2", "Generation #3"]);
  expect(
    breadcrumbs.getByText("Generation #3").getAttribute("aria-current"),
  ).toBe("page");
  fireEvent.click(breadcrumbs.getByRole("button", { name: "Generation #2" }));
  expect(screen.getAllByRole("img")).toHaveLength(2);
  expect(
    screen.queryByRole("region", { name: "Generation #3の画像評価" }),
  ).toBeNull();
  view.unmount();
  render(<Generations projectId={1} />);
  await screen.findByRole("region", { name: "Generation #4の画像評価" });
  fireEvent.change(screen.getByLabelText("表示するGeneration"), {
    target: { value: "3" },
  });
  expect(screen.getAllByRole("img")).toHaveLength(3);
});

it("starts carried liked images unrated in the child and allows rating them again", async () => {
  const root = generation(1, 1);
  const child = {
    ...generation(2, 2, 1),
    parameters: { width: 64, height: 96, carried_images: [{ position: 1 }] },
    selection: { liked: [100], disliked: [] },
  };
  child.images[1].url = root.images[0].url;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => [root, child] }),
  );
  render(<Generations projectId={1} />);
  const leaf = within(
    await screen.findByRole("region", { name: "Generation #2の画像評価" }),
  );
  expect(
    leaf
      .getAllByRole("button", { name: "未評価" })
      .every((button) => button.getAttribute("aria-pressed") === "true"),
  ).toBe(true);
  const copied = within(leaf.getByRole("article", { name: "画像 2" }));
  expect(leaf.getAllByRole("article")[0].getAttribute("aria-label")).toBe(
    "画像 2",
  );
  fireEvent.click(copied.getByRole("button", { name: "好き" }));
  expect(
    copied.getByRole("button", { name: "好き" }).getAttribute("aria-pressed"),
  ).toBe("true");
  expect(
    within(screen.getByRole("region", { name: "Generation #1の画像評価" }))
      .getByRole("button", { name: "好き" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
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
