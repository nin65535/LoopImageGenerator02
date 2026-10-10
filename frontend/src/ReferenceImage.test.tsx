import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ReferenceImage from "./ReferenceImage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("uploads a selected file and returns the saved project", async () => {
  const saved = { id: 1, initial_image_path: "references/test.png" };
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => saved });
  vi.stubGlobal("fetch", fetch);
  const onSaved = vi.fn();
  render(<ReferenceImage projectId={1} registered={false} onSaved={onSaved} />);
  const file = new File(["image"], "../../test.png", { type: "image/png" });
  fireEvent.change(screen.getByLabelText("参考画像を選択"), {
    target: { files: [file] },
  });
  await vi.waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
  expect(fetch).toHaveBeenCalledWith("/api/projects/1/initial-image", {
    method: "PUT",
    body: file,
  });
});

it("accepts a drop and shows server errors for retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "画像が破損しています。" }),
    }),
  );
  const saved = vi.fn();
  render(<ReferenceImage projectId={2} registered={false} onSaved={saved} />);
  fireEvent.drop(screen.getByText(/参考画像をここにドロップ/).parentElement!, {
    dataTransfer: { files: [new File(["bad"], "bad.png")] },
  });
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "画像が破損しています。",
  );
  expect(saved).not.toHaveBeenCalled();
  expect(
    (screen.getByLabelText("参考画像を選択") as HTMLInputElement).disabled,
  ).toBe(false);
});

it("displays the saved image without offering replacement", () => {
  render(<ReferenceImage projectId={3} registered={true} onSaved={vi.fn()} />);
  expect(screen.getByAltText("初期参考画像").getAttribute("src")).toBe(
    "/api/projects/3/initial-image",
  );
  expect(screen.queryByLabelText("参考画像を選択")).toBeNull();
});
