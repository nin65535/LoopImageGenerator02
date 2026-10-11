"""Check dedicated Chrome window position and maximized state across fresh profiles."""

import os
import socket
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from backend.launcher import AppServer, find_chrome
from backend.window_state import WindowState
from scripts.check_lifecycle import wait_for


def main():
    if os.name != "nt":
        raise RuntimeError("This check requires Windows")
    with tempfile.TemporaryDirectory(prefix="loop-window-state-") as directory:
        root = Path(directory)
        config = root / "config.toml"
        config.write_text('storage_dir = "data"\nstartup_timeout = 30\n', encoding="utf-8")
        normal = WindowState(left=120, top=140, right=1020, bottom=840, maximized=False)
        maximized = normal.model_copy(update={"maximized": True})
        restored_normal = normal.model_copy(update={"left": 180, "right": 1080})
        expected = None
        with patch.dict(os.environ, {"LOOP_IMAGE_CONFIG": str(config)}):
            for target in (maximized, restored_normal, None):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                with tempfile.TemporaryDirectory(prefix="loop-window-profile-") as profile:
                    server = AppServer(port, find_chrome(), profile)
                    thread = threading.Thread(target=server.run, daemon=True)
                    thread.start()
                    try:
                        wait_for(lambda: server.window_tracker is not None)
                        tracker = server.window_tracker
                        wait_for(lambda: tracker.restored and tracker.last is not None)
                        if expected:
                            wait_for(lambda: tracker.last == expected)
                            print(f"Restored: {expected.model_dump()}", flush=True)
                        if target:
                            hwnd = tracker.window.find()
                            tracker.window.restore(hwnd, target)
                            wait_for(lambda: tracker.last == target)
                            expected = target
                        server.close_browser()
                        wait_for(lambda: not thread.is_alive(), timeout=12)
                        assert server.window_store.read() == expected
                    finally:
                        server.should_exit = True
                        thread.join(timeout=10)
                        server.close_browser()
    print("Chrome window bounds / maximized on + off / fresh-profile restart: OK")


if __name__ == "__main__":
    main()
