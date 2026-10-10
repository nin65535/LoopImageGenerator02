from unittest.mock import Mock

from backend.lifecycle import ConnectionMonitor


def test_startup_timeout_and_single_shutdown():
    now = [0.0]
    stop = Mock()
    monitor = ConnectionMonitor(stop, clock=lambda: now[0])
    now[0] = 29
    monitor.check()
    stop.assert_not_called()
    now[0] = 30
    monitor.check()
    monitor.check()
    stop.assert_called_once()


def test_reload_multiple_tabs_and_disconnect_grace():
    now = [0.0]
    stop = Mock()
    monitor = ConnectionMonitor(stop, clock=lambda: now[0])
    monitor.connect()
    now[0] = 100
    monitor.check()
    monitor.disconnect()
    now[0] = 109
    monitor.check()
    monitor.connect()  # Reload reconnects inside the grace period.
    monitor.connect()  # Another tab keeps the backend alive.
    monitor.disconnect()
    now[0] = 200
    monitor.check()
    stop.assert_not_called()
    monitor.disconnect()
    now[0] = 209
    monitor.check()
    stop.assert_not_called()
    now[0] = 210
    monitor.check()
    stop.assert_called_once()
