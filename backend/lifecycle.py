"""Track live SSE connections without treating page reloads as application exit."""

import asyncio
import time
from collections.abc import Callable


class ConnectionMonitor:
    def __init__(
        self,
        shutdown: Callable[[], None],
        grace: float = 5,
        startup_timeout: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.shutdown = shutdown
        self.grace = grace
        self.startup_timeout = startup_timeout
        self.clock = clock
        self.connections = 0
        self.deadline = clock() + startup_timeout
        self.stopped = False

    def connect(self) -> None:
        self.connections += 1

    def disconnect(self) -> None:
        self.connections -= 1
        if self.connections == 0:
            self.deadline = self.clock() + self.grace

    def check(self) -> None:
        if not self.stopped and self.connections == 0 and self.clock() >= self.deadline:
            self.stopped = True
            self.shutdown()

    async def watch(self) -> None:
        while not self.stopped:
            self.check()
            await asyncio.sleep(0.25)
