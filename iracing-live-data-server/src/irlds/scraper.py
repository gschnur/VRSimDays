from __future__ import annotations

import asyncio
import logging
import time
import threading
from queue import SimpleQueue

from irlds.events import ResetCompleted, StatusChanged, TrackerEvent
from irlds.models import TelemetryFrame
from irlds.sources.base import TelemetrySource
from irlds.tracker import LapSectorTracker

log = logging.getLogger("irlds.scraper")


class ResetRequest:
    __slots__ = ("driver_name",)

    def __init__(self, driver_name: str | None) -> None:
        self.driver_name = driver_name


class ScraperThread:
    """Runs in a dedicated thread: polls source -> tracker -> pushes events to asyncio queue."""

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
        self._poll_hz = poll_hz
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_driver: str | None = None
        self._reset_slot: ResetRequest | None = None
        self._reset_slot_lock = threading.Lock()
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending_reset: bool = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._thread = threading.Thread(target=self._run, daemon=True, name="scraper")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def request_reset(self, driver_name: str | None) -> None:
        with self._reset_slot_lock:
            self._reset_slot = ResetRequest(driver_name)
            self._pending_reset = True

    def _run(self) -> None:
        interval = 1.0 / self._poll_hz
        deadline = time.monotonic()
        latest_frame: TelemetryFrame | None = None

        while not self._stop_event.is_set():
            try:
                self._tick(latest_frame)
            except Exception as e:
                log.error("Scraper tick error: %s", e, exc_info=True)

            now = time.monotonic()
            deadline += interval
            sleep_time = deadline - now
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _tick(self, latest_frame: TelemetryFrame | None) -> None:
        with self._reset_slot_lock:
            if self._reset_slot is not None:
                self._current_driver = self._reset_slot.driver_name
                self._reset_slot = None
                self._pending_reset = True

        frame = self._source.poll()
        connected_now = frame is not None

        if connected_now != self._connected:
            self._connected = connected_now
            log.info("iRacing connection status: %s", "connected" if connected_now else "disconnected")
            self._push_event(StatusChanged(connected=connected_now))

        if not connected_now:
            if self._pending_reset:
                self._push_event(ResetCompleted(driver_name=self._current_driver))
                self._pending_reset = False
            return

        latest_frame = frame

        if self._pending_reset:
            self._tracker.set_driver_name(self._current_driver)
            self._tracker.reset(frame)
            self._push_event(ResetCompleted(driver_name=self._current_driver))
            self._pending_reset = False
            return

        self._tracker.set_driver_name(self._current_driver)
        events = self._tracker.process(frame)
        for evt in events:
            self._push_event(evt)

    def _push_event(self, event: TrackerEvent) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)
