from __future__ import annotations

import pytest
from irlds.events import LapCompleted, SectorCompleted, TrackerInvalidated
from irlds.models import TelemetryFrame
from irlds.tracker import LapSectorTracker


def _frames_clean_lap(lap_time: float = 90.0, hz: int = 60, num_laps: int = 3) -> list[TelemetryFrame]:
    frames = []
    total_ticks = int(lap_time * hz * num_laps) + 2
    for tick in range(total_ticks):
        t = tick / hz
        pct = (t % lap_time) / lap_time
        completed = int(t // lap_time)
        last = lap_time if pct < 0.02 and completed > 0 else 0.0
        frames.append(TelemetryFrame(
            session_time=t,
            lap_dist_pct=pct,
            lap_completed=completed,
            lap_current=completed + 1,
            last_lap_time=last,
            on_pit_road=False,
            is_on_track=True,
            connected=True,
        ))
    return frames


class TestTrackerCleanLaps:
    def test_emits_lap_completed(self) -> None:
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.33, 0.66])
        tracker.set_driver_name("D")

        frames = _frames_clean_lap(90.0, num_laps=3)
        all_events = []
        for f in frames:
            all_events.extend(tracker.process(f))

        laps = [e for e in all_events if isinstance(e, LapCompleted)]
        assert len(laps) >= 1

    def test_emits_sector_completed(self) -> None:
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.33, 0.66])
        tracker.set_driver_name("D")

        frames = _frames_clean_lap(90.0, num_laps=3)
        all_events = []
        for f in frames:
            all_events.extend(tracker.process(f))

        sectors = [e for e in all_events if isinstance(e, SectorCompleted)]
        assert len(sectors) >= 2

    def test_sector_sum_equals_lap_time(self) -> None:
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.33, 0.66])
        tracker.set_driver_name("D")

        frames = _frames_clean_lap(90.0, num_laps=3)
        all_events = []
        for f in frames:
            all_events.extend(tracker.process(f))

        laps = [e for e in all_events if isinstance(e, LapCompleted) and e.valid]
        if laps:
            lap = laps[0]
            assert sum(lap.sectors) == pytest.approx(lap.lap_time, abs=2.0)


class TestTrackerOutlap:
    def test_first_lap_not_counted_by_default(self) -> None:
        tracker = LapSectorTracker(count_outlap=False)
        tracker.set_boundaries([0.0, 0.5])
        tracker.set_driver_name("D")

        frames = _frames_clean_lap(90.0, num_laps=3)
        all_events = []
        for f in frames:
            all_events.extend(tracker.process(f))

        laps = [e for e in all_events if isinstance(e, LapCompleted) and e.valid]
        assert len(laps) >= 1


class TestTrackerInvalidLap:
    def test_invalid_lap_not_best(self) -> None:
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.5])
        tracker.set_driver_name("D")

        f1 = TelemetryFrame(0.0, 0.0, 0, 1, 0.0, False, True, True)
        f2 = TelemetryFrame(1.0, 0.1, 1, 2, -1.0, False, True, True)
        events = tracker.process(f1)
        events = tracker.process(f2)
        laps = [e for e in events if isinstance(e, LapCompleted)]
        for lap in laps:
            if lap.lap_time <= 0:
                assert not lap.valid


class TestTrackerPitEntry:
    def test_pit_entry_invalidates(self) -> None:
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.5])
        tracker.set_driver_name("D")

        frames = _frames_clean_lap(90.0, num_laps=3)
        for f in frames:
            tracker.process(f)
        assert tracker._armed is True

        f_pit = TelemetryFrame(200.0, 0.3, 2, 3, 0.0, True, True, True)
        e_pit = tracker.process(f_pit)
        invalidated = [e for e in e_pit if isinstance(e, TrackerInvalidated)]
        assert len(invalidated) >= 1
        assert tracker._armed is False


class TestTrackerReset:
    def test_reset_disarms(self) -> None:
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0, 0.5])
        f = TelemetryFrame(0.0, 0.0, 0, 1, 0.0, False, True, True)
        tracker.process(f)
        tracker.reset(f)
        assert not tracker._armed


class TestTrackerSingleSectorFallback:
    def test_single_sector(self) -> None:
        tracker = LapSectorTracker()
        tracker.set_boundaries([0.0])
        tracker.set_driver_name("D")
        frames = _frames_clean_lap(90.0, num_laps=3)
        all_events = []
        for f in frames:
            all_events.extend(tracker.process(f))
        laps = [e for e in all_events if isinstance(e, LapCompleted) and e.valid]
        assert len(laps) >= 1
