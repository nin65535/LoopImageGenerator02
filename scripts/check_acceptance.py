"""Run real ComfyUI/Chrome acceptance in isolated storage, then lifecycle checks."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from backend.config import load_settings
from scripts.check_generation_history import disconnect_before_shutdown
from scripts.check_projects import running_app


def verify_weights(parent, child, selection):
    previous = parent["parameters"]["tag_weights"]
    images = {image["id"]: image["tags"] for image in parent["images"]}
    likes = [images[key] for key in selection["liked"]]
    dislikes = [images[key] for key in selection["disliked"]]
    all_tags = set(previous).union(*(set(tags) for tags in likes + dislikes))
    expected = {}
    for tag in all_tags:
        old = previous.get(tag, 0)
        positive = sum(tag in tags for tags in likes) / len(likes) if likes else 0
        negative = sum(tag in tags for tags in dislikes) / len(dislikes) if dislikes else 0
        evidence = old if positive and negative else positive - negative
        weight = (old + evidence) / 2
        if weight:
            expected[tag] = weight
    assert child["parameters"]["tag_weights"] == expected
    assert child["parameters"]["inheritance_rate"] == 0.5


def main():
    with TemporaryDirectory(prefix="loop-acceptance-") as directory:
        settings = load_settings().model_copy(
            update=dict(storage_dir=Path(directory), image_count=2, width=256, height=384)
        )
        stream = io.BytesIO()
        Image.new("RGB", (256, 384), "steelblue").save(stream, "PNG")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                with running_app(settings) as url, disconnect_before_shutdown(page):
                    page.goto(url)
                    page.get_by_label("プロジェクト名").fill("工程16受入")
                    page.get_by_role("button", name="作成する", exact=True).click()
                    page.get_by_label("参考画像を選択").set_input_files(
                        {
                            "name": "reference.png",
                            "mimeType": "image/png",
                            "buffer": stream.getvalue(),
                        }
                    )
                    page.get_by_role("button", name="参考画像から候補を生成").click()
                    expect(page.locator(".candidate")).to_have_count(2, timeout=300_000)
                    root = page.request.get(url + "/api/projects/1/generations").json()[0]
                    region = page.get_by_role("region", name="Generation #1の画像評価")
                    region.get_by_role("button", name="好き", exact=True).first.click()
                    region.get_by_role("button", name="嫌い", exact=True).nth(1).click()
                    assert page.request.get(url + "/api/projects/1/generations").json() == [root]
                    region.get_by_role("button", name="評価を確定して次世代を生成").click()
                    expect(page.locator(".candidate")).to_have_count(4, timeout=300_000)
                    saved = page.request.get(url + "/api/projects/1/generations").json()
                    assert saved[0] == root
                    verify_weights(root, saved[1], saved[1]["selection"])
                # Restart with a different count and aspect ratio, then branch from the root.
                settings = settings.model_copy(update=dict(image_count=3, width=384, height=256))
                with running_app(settings) as url, disconnect_before_shutdown(page):
                    page.goto(url)
                    page.get_by_role("button", name="工程16受入（#1）を開く").click()
                    expect(page.locator(".candidate")).to_have_count(4)
                    region = page.get_by_role("region", name="Generation #1の画像評価")
                    region.get_by_role("button", name="好き", exact=True).first.click()
                    region.get_by_role("button", name="評価を確定して次世代を生成").click()
                    expect(page.locator(".candidate")).to_have_count(5, timeout=300_000)
                    branched = page.request.get(url + "/api/projects/1/generations").json()
                    assert branched[:2] == saved
                    assert branched[2]["parent_id"] == root["id"]
                    assert branched[2]["selection"]["liked"] == []
                    verify_weights(root, branched[2], branched[2]["selection"])
                    for generation, count, width, height in (
                        (branched[0], 2, 256, 384),
                        (branched[1], 2, 256, 384),
                        (branched[2], 3, 384, 256),
                    ):
                        params = generation["parameters"]
                        assert (params["image_count"], params["width"], params["height"]) == (
                            count,
                            width,
                            height,
                        )
                        assert len(generation["images"]) == count
                        for image in generation["images"]:
                            response = page.request.get(url + image["url"])
                            assert response.ok
                            assert Image.open(io.BytesIO(response.body())).size == (width, height)
                    assert branched[1]["parameters"]["seeds"] != branched[0]["parameters"]["seeds"]
                with running_app(settings) as url, disconnect_before_shutdown(page):
                    page.goto(url)
                    page.get_by_role("button", name="工程16受入（#1）を開く").click()
                    expect(page.locator(".candidate")).to_have_count(5)
                    page.get_by_label("表示するGeneration").select_option("2")
                    expect(page.locator(".candidate")).to_have_count(4)
                    assert page.request.get(url + "/api/projects/1/generations").json() == branched
                    assert not errors, errors
                print(json.dumps({"generations": 3, "images": 7, "chrome_errors": errors}))
            finally:
                browser.close()


if __name__ == "__main__":
    main()
