"""Verify project creation and reopening after API and Chrome restart."""

import socket
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from backend.config import Settings
from backend.main import create_app
from scripts.check_lifecycle import wait_for


@contextmanager
def running_app(settings):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings=settings), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_for(lambda: server.started)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), "API did not stop"


def main():
    with tempfile.TemporaryDirectory(prefix="loop-project-check-") as directory:
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
                        expect(page.get_by_role("status")).to_have_text("APIに接続しました")
                        if not restart:
                            expect(
                                page.get_by_text("プロジェクトはまだありません。")
                            ).to_be_visible()
                            for name in ("海", "山"):
                                page.get_by_label("プロジェクト名").fill(name)
                                page.get_by_role("button", name="作成する", exact=True).click()
                                expect(
                                    page.get_by_role("heading", name=name, exact=True)
                                ).to_be_visible()
                        for name, project_id in (("海", 1), ("山", 2)):
                            page.get_by_role(
                                "button", name=f"{name}（#{project_id}）を開く"
                            ).click()
                            expect(
                                page.get_by_role("heading", name=name, exact=True)
                            ).to_be_visible()
                            expect(
                                page.get_by_text(f"プロジェクト #{project_id} · 保存済み 0世代")
                            ).to_be_visible()
                            expect(
                                page.get_by_text("参考画像はまだ登録されていません。")
                            ).to_be_visible()
                        page.reload()
                        expect(page.get_by_role("button", name="海（#1）を開く")).to_be_visible()
                        assert not errors, errors
                    finally:
                        browser.close()
        print("Chrome project create / isolation / reload / API and Chrome restart: OK")


if __name__ == "__main__":
    main()
