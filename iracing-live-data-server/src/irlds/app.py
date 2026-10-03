from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from irlds.commands import PitActionsLike
from irlds.config import Config
from irlds.events import TrackerEvent
from irlds.models import SessionStats, TelemetryFrame
from irlds.pit_actions import FakePitActions, PitActions, PitResult
from irlds.scraper import ScraperThread
from irlds.server import DEFAULT_ORIGINS, IRLDSServer
from irlds.sources.base import TelemetrySource
from irlds.tracker import LapSectorTracker

log = logging.getLogger("irlds.app")

SINGLE_SECTOR = [0.0]


class BoundarySyncSource:
    """Wraps a TelemetrySource; keeps tracker boundaries in sync with session info.

    `poll()` is called on the scraper thread, so tracker mutation here stays on that
    thread (agent rule 4). Sector-count changes are handed to the event loop.
    """

    def __init__(
        self,
        inner: TelemetrySource,
        tracker: LapSectorTracker,
        stats: SessionStats,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._inner = inner
        self._tracker = tracker
        self._stats = stats
        self._loop = loop
        self._boundaries: list[float] | None = None
        self._signature: str | None = None

    def poll(self) -> TelemetryFrame | None:
        frame = self._inner.poll()
        if frame is None:
            return None
        boundaries = self._inner.sector_boundaries() or SINGLE_SECTOR
        signature = self._inner.session_signature()
        if boundaries != self._boundaries or signature != self._signature:
            first = self._boundaries is None
            self._boundaries = list(boundaries)
            self._signature = signature
            self._tracker.set_boundaries(boundaries)
            if not first:
                # Session/track change (§6.3): re-arm on the next S/F crossing.
                self._tracker.reset(frame)
            log.info("sector boundaries (%s): %s", signature, boundaries)
            self._loop.call_soon_threadsafe(self._set_sector_count, len(boundaries))
        return frame

    def _set_sector_count(self, count: int) -> None:
        if self._stats.sector_count != count:
            self._stats.sector_count = count

    def sector_boundaries(self) -> list[float] | None:
        return self._inner.sector_boundaries()

    def session_signature(self) -> str:
        return self._inner.session_signature()

    def close(self) -> None:
        self._inner.close()


class IRLDSApp:
    def __init__(
        self,
        config: Config,
        fake_source: bool = False,
        source: TelemetrySource | None = None,
        pit_actions: PitActionsLike | None = None,
        fake_lap_time: float = 20.0,
    ) -> None:
        self.config = config
        self._fake = fake_source
        self._source_override = source
        self._pit_override = pit_actions
        self._fake_lap_time = fake_lap_time

        self.server: IRLDSServer | None = None
        self._scraper: ScraperThread | None = None
        self._source: TelemetrySource | None = None
        self._stop_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.started = asyncio.Event()

    # ---- construction ----------------------------------------------------

    def _make_source(self) -> TelemetrySource:
        if self._source_override is not None:
            return self._source_override
        if self._fake:
            from irlds.sources.fake import FakeSource

            return FakeSource(lap_time=self._fake_lap_time)
        from irlds.sources.iracing import IRacingSource

        return IRacingSource()

    def _make_pit_actions(self) -> PitActionsLike:
        if self._pit_override is not None:
            return self._pit_override
        if self._fake:
            return FakePitActions(result=PitResult(ok=True, detail="fake"))
        return PitActions(self.config.pit_actions)

    def _origins(self) -> list[Any]:
        # Config entries extend the localhost default (§10); "null" allows file:// pages.
        return list(DEFAULT_ORIGINS) + list(self.config.server.allowed_origins)

    # ---- lifecycle -------------------------------------------------------

    def run(self) -> None:
        """Blocking entry point. Ctrl+C on Windows surfaces as KeyboardInterrupt."""
        try:
            asyncio.run(self.main())
        finally:
            self.stop()

    def request_stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    async def main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._install_signal_handlers()

        cfg = self.config
        queue: asyncio.Queue[TrackerEvent] = asyncio.Queue()
        stats = SessionStats()
        tracker = LapSectorTracker(count_outlap=cfg.scraper.count_outlap)
        self._source = self._make_source()
        source = BoundarySyncSource(self._source, tracker, stats, self._loop)
        self._scraper = ScraperThread(source, tracker, queue, poll_hz=cfg.scraper.poll_hz)

        self.server = IRLDSServer(
            stats,
            queue,
            reset_hook=self._scraper.request_reset,
            pit_actions=self._make_pit_actions(),
            host=cfg.server.host,
            port=cfg.server.port,
            allowed_origins=self._origins(),
        )

        # Start order (§12): WebSocket server first, then the scraper.
        await self.server.start()
        self._scraper.start(self._loop)
        log.info("IRLDS running (source=%s)", type(self._source).__name__)
        self.started.set()

        try:
            await self._stop_event.wait()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        log.info("shutting down")
        self._remove_signal_handlers()
        scraper, server = self._scraper, self.server
        # Stop the scraper and close the WS server (clients get 1001) concurrently.
        tasks = []
        if scraper is not None:
            tasks.append(asyncio.to_thread(scraper.stop))
        if server is not None:
            tasks.append(server.stop())
        await asyncio.gather(*tasks, return_exceptions=True)
        self._scraper = None
        self.server = None
        if self._source is not None:
            self._source.close()
            self._source = None
        log.info("shutdown complete")

    def stop(self) -> None:
        """Synchronous, idempotent cleanup for paths where the loop is already gone."""
        if self._scraper is not None:
            self._scraper.stop()
            self._scraper = None
        if self._source is not None:
            self._source.close()
            self._source = None

    def _install_signal_handlers(self) -> None:
        if sys.platform == "win32" or self._loop is None or self._stop_event is None:
            return  # Windows: KeyboardInterrupt path via asyncio.run
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._loop.add_signal_handler(sig, self._stop_event.set)
            except (NotImplementedError, RuntimeError, ValueError):
                pass

    def _remove_signal_handlers(self) -> None:
        if sys.platform == "win32" or self._loop is None:
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
