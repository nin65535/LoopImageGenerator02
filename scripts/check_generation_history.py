"""Verify branches, restart and scroll preservation in real Chrome and ComfyUI."""

import io
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from backend.config import Settings
from backend.database import Database
from backend.generation import GeneratedImage, GenerationResult
from backend.generation_storage import save_generation
from scripts.check_projects import running_app


@contextmanager
def disconnect_before_shutdown(page):
    try:
        yield
    finally:
        page.goto("about:blank")


def main():
    with TemporaryDirectory(prefix="loop-history-") as directory:
        settings = Settings(storage_dir=Path(directory), image_count=2, width=256, height=384)
        database = Database(settings.database_path)
        database.initialize()
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO projects(name, initial_image_path) VALUES ('履歴検証', '')"
            )
        stream = io.BytesIO()
        Image.new("RGB", (256, 384), "steelblue").save(stream, "PNG")
        result = GenerationResult(
            {
                "image_count": 2,
                "width": 256,
                "height": 384,
                "seeds": [1, 2],
                "checkpoint": "boleromixIllustrious_v402.safetensors",
                "steps": 4,
                "tag_weights": {"sky": 1.0},
            },
            tuple(GeneratedImage(i, i + 1, "fixture", stream.getvalue(), {}) for i in range(2)),
        )
        parent = None
        for _ in range(3):
            selection = None
            if parent:
                with database.connect() as connection:
                    image_id = connection.execute(
                        "SELECT id FROM images WHERE generation_id = ? ORDER BY position", (parent,)
                    ).fetchone()[0]
                selection = {"liked": [image_id], "disliked": []}
            parent = save_generation(
                database,
                settings.storage_dir,
                1,
                result,
                ({"sky": None},) * 2,
                parent_id=parent,
                selection=selection,
            )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                with running_app(settings) as url, disconnect_before_shutdown(page):
                    page.goto(url)
                    page.get_by_role("button", name="履歴検証（#1）を開く").click()
                    expect(page.locator(".candidate")).to_have_count(6)
                    root = page.get_by_role("region", name="Generation #1の画像評価")
                    root.get_by_role("button", name="嫌い", exact=True).first.click()
                    root.get_by_role("button", name="評価を確定して次世代を生成").click()
                    expect(
                        page.get_by_text("画像生成・タグ付け中です…完了後に保存します。")
                    ).to_be_visible()
                    page.evaluate(
                        "window.scrollTo(0, document.querySelector('[data-generation=\"1\"]')"
                        ".getBoundingClientRect().top + scrollY - 40)"
                    )
                    before = page.locator('[data-generation="1"]').bounding_box()["y"]
                    expect(
                        page.get_by_role("region", name="Generation #4の画像評価")
                    ).to_be_visible(timeout=300_000)
                    after = page.locator('[data-generation="1"]').bounding_box()["y"]
                    assert abs(before - after) < 3, (before, after)
                    assert page.locator('[data-generation="3"]').count() == 0
                    expect(page.locator(".candidate")).to_have_count(4)
                    first_four = page.request.get(url + "/api/projects/1/generations").json()
                    assert first_four[3]["parent_id"] == 1
                    assert first_four[3]["selection"] == {"liked": [], "disliked": [1]}
                    page.get_by_role("button", name="枝 #2を開く").click()
                    expect(
                        page.get_by_role("region", name="Generation #2の画像評価")
                    ).to_be_visible()
                    page.get_by_label("表示するGeneration").select_option("3")
                    expect(page.locator(".candidate")).to_have_count(6)
                    page.get_by_label("表示するGeneration").select_option("4")
                    leaf = page.get_by_role("region", name="Generation #4の画像評価")
                    leaf.get_by_role("button", name="好き", exact=True).first.click()
                    leaf.get_by_role("button", name="評価を確定して次世代を生成").click()
                    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                    expect(
                        page.get_by_role("region", name="Generation #5の画像評価")
                    ).to_be_visible(timeout=300_000)
                    assert (
                        page.evaluate(
                            "document.documentElement.scrollHeight - innerHeight - scrollY"
                        )
                        < 3
                    )
                    saved = page.request.get(url + "/api/projects/1/generations").json()
                    assert saved[:4] == first_four
                with running_app(settings) as url, disconnect_before_shutdown(page):
                    page.goto(url)
                    page.get_by_role("button", name="履歴検証（#1）を開く").click()
                    expect(page.locator(".candidate")).to_have_count(6)
                    expect(
                        page.get_by_role("navigation", name="Generationの祖先経路").get_by_role(
                            "listitem"
                        )
                    ).to_have_text(["Generation #1", "›Generation #4", "›Generation #5"])
                    page.get_by_label("表示するGeneration").select_option("3")
                    expect(
                        page.get_by_role("navigation", name="Generationの祖先経路").get_by_role(
                            "listitem"
                        )
                    ).to_have_text(["Generation #1", "›Generation #2", "›Generation #3"])
                    page.get_by_label("表示するGeneration").select_option("5")
                    assert page.request.get(url + "/api/projects/1/generations").json() == saved
                    assert not errors, errors
                print(
                    "Chrome: real sibling generation, both paths after API restart, "
                    "past-view scroll and bottom-follow: OK"
                )
            finally:
                browser.close()


if __name__ == "__main__":
    main()
