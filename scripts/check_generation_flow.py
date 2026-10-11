"""Verify two successive real ComfyUI generations through desktop Chrome."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from backend.config import Settings
from backend.database import Database
from scripts.check_projects import running_app


def main():
    with TemporaryDirectory(prefix="loop-flow-") as directory:
        settings = Settings(storage_dir=Path(directory), image_count=2, width=256, height=384)
        stream = io.BytesIO()
        Image.new("RGB", (256, 384), "steelblue").save(stream, "PNG")
        with running_app(settings) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                page.get_by_role("link", name="新規プロジェクト", exact=True).click()
                page.get_by_label("プロジェクト名").fill("連続生成検証")
                page.get_by_role("button", name="作成する", exact=True).click()
                expect(page.get_by_role("heading", name="連続生成検証", exact=True)).to_be_visible()
                response = page.request.put(
                    url + "/api/projects/1/initial-image",
                    data=stream.getvalue(),
                    headers={"Content-Type": "image/png"},
                )
                assert response.ok, response.text()
                page.reload()
                page.get_by_role("button", name="参考画像から候補を生成").click()
                expect(page.locator(".candidate")).to_have_count(2, timeout=300_000)
                first = page.request.get(url + "/api/projects/1/generations").json()[0]
                section = page.get_by_role("region", name=f"Generation #{first['id']}の画像評価")
                section.get_by_role("button", name="嫌い", exact=True).first.click()
                section.get_by_role("button", name="評価を確定して次世代を生成").click()
                expect(page.locator(".candidate")).to_have_count(4, timeout=300_000)
                snapshots = page.request.get(url + "/api/projects/1/generations").json()
                assert len(snapshots) == 2 and snapshots[0] == first
                assert snapshots[1]["parent_id"] == first["id"]
                for image in page.locator(".candidate img").all():
                    image.evaluate("image => image.decode()")
                with Database(settings.database_path).connect() as connection:
                    rows = connection.execute("SELECT * FROM generations ORDER BY id").fetchall()
                    assert json.loads(rows[1]["selection_json"]) == {
                        "liked": [],
                        "disliked": [first["images"][0]["id"]],
                    }
                    params = [json.loads(row["parameters_json"]) for row in rows]
                    assert params[0]["seeds"] != params[1]["seeds"]
                    assert all(p["inheritance_rate"] == 0.5 for p in params)
                assert not errors, errors
                print(
                    json.dumps(
                        {
                            "generations": 2,
                            "images": 4,
                            "checkpoint": params[0]["checkpoint"],
                            "selection": "dislikes only",
                            "chrome_errors": errors,
                        }
                    )
                )
            finally:
                browser.close()


if __name__ == "__main__":
    main()
