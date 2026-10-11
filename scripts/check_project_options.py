"""Verify settings, new project choices and generation snapshots in real Chrome."""

import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from backend.app_options import AppOptions
from backend.config import Settings
from backend.generation import GeneratedImage, GenerationResult
from backend.tagging import TaggingResult
from scripts.check_generation_history import disconnect_before_shutdown
from scripts.check_projects import running_app


def main():
    calls = []

    async def tagging(*args):
        return TaggingResult("fixture", {"sky": None})

    async def generating(client, settings, **kwargs):
        calls.append((kwargs["checkpoint"], settings.width, settings.height))
        buffer = io.BytesIO()
        Image.new("RGB", (settings.width, settings.height), "steelblue").save(buffer, "PNG")
        seed = len(calls)
        return GenerationResult(
            {
                **kwargs,
                "image_count": 1,
                "width": settings.width,
                "height": settings.height,
                "seeds": [seed],
            },
            (GeneratedImage(0, seed, "fixture", buffer.getvalue(), {}),),
        )

    with (
        TemporaryDirectory(prefix="loop-options-") as directory,
        patch("backend.generation_flow.tag_image", tagging),
        patch("backend.generation_storage.tag_image", tagging),
        patch("backend.generation_flow.generate_images", generating),
        sync_playwright() as playwright,
    ):
        settings = Settings(storage_dir=Path(directory), image_count=1)
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        model = "hassakuXLIllustrious_v33.safetensors"
        try:
            with running_app(settings) as url, disconnect_before_shutdown(page):
                page.goto(url)
                expect(page.get_by_label("プロジェクト名")).to_have_count(0)
                page.get_by_role("link", name="設定", exact=True).click()
                for other in AppOptions().model_whitelist:
                    page.get_by_role("checkbox", name=other, exact=True).set_checked(other == model)
                page.get_by_label("幅", exact=True).fill("640")
                page.get_by_label("高さ", exact=True).fill("960")
                page.get_by_role("button", name="サイズを追加").click()
                page.get_by_role("button", name="設定を保存").click()
                expect(page.get_by_text("設定を保存しました。", exact=True)).to_be_visible()
                page.get_by_role("link", name="LoopImageGenerator V2", exact=True).click()
                page.get_by_role("link", name="新規プロジェクト", exact=True).click()
                page.get_by_label("プロジェクト名").fill("モデル・サイズ確認")
                expect(page.get_by_label("モデル").locator("option")).to_have_count(1)
                page.get_by_label("モデル").select_option(model)
                page.get_by_label("画像サイズ").select_option("640x960")
                page.get_by_role("button", name="作成する", exact=True).click()
                expect(
                    page.get_by_role("heading", name="モデル・サイズ確認", exact=True)
                ).to_be_visible()
                config = {"checkpoint": model, "width": 640, "height": 960}
                assert (
                    page.request.get(url + "/api/projects/1").json()["generation_config"] == config
                )
                buffer = io.BytesIO()
                Image.new("RGB", (64, 96), "blue").save(buffer, "PNG")
                page.get_by_label("参考画像を選択").set_input_files(
                    {"name": "ref.png", "mimeType": "image/png", "buffer": buffer.getvalue()}
                )
                page.get_by_role("button", name="参考画像から候補を生成").click()
                expect(page.locator(".candidate")).to_have_count(1)
                page.get_by_role("link", name="設定", exact=True).click()
                page.get_by_role("checkbox", name=model, exact=True).uncheck()
                page.get_by_role("button", name="設定を保存").click()
                expect(page.get_by_text("設定を保存しました。", exact=True)).to_be_visible()
                page.get_by_role("link", name="LoopImageGenerator V2", exact=True).click()
                page.get_by_role("link", name="新規プロジェクト", exact=True).click()
                expect(page.get_by_role("button", name="作成する", exact=True)).to_be_disabled()
                page.goto(url + "#/projects/1")
                page.get_by_role("button", name="好き", exact=True).click()
                page.get_by_role("button", name="評価を確定して次世代を生成").click()
                expect(page.locator(".candidate")).to_have_count(2)
                assert calls == [(model, 640, 960), (model, 640, 960)]
                generations = page.request.get(url + "/api/projects/1/generations").json()
                assert all(
                    (
                        g["parameters"]["checkpoint"],
                        g["parameters"]["width"],
                        g["parameters"]["height"],
                    )
                    == (model, 640, 960)
                    for g in generations
                )
            with running_app(settings) as url, disconnect_before_shutdown(page):
                page.goto(url + "#/projects/1")
                expect(page.locator(".candidate")).to_have_count(2)
                assert (
                    page.request.get(url + "/api/projects/1").json()["generation_config"] == config
                )
                saved = page.request.get(url + "/api/settings").json()
                assert saved["model_whitelist"] == []
                assert saved["extra_sizes"] == [{"width": 640, "height": 960}]
            assert not errors, errors
        finally:
            browser.close()
    print("Chrome: isolated creation, whitelist, custom size, generation snapshots, restart: OK")


if __name__ == "__main__":
    main()
