"""Exercise automatic launch, reload, tab close and Chrome crash with real SSE."""

import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from backend.launcher import AppServer, find_chrome


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for lifecycle transition")


def verify(crash: bool) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="loop-lifecycle-check-") as profile:
        server = AppServer(port, find_chrome(), profile, headless=True)
        server.monitor.grace = 1.5
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            devtools = Path(profile) / "DevToolsActivePort"
            debug_port = []

            def read_debug_port():
                try:
                    lines = devtools.read_text().splitlines()
                    if lines:
                        debug_port.append(lines[0])
                        return True
                except OSError:
                    pass
                return False

            wait_for(read_debug_port)
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port[0]}")
                context = browser.contexts[0]
                page = context.pages[0]
                expect(page.get_by_role("status")).to_have_text("APIに接続しました")
                wait_for(lambda: server.monitor.connections == 1)
                if not crash:
                    server.monitor.grace = 10
                    page.goto("about:blank")
                    wait_for(lambda: server.monitor.connections == 0)
                    time.sleep(0.5)
                    page.goto(f"http://127.0.0.1:{port}")
                    wait_for(lambda: server.monitor.connections == 1)
                    assert thread.is_alive() and not server.should_exit
                    server.monitor.grace = 1.5
                for _ in range(3):
                    page.reload()
                    expect(page.get_by_role("status")).to_have_text("APIに接続しました")
                time.sleep(2)
                assert thread.is_alive() and not server.should_exit
                second = context.new_page()
                second.goto(f"http://127.0.0.1:{port}")
                wait_for(lambda: server.monitor.connections == 2)
                page.close()
                wait_for(lambda: server.monitor.connections == 1)
                time.sleep(2)
                assert thread.is_alive() and not server.should_exit
                if crash:
                    server.close_browser()
                else:
                    second.close()
                wait_for(lambda: not thread.is_alive())
                assert server.monitor.connections == 0 and server.should_exit
            print(f"Automatic Chrome launch / reload / tabs / {'crash' if crash else 'close'}: OK")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            server.close_browser()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="loop-lifecycle-storage-") as directory:
        config = Path(directory) / "config.toml"
        config.write_text('storage_dir = "data"\n', encoding="utf-8")
        with patch.dict(os.environ, {"LOOP_IMAGE_CONFIG": str(config)}):
            verify(crash=False)
            verify(crash=True)
