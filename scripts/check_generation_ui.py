"""Verify candidate layout and transient ratings using real desktop Chrome."""

import io
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from backend.config import Settings
from backend.database import Database
from backend.generation import GeneratedImage, GenerationResult
from backend.generation_storage import save_generation
from scripts.check_projects import running_app


def snapshot(database):
    with database.connect() as connection:
        return [
            [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in ("projects", "generations", "images")
        ]


def main():
    with tempfile.TemporaryDirectory(prefix="loop-generation-ui-") as directory:
        settings = Settings(storage_dir=Path(directory))
        database = Database(settings.database_path)
        database.initialize()
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO projects(name, initial_image_path) VALUES ('評価検証', '')"
            )
        ids = []
        for count, width, height in ((1, 512, 512), (3, 768, 384), (11, 384, 576)):
            stream = io.BytesIO()
            Image.new("RGB", (width, height), "steelblue").save(stream, "PNG")
            result = GenerationResult(
                {
                    "image_count": count,
                    "width": width,
                    "height": height,
                    "seeds": list(range(count)),
                },
                tuple(GeneratedImage(i, i, str(i), stream.getvalue(), {}) for i in range(count)),
            )
            ids.append(save_generation(database, settings.storage_dir, 1, result, ({},) * count))
        before = snapshot(database)
        with running_app(settings) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                page.get_by_role("button", name="評価検証（#1）を開く").click()
                expect(page.locator(".candidate")).to_have_count(11)
                page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                page.wait_for_function(
                    "Math.abs(document.querySelector('.app-header')"
                    ".getBoundingClientRect().top) < 1"
                )
                header = page.locator(".app-header")
                expect(
                    header.get_by_role("navigation", name="Generationの祖先経路")
                ).to_be_visible()
                expect(page.locator(".selected .generation-breadcrumbs")).to_have_count(0)
                expect(header.get_by_role("link", name="LoopImageGenerator V2")).to_be_visible()
                expect(header.get_by_role("link", name="設定")).to_be_visible()
                page.get_by_role("button", name="評価を確定して次世代を生成", exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("最低1枚")
                card = page.get_by_role("article", name="画像 1", exact=True)
                card.get_by_role("button", name="好き", exact=True).click()
                card.get_by_role("button", name="嫌い", exact=True).click()
                expect(card.get_by_role("button", name="好き", exact=True)).to_have_attribute(
                    "aria-pressed", "false"
                )
                card.get_by_role("button", name="嫌い", exact=True).click()
                expect(card.get_by_role("button", name="未評価", exact=True)).to_have_attribute(
                    "aria-pressed", "true"
                )
                for generation_id, count in zip(ids, (1, 3, 11), strict=True):
                    page.get_by_label("表示するGeneration").select_option(str(generation_id))
                    expect(page.locator(".candidate")).to_have_count(count)
                    for image in page.locator(".candidate img").all():
                        image.scroll_into_view_if_needed()
                        expect(image).to_be_visible()
                        image.evaluate("image => image.decode()")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    if count == 11:
                        assert (
                            page.locator(".candidate-grid").evaluate(
                                "grid => getComputedStyle(grid).gridTemplateColumns"
                                ".split(' ').length"
                            )
                            >= 5
                        )
                card.get_by_role("button", name="好き", exact=True).click()
                page.reload()
                expect(page.locator('.candidate[data-rating="unrated"]')).to_have_count(11)
                assert snapshot(database) == before
                assert not errors, errors
            finally:
                browser.close()
        print("Chrome 1920px: 1/3/11 images, aspect ratios, ratings, reload, unchanged DB: OK")


if __name__ == "__main__":
    main()
