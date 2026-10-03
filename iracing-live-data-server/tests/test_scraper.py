from __future__ import annotations

import asyncio
import pytest

from irlds.events import LapCompleted, ResetCompleted, SectorCompleted, StatusChanged
from irlds.models import TelemetryFrame
from irlds.scraper import ScraperThread
from irlds.sources.fake import FakeSource
from irlds.tracker import LapSectorTracker


class TestScraperWithFakeSource:
    @pytest.mark.asyncio
    async def test_events_arrive_on_queue(self) -> None:
        source = FakeSource(lap_time=2.0, sector_splits=[0.5], num_laps=3)
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.5])
        queue: asyncio.Queue = asyncio.Queue()

        scraper = ScraperThread(source, tracker, queue, poll_hz=60)
        loop = asyncio.get_event_loop()
        scraper.start(loop)

        try:
            await asyncio.sleep(0.2)

            scraper.request_reset("TestDriver")
            await asyncio.sleep(0.5)

            reset_events = []
            while not queue.empty():
                evt = queue.get_nowait()
                if isinstance(evt, ResetCompleted):
                    reset_events.append(evt)
            assert len(reset_events) >= 1
            assert reset_events[-1].driver_name == "TestDriver"

            await asyncio.sleep(4.0)

            lap_events = []
            sector_events = []
            while not queue.empty():
                evt = queue.get_nowait()
                if isinstance(evt, LapCompleted):
                    lap_events.append(evt)
                elif isinstance(evt, SectorCompleted):
                    sector_events.append(evt)

            assert len(lap_events) >= 1
            assert len(sector_events) >= 1
        finally:
            scraper.stop()
            source.close()

    @pytest.mark.asyncio
    async def test_status_changed_on_connect(self) -> None:
        source = FakeSource(lap_time=2.0, num_laps=1)
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0])
        queue: asyncio.Queue = asyncio.Queue()

        scraper = ScraperThread(source, tracker, queue, poll_hz=60)
        loop = asyncio.get_event_loop()
        scraper.start(loop)

        try:
            await asyncio.sleep(0.2)
            status_events = []
            while not queue.empty():
                evt = queue.get_nowait()
                if isinstance(evt, StatusChanged):
                    status_events.append(evt)
            assert len(status_events) >= 1
            assert status_events[0].connected is True
        finally:
            scraper.stop()
            source.close()


class _GappySource:
    """FakeSource that reports 'disconnected' for the first `gap` polls."""

    def __init__(self, gap: int) -> None:
        self.inner = FakeSource(lap_time=1.0, sector_splits=[0.5])
        self.gap = gap
        self.polls = 0

    def poll(self) -> TelemetryFrame | None:
        self.polls += 1
        if self.polls <= self.gap:
            return None
        return self.inner.poll()

    def sector_boundaries(self) -> list[float] | None:
        return self.inner.sector_boundaries()

    def session_signature(self) -> str:
        return self.inner.session_signature()

    def close(self) -> None:
        self.inner.close()


def _drain(queue: asyncio.Queue) -> list:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


class TestScraperDisconnected:
    async def test_reset_while_disconnected_applies_and_rearms(self) -> None:
        source = _GappySource(gap=3)
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.5])
        queue: asyncio.Queue = asyncio.Queue()
        scraper = ScraperThread(source, tracker, queue, poll_hz=240)
        scraper.RETRY_INTERVAL_S = 0.2
        scraper.request_reset("Early")  # queued before the first tick
        scraper.start(asyncio.get_running_loop())
        try:
            await asyncio.sleep(0.1)
            events = _drain(queue)
            # Applied immediately even though no telemetry is available.
            assert [e.driver_name for e in events if isinstance(e, ResetCompleted)] == ["Early"]
            assert source.polls <= 2  # retrying slowly while disconnected

            await asyncio.sleep(1.5)
            events = _drain(queue)
            assert any(isinstance(e, StatusChanged) and e.connected for e in events)
            laps = [e for e in events if isinstance(e, LapCompleted)]
            assert laps, "tracker should be armed after reconnect"
            assert laps[0].lap_number == 1
            assert all(e.driver_name == "Early" for e in laps)
            # No second ResetCompleted when the tracker re-arms.
            assert not any(isinstance(e, ResetCompleted) for e in events)
        finally:
            scraper.stop()
            source.close()

    async def test_stop_is_prompt_while_disconnected(self) -> None:
        source = _GappySource(gap=10**9)
        tracker = LapSectorTracker()
        scraper = ScraperThread(source, tracker, asyncio.Queue(), poll_hz=60)
        scraper.start(asyncio.get_running_loop())
        await asyncio.sleep(0.05)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.to_thread(scraper.stop)
        assert loop.time() - t0 < 0.5
