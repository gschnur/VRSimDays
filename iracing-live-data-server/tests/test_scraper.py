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
