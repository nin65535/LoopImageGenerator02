"""Remember the dedicated Chrome window's normal bounds and maximized state on Windows."""

import asyncio
import ctypes
import logging
from ctypes import wintypes
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, model_validator

logger = logging.getLogger("uvicorn.error")


class WindowState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: StrictInt
    top: StrictInt
    right: StrictInt
    bottom: StrictInt
    maximized: StrictBool

    @model_validator(mode="after")
    def validate_bounds(self):
        if not (100 <= self.right - self.left <= 32768 and 100 <= self.bottom - self.top <= 32768):
            raise ValueError("Invalid window bounds")
        if any(abs(value) > 100000 for value in (self.left, self.top, self.right, self.bottom)):
            raise ValueError("Invalid window position")
        return self


class WindowStateStore:
    def __init__(self, storage: Path):
        self.path = storage / "window-state.json"

    def read(self) -> WindowState | None:
        try:
            if not self.path.exists():
                return None
            return WindowState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Cannot read window state; using Chrome defaults")
            return None

    def write(self, state: WindowState):
        staged = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(state.model_dump_json(indent=2), encoding="utf-8")
            staged.replace(self.path)
        finally:
            staged.unlink(missing_ok=True)


class Placement(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


class WindowsWindow:
    def __init__(self, process_id: int):
        self.process_id = process_id
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            "EnumWindows": ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "GetWindowThreadProcessId": (
                [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
                wintypes.DWORD,
            ),
            "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowPlacement": ([wintypes.HWND, ctypes.POINTER(Placement)], wintypes.BOOL),
            "SetWindowPlacement": ([wintypes.HWND, ctypes.POINTER(Placement)], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            method = getattr(self.user32, name)
            method.argtypes = args
            method.restype = result

    def find(self):
        found = []

        def visit(hwnd, _):
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.process_id and self.user32.IsWindowVisible(hwnd):
                name = ctypes.create_unicode_buffer(256)
                self.user32.GetClassNameW(hwnd, name, len(name))
                if name.value == "Chrome_WidgetWin_1":
                    found.append(hwnd)
                    return False
            return True

        self.user32.EnumWindows(self.callback_type(visit), 0)
        return found[0] if found else None

    def read(self, hwnd) -> WindowState | None:
        placement = Placement()
        placement.length = ctypes.sizeof(Placement)
        if not self.user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            return None
        # Minimize is temporary: retain the last normal/maximized state instead.
        if placement.showCmd not in (1, 3):
            return None
        rect = placement.rcNormalPosition
        return WindowState(
            left=rect.left,
            top=rect.top,
            right=rect.right,
            bottom=rect.bottom,
            maximized=placement.showCmd == 3,
        )

    def restore(self, hwnd, state: WindowState):
        placement = Placement()
        placement.length = ctypes.sizeof(Placement)
        placement.showCmd = 3 if state.maximized else 1
        placement.ptMinPosition = wintypes.POINT(-1, -1)
        placement.ptMaxPosition = wintypes.POINT(-1, -1)
        placement.rcNormalPosition = wintypes.RECT(state.left, state.top, state.right, state.bottom)
        if not self.user32.SetWindowPlacement(hwnd, ctypes.byref(placement)):
            raise ctypes.WinError(ctypes.get_last_error())


class WindowTracker:
    def __init__(self, window, store: WindowStateStore):
        self.window = window
        self.store = store
        self.saved = store.read()
        self.restored = False
        self.last = None

    def tick(self):
        hwnd = self.window.find()
        if hwnd is None:
            return
        if not self.restored:
            if self.saved:
                self.window.restore(hwnd, self.saved)
            self.restored = True
        state = self.window.read(hwnd)
        if state is not None and state != self.last:
            self.store.write(state)
            self.last = state

    async def watch(self):
        while True:
            try:
                self.tick()
            except (OSError, ValueError):
                logger.warning("Cannot save or restore window state", exc_info=True)
            await asyncio.sleep(0.25)
