"""Verify file selection, drop, failures and reference persistence in real Chrome."""

import io
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from backend.config import Settings
from scripts.check_projects import running_app


def main():
    stream = io.BytesIO()
    Image.new("RGB", (64, 48), "blue").save(stream, "PNG")
    payload = {"name": "../../reference.png", "mimeType": "image/png", "buffer": stream.getvalue()}
    with tempfile.TemporaryDirectory(prefix="loop-reference-check-") as directory:
        settings = Settings(storage_dir=Path(directory))
        with sync_playwright() as playwright:
            for restart in (False, True):
                with running_app(settings) as url:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1920, "height": 1080})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(url)
                        expect(page.get_by_role("status")).to_have_attribute(
                            "data-state", "connected"
                        )
                        if not restart:
                            for index, name in enumerate(("選択", "ドロップ")):
                                page.get_by_role(
                                    "link", name="LoopImageGenerator V2", exact=True
                                ).click()
                                page.get_by_role(
                                    "link", name="新規プロジェクト", exact=True
                                ).click()
                                page.get_by_label("プロジェクト名").fill(name)
                                page.get_by_role("button", name="作成する", exact=True).click()
                                expect(
                                    page.get_by_role("heading", name=name, exact=True)
                                ).to_be_visible()
                                if index == 0:
                                    page.get_by_label("参考画像を選択").set_input_files(
                                        {
                                            "name": "bad.png",
                                            "mimeType": "image/png",
                                            "buffer": b"bad",
                                        }
                                    )
                                    expect(page.get_by_role("alert")).to_contain_text("破損")
                                    page.get_by_label("参考画像を選択").set_input_files(payload)
                                else:
                                    page.locator(".image-drop").evaluate(
                                        """(element, bytes) => {
                                            const transfer = new DataTransfer();
                                            transfer.items.add(new File([new Uint8Array(bytes)],
                                                'reference.png', {type: 'image/png'}));
                                            element.dispatchEvent(new DragEvent('drop',
                                                {bubbles: true, dataTransfer: transfer}));
                                        }""",
                                        list(stream.getvalue()),
                                    )
                                expect(page.get_by_alt_text("初期参考画像")).to_be_visible()
                        for project_id, name in ((1, "選択"), (2, "ドロップ")):
                            page.get_by_role(
                                "link", name="LoopImageGenerator V2", exact=True
                            ).click()
                            page.get_by_role(
                                "button", name=f"{name}（#{project_id}）を開く"
                            ).click()
                            image = page.get_by_alt_text("初期参考画像")
                            expect(image).to_be_visible()
                            page.wait_for_function(
                                "document.querySelector('.reference-image')?.naturalWidth === 64"
                            )
                        page.reload()
                        expect(page.get_by_alt_text("初期参考画像")).to_be_visible()
                        assert not errors, errors
                    finally:
                        browser.close()
        print("Chrome reference select / drop / invalid retry / reload / restart: OK")


if __name__ == "__main__":
    main()
