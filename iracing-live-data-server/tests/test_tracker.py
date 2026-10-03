from __future__ import annotations

from dataclasses import replace

import pytest

from irlds.events import LapCompleted, SectorCompleted, TrackerEvent, TrackerInvalidated
from irlds.models import TelemetryFrame
from irlds.tracker import LAST_LAP_GRACE_S, LapSectorTracker

MS = 1e-3


def drive(
    lap_time: float = 90.0,
    hz: int = 60,
    laps: float = 3.0,
    start_pct: float = 0.0,
    start_completed: int = 0,
    lag_ticks: int = 0,
    reported: dict[int, float] | None = None,
    t0: float = 100.0,
) -> list[TelemetryFrame]:
    """Constant-speed car. LapLastLapTime updates `lag_ticks` after LapCompleted increments.

    `reported` overrides the published lap time keyed by the absolute LapCompleted value.
    """
    reported = reported or {}
    frames: list[TelemetryFrame] = []
    last = 0.0
    pending: list[tuple[int, float]] = []
    prev_completed = start_completed
    for tick in range(int(round(laps * lap_time * hz)) + 1):
        dist = start_pct + tick / (hz * lap_time)
        whole = int(dist + 1e-9)
        completed = start_completed + whole
        pct = max(0.0, dist - whole)
        if completed > prev_completed:
            pending.append((tick + lag_ticks, reported.get(completed, lap_time)))
            prev_completed = completed
        for item in list(pending):
            if tick >= item[0]:
                last = item[1]
                pending.remove(item)
        frames.append(TelemetryFrame(
            session_time=t0 + tick / hz,
            lap_dist_pct=pct,
            lap_completed=completed,
            lap_current=completed + 1,
            last_lap_time=last,
            on_pit_road=False,
            is_on_track=True,
            connected=True,
        ))
    return frames


def run(tracker: LapSectorTracker, frames: list[TelemetryFrame], reset: bool = True) -> list[TrackerEvent]:
    events: list[TrackerEvent] = []
    if reset:
        tracker.reset(frames[0])
        frames = frames[1:]
    for f in frames:
        events.extend(tracker.process(f))
    return events


def make(boundaries: list[float], **kw: bool) -> LapSectorTracker:
    t = LapSectorTracker(**kw)
    t.set_boundaries(boundaries)
    t.set_driver_name("D")
    return t


def laps_of(events: list[TrackerEvent]) -> list[LapCompleted]:
    return [e for e in events if isinstance(e, LapCompleted)]


def sectors_of(events: list[TrackerEvent]) -> list[SectorCompleted]:
    return [e for e in events if isinstance(e, SectorCompleted)]


class TestCleanLaps:
    def test_laps_numbered_from_one_with_exact_sectors(self) -> None:
        events = run(make([0.0, 0.33, 0.66]), drive(laps=4.1))
        laps = laps_of(events)
        assert [l.lap_number for l in laps] == [1, 2, 3]
        for lap in laps:
            assert lap.valid
            assert lap.lap_time == 90.0
            assert lap.sectors == pytest.approx([29.7, 29.7, 30.6], abs=MS)
            assert sum(lap.sectors) == pytest.approx(lap.lap_time, abs=MS)

    def test_sector_events_in_order_with_lap_numbers(self) -> None:
        events = run(make([0.0, 0.33, 0.66]), drive(laps=3.1))
        secs = [(s.lap_number, s.sector_index) for s in sectors_of(events)]
        assert secs == [(1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
        # Last sector of a lap is reported right before its LapCompleted.
        kinds = [type(e).__name__ for e in events]
        assert kinds[:4] == ["SectorCompleted", "SectorCompleted", "SectorCompleted", "LapCompleted"]

    def test_single_sector_fallback(self) -> None:
        events = run(make([0.0]), drive(laps=3.1))
        laps = laps_of(events)
        assert [l.lap_number for l in laps] == [1, 2]
        assert laps[0].sectors == pytest.approx([90.0])
        secs = sectors_of(events)
        assert [(s.sector_index, round(s.time, 3)) for s in secs] == [(0, 90.0), (0, 90.0)]


class TestMultiBoundaryTick:
    def test_several_interior_boundaries_in_one_tick(self) -> None:
        # 1 Hz, 10 s lap: each tick moves 0.1; 0.33 -> 0.43 crosses three boundaries.
        b = [0.0, 0.34, 0.36, 0.38, 0.95]
        events = run(make(b), drive(lap_time=10.0, hz=1, laps=2.5, start_pct=0.03))
        lap = laps_of(events)[0]
        assert lap.sectors == pytest.approx([3.4, 0.2, 0.2, 5.7, 0.5], abs=MS)
        assert [s.sector_index for s in sectors_of(events) if s.lap_number == 1] == [0, 1, 2, 3, 4]

    def test_boundary_and_line_in_same_tick(self) -> None:
        # 0.93 -> 0.03 crosses the 0.95 boundary and the S/F line in one tick.
        events = run(make([0.0, 0.5, 0.95]), drive(lap_time=10.0, hz=1, laps=3.5, start_pct=0.03))
        laps = laps_of(events)
        assert len(laps) == 2
        for lap in laps:
            assert lap.sectors == pytest.approx([5.0, 4.5, 0.5], abs=MS)


class TestOutLap:
    def test_out_lap_discarded_after_mid_lap_reset(self) -> None:
        events = run(make([0.0, 0.5]), drive(laps=3.0, start_pct=0.5, start_completed=7))
        laps = laps_of(events)
        assert [l.lap_number for l in laps] == [1, 2]
        assert all(l.sectors == pytest.approx([45.0, 45.0], abs=MS) for l in laps)

    def test_count_outlap_reports_lap_without_sectors(self) -> None:
        events = run(make([0.0, 0.5], count_outlap=True), drive(laps=1.9, start_pct=0.5))
        laps = laps_of(events)
        assert [l.lap_number for l in laps] == [1, 2]
        assert laps[0].valid and laps[0].sectors == []
        assert laps[1].sectors == pytest.approx([45.0, 45.0], abs=MS)
        assert all(s.lap_number == 2 for s in sectors_of(events))


class TestInvalidLap:
    def test_invalid_lap_reported_and_numbering_continues(self) -> None:
        # Absolute LapCompleted 2 is counted lap 1 (lap 1 is the out-lap).
        events = run(make([0.0, 0.5]), drive(laps=4, reported={3: -1.0}))
        laps = laps_of(events)
        assert [(l.lap_number, l.valid) for l in laps] == [(1, True), (2, False), (3, True)]
        assert laps[1].lap_time == -1.0
        assert laps[1].sectors == []
        # The invalid lap gets no final-sector event.
        assert [s.lap_number for s in sectors_of(events) if s.sector_index == 1] == [1, 3]


class TestInvalidation:
    def test_pit_entry_mid_lap(self) -> None:
        frames = drive(laps=5.1)
        hz, lap = 60, 90.0
        # Pit road for 10 s in the middle of counted lap 2 (absolute lap 3).
        start = int((2 * lap + 30) * hz)
        for i in range(start, start + 10 * hz):
            frames[i] = replace(frames[i], on_pit_road=True)
        events = run(make([0.0, 0.5]), frames)
        assert sum(isinstance(e, TrackerInvalidated) for e in events) == 1
        laps = laps_of(events)
        # Lap 2 is lost (rest of it is the out-lap from the pits); numbering continues.
        assert [l.lap_number for l in laps] == [1, 2, 3]
        assert all(l.sectors == pytest.approx([45.0, 45.0], abs=MS) for l in laps)

    def test_teleport_mid_lap(self) -> None:
        frames = drive(laps=4.1)
        i = int((90 + 20) * 60)
        frames[i] = replace(frames[i], lap_dist_pct=0.9)
        events = run(make([0.0, 0.5]), frames)
        assert any(isinstance(e, TrackerInvalidated) for e in events)
        laps = laps_of(events)
        # The teleported lap is discarded; the next lap is an out-lap.
        assert [l.lap_number for l in laps] == [1, 2]

    def test_reversing_over_line_is_teleport(self) -> None:
        tracker = make([0.0, 0.5])
        frames = drive(laps=2.5)
        run(tracker, frames)
        assert tracker._armed
        f = frames[-1]
        tracker.process(replace(f, lap_dist_pct=0.05, session_time=f.session_time + 1))
        events = tracker.process(replace(f, lap_dist_pct=0.97, session_time=f.session_time + 2))
        assert any(isinstance(e, TrackerInvalidated) for e in events)
        assert not laps_of(events)

    def test_off_track_invalidates(self) -> None:
        frames = drive(laps=3)
        i = int((90 + 20) * 60)
        frames[i] = replace(frames[i], is_on_track=False)
        events = run(make([0.0, 0.5]), frames)
        assert sum(isinstance(e, TrackerInvalidated) for e in events) == 1
        assert laps_of(events) == []


class TestReset:
    def test_reset_mid_lap_restarts_numbering(self) -> None:
        tracker = make([0.0, 0.5])
        frames = drive(laps=5.1)
        mid = int((2 * 90 + 60) * 60)
        first = run(tracker, frames[:mid])
        assert [l.lap_number for l in laps_of(first)] == [1]
        tracker.set_driver_name("E")
        tracker.reset(frames[mid])
        second = run(tracker, frames[mid + 1:], reset=False)
        laps = laps_of(second)
        assert [l.lap_number for l in laps] == [1, 2]
        assert all(l.driver_name == "E" for l in laps)
        assert all(s.driver_name == "E" for s in sectors_of(second))

    def test_reset_disarms(self) -> None:
        tracker = make([0.0, 0.5])
        frames = drive(laps=2.5)
        run(tracker, frames)
        assert tracker._armed
        tracker.reset(frames[-1])
        assert not tracker._armed

    def test_resume_keeps_numbering(self) -> None:
        tracker = make([0.0, 0.5])
        frames = drive(laps=6)
        cut = int((2 * 90 + 10) * 60)
        run(tracker, frames[:cut])
        tracker.resume(frames[cut + 600])  # 10 s telemetry gap
        events = run(tracker, frames[cut + 601:], reset=False)
        # Remainder of lap 2 lost, lap 3 is an out-lap, lap 4 continues numbering at 2.
        assert [l.lap_number for l in laps_of(events)] == [2, 3]


class TestLastLapTimeTiming:
    def test_lagged_last_lap_time_uses_new_value(self) -> None:
        events = run(make([0.0, 0.5]), drive(laps=4, lag_ticks=5, reported={2: 90.25, 3: 90.5}))
        laps = laps_of(events)
        assert [l.lap_time for l in laps] == [90.25, 90.5]
        for lap in laps:
            assert sum(lap.sectors) == pytest.approx(lap.lap_time, abs=MS)
            assert lap.sectors[0] == pytest.approx(45.0, abs=MS)

    def test_unchanged_value_resolves_after_grace(self) -> None:
        # Same published value twice in a row (e.g. identical lap time): wait out the grace.
        tracker = make([0.0, 0.5])
        hz = 60
        frames = drive(laps=3.5, hz=hz)
        crossing = int(3 * 90 * hz)  # counted lap 2 completes here
        before = laps_of(run(tracker, frames[: crossing + int((LAST_LAP_GRACE_S - 0.5) * hz)]))
        assert [l.lap_number for l in before] == [1]
        after = laps_of(run(tracker, frames[crossing + int((LAST_LAP_GRACE_S - 0.5) * hz):], reset=False))
        assert [l.lap_number for l in after] == [2]
        assert after[0].lap_time == 90.0

    def test_pending_lap_keeps_driver_at_crossing(self) -> None:
        tracker = make([0.0, 0.5])
        frames = drive(laps=2.5, lag_ticks=30)
        crossing = int(2 * 90 * 60)  # counted lap 1 completes here
        run(tracker, frames[: crossing + 5])
        tracker.set_driver_name("Next")
        events = run(tracker, frames[crossing + 5:], reset=False)
        lap = laps_of(events)[0]
        assert lap.driver_name == "D"
