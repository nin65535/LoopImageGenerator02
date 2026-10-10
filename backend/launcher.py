"""Run the local server and an isolated Chrome application window."""

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import uvicorn

from backend.lifecycle import ConnectionMonitor
from backend.main import DIST, create_app


def find_chrome() -> str:
    candidates = [shutil.which("google-chrome"), shutil.which("chrome")]
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidates.append(str(Path(root) / "Google/Chrome/Application/chrome.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Google Chromeが見つかりません。Chromeをインストールしてください。")


class AppServer(uvicorn.Server):
    def __init__(self, port: int, chrome: str, profile: str, headless: bool = False):
        self.chrome = chrome
        self.profile = profile
        self.headless = headless
        self.browser: subprocess.Popen | None = None
        self.watcher: asyncio.Task | None = None
        self.monitor = ConnectionMonitor(self.request_exit)
        super().__init__(
            uvicorn.Config(
                create_app(monitor=self.monitor),
                host="127.0.0.1",
                port=port,
                timeout_graceful_shutdown=3,
            )
        )

    def request_exit(self) -> None:
        logging.getLogger("uvicorn.error").info("UI disconnected; stopping backend")
        self.should_exit = True

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets)
        if self.should_exit:
            return
        # Uvicorn has bound its listening socket before Chrome is launched.
        self.monitor.deadline = self.monitor.clock() + self.monitor.startup_timeout
        args = [
            self.chrome,
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--app=http://127.0.0.1:{self.config.port}",
        ]
        if self.headless:
            args.extend(["--headless=new", "--disable-gpu", "--remote-debugging-port=0"])
        self.browser = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.watcher = asyncio.create_task(self.monitor.watch())

    async def shutdown(self, sockets=None) -> None:
        if self.watcher:
            self.watcher.cancel()
        await super().shutdown(sockets)

    def close_browser(self) -> None:
        if self.browser and self.browser.poll() is None:
            self.browser.terminate()
            try:
                self.browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.browser.kill()
                self.browser.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not DIST.joinpath("index.html").is_file():
        parser.error("UIが未ビルドです。frontendのビルドが必要です。")
    try:
        chrome = find_chrome()
    except RuntimeError as error:
        parser.error(str(error))
    with tempfile.TemporaryDirectory(prefix="loop-image-generator-chrome-") as profile:
        server = AppServer(args.port, chrome, profile)
        try:
            server.run()
        finally:
            server.close_browser()


if __name__ == "__main__":
    main()
