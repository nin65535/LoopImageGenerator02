"""Exercise reload during a pending request and a long history in actual Chrome."""

import asyncio
import io
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from backend.config import Settings
from backend.database import Database
from backend.generation import GeneratedImage, GenerationResult
from backend.generation_storage import save_generation
from backend.tagging import TaggingResult
from scripts.check_projects import running_app


def main():
    with TemporaryDirectory(prefix="loop-recovery-") as directory:
        settings = Settings(storage_dir=Path(directory), image_count=1, width=64, height=96)
        database = Database(settings.database_path)
        database.initialize()
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO projects (name, initial_image_path) VALUES ('復旧検証', '')"
            )
        buffer = io.BytesIO()
        Image.new("RGB", (64, 96), "steelblue").save(buffer, "PNG")
        result = GenerationResult(
            {
                "image_count": 1,
                "width": 64,
                "height": 96,
                "seeds": [1],
                "checkpoint": "fixture",
                "tag_weights": {"sky": 1.0},
            },
            (GeneratedImage(0, 1, "fixture", buffer.getvalue(), {}),),
        )
        parent = None
        for i in range(300):
            parent = save_generation(
                database,
                settings.storage_dir,
                1,
                result,
                ({"sky": None},),
                parent_id=parent,
                selection={"liked": [i], "disliked": []} if parent else None,
            )
        entered, release = threading.Event(), threading.Event()

        async def generating(*args, **kwargs):
            entered.set()
            await asyncio.to_thread(release.wait, 20)
            return result

        async def tagging(*args):
            return TaggingResult("fixture", {"sky": None})

        with (
            patch("backend.generation_flow.generate_images", generating),
            patch("backend.generation_storage.tag_image", tagging),
            sync_playwright() as playwright,
        ):
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                with running_app(settings) as url:
                    try:
                        page.goto(url)
                        page.get_by_role("button", name="復旧検証（#1）を開く").click()
                        expect(page.locator("[data-generation]")).to_have_count(300)
                        page.get_by_label("表示するGeneration").select_option("1")
                        expect(page.locator(".candidate")).to_have_count(1)
                        page.get_by_role("button", name="好き", exact=True).click()
                        page.get_by_role("button", name="評価を確定して次世代を生成").click()
                        assert entered.wait(5)
                        page.reload()
                        page.get_by_role("button", name="復旧検証（#1）を開く").click()
                        expect(
                            page.get_by_text("画像生成・タグ付け中です…完了後に保存します。")
                        ).to_be_visible()
                        assert (
                            len(page.request.get(url + "/api/projects/1/generations").json()) == 300
                        )
                        duplicate = page.request.post(
                            url + "/api/projects/1/generations",
                            data={"parent_id": 1, "selection": {"liked": [1], "disliked": []}},
                        )
                        assert duplicate.status == 409
                        release.set()
                        expect(page.locator('[data-generation="301"]')).to_have_count(
                            1, timeout=10000
                        )
                        assert (
                            len(page.request.get(url + "/api/projects/1/generations").json()) == 301
                        )
                        assert not errors, errors
                    finally:
                        release.set()
                        page.goto("about:blank")
            finally:
                browser.close()
        print(
            "Chrome 1920px: 300-generation history, reload during request, "
            "duplicate rejection, recovery: OK"
        )


if __name__ == "__main__":
    main()
