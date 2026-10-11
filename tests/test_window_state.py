from unittest.mock import Mock

from backend.window_state import WindowState, WindowStateStore, WindowTracker


def state(maximized=False):
    return WindowState(left=-1200, top=80, right=-300, bottom=780, maximized=maximized)


def test_window_state_round_trip_and_invalid_file(tmp_path):
    store = WindowStateStore(tmp_path)
    assert store.read() is None
    store.write(state(True))
    assert store.read() == state(True)
    store.path.write_text('{"left":true}', encoding="utf-8")
    assert store.read() is None
    store.path.write_text("broken", encoding="utf-8")
    assert store.read() is None


def test_restores_once_saves_changes_and_retains_last_state_after_close(tmp_path):
    store = WindowStateStore(tmp_path)
    store.write(state(True))
    window = Mock()
    window.find.return_value = 123
    window.read.return_value = state(True)
    tracker = WindowTracker(window, store)
    tracker.tick()
    window.restore.assert_called_once_with(123, state(True))
    window.read.return_value = state(False)
    tracker.tick()
    assert store.read() == state(False)
    window.restore.assert_called_once()
    window.read.return_value = None  # Minimized state is ignored.
    tracker.tick()
    window.find.return_value = None  # Window already closed.
    tracker.tick()
    assert store.read() == state(False)


def test_new_window_keeps_chrome_default_until_a_window_exists(tmp_path):
    store = WindowStateStore(tmp_path)
    window = Mock()
    window.find.return_value = None
    tracker = WindowTracker(window, store)
    tracker.tick()
    assert not store.path.exists()
    window.find.return_value = 123
    window.read.return_value = state()
    tracker.tick()
    window.restore.assert_not_called()
    assert store.read() == state()
