from __future__ import annotations

import asyncio
import logging
import time
import threading

from irlds.events import ResetCompleted, StatusChanged, TrackerEvent
from irlds.sources.base import TelemetrySource
from irlds.tracker import LapSectorTracker

log = logging.getLogger("irlds.scraper")


class ResetRequest:
    __slots__ = ("driver_name",)

    def __init__(self, driver_name: str | None) -> None:
        self.driver_name = driver_name


class ScraperThread:
    """Runs in a dedicated thread: polls source -> tracker -> pushes events to asyncio queue.

    Only this thread touches the tracker (agent rule 4).
    """

    RETRY_INTERVAL_S = 1.0

    def __init__(
        self,
        source: TelemetrySource,
        tracker: LapSectorTracker,
        event_queue: asyncio.Queue[TrackerEvent],
        poll_hz: int = 60,
    ) -> None:
        self._source = source
        self._tracker = tracker
        self._event_queue = event_queue
        self._poll_hz = max(1, poll_hz)
        self._stop_event = threading.Event()
        # Set to cut a sleep short (stop or reset request).
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_driver: str | None = None
        self._reset_slot: ResetRequest | None = None
        self._reset_slot_lock = threading.Lock()
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending_reset = False
        self._needs_resync = False
        self._reset_on_connect = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._thread = threading.Thread(target=self._run, daemon=True, name="scraper")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def request_reset(self, driver_name: str | None) -> None:
        """Thread-safe; latest request wins. Applied at the top of the next tick."""
        with self._reset_slot_lock:
            self._reset_slot = ResetRequest(driver_name)
        self._wake.set()

    def _run(self) -> None:
        interval = 1.0 / self._poll_hz
        deadline = time.monotonic()

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log.error("Scraper tick error: %s", e, exc_info=True)

            if not self._connected:
                # Disconnected: retry once a second (resets still apply promptly).
                self._sleep(self.RETRY_INTERVAL_S)
                deadline = time.monotonic()
                continue

            now = time.monotonic()
            deadline += interval
            if deadline < now - interval:
                deadline = now  # fell behind; don't burst to catch up
            self._sleep(deadline - now)

    def _sleep(self, seconds: float) -> None:
        if seconds > 0 and self._wake.wait(seconds):
            self._wake.clear()

    def _tick(self) -> None:
        with self._reset_slot_lock:
            request, self._reset_slot = self._reset_slot, None
        if request is not None:
            self._current_driver = request.driver_name
            self._pending_reset = True

        frame = self._source.poll()
        connected_now = frame is not None

        if connected_now != self._connected:
            self._connected = connected_now
            log.info("iRacing connection status: %s", "connected" if connected_now else "disconnected")
            self._push_event(StatusChanged(connected=connected_now))
            if not connected_now:
                self._needs_resync = True

        if frame is None:
            if self._pending_reset:
                # Apply to stats/driver now; re-arm the tracker on the first frame (§8).
                self._push_event(ResetCompleted(driver_name=self._current_driver))
                self._pending_reset = False
                self._reset_on_connect = True
            return

        self._tracker.set_driver_name(self._current_driver)

        if self._pending_reset or self._reset_on_connect:
            self._tracker.reset(frame)
            if self._pending_reset:
                self._push_event(ResetCompleted(driver_name=self._current_driver))
            self._pending_reset = False
            self._reset_on_connect = False
            self._needs_resync = False
            return

        if self._needs_resync:
            # After a telemetry gap the previous position/time are stale.
            self._tracker.resume(frame)
            self._needs_resync = False
            return

        for evt in self._tracker.process(frame):
            self._push_event(evt)

    def _push_event(self, event: TrackerEvent) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)
