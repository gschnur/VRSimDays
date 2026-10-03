from __future__ import annotations

import logging
from dataclasses import dataclass

from irlds.events import (
    LapCompleted,
    SectorCompleted,
    TrackerEvent,
    TrackerInvalidated,
)
from irlds.models import TelemetryFrame

log = logging.getLogger("irlds.tracker")

# How long (session seconds) to wait after an S/F crossing for iRacing to publish the
# new LapLastLapTime before using whatever value it currently reports (§7.2 item 2).
LAST_LAP_GRACE_S = 2.0

WRAP_HIGH = 0.9
WRAP_LOW = 0.1
TELEPORT_DELTA = 0.5


@dataclass(slots=True)
class _PendingLap:
    """A lap whose S/F crossing has been seen but whose official time is not yet known."""

    lap_number: int
    driver_name: str | None
    crossing_time: float
    sectors: list[float] | None  # None = sector data incomplete (out-lap counted, etc.)
    last_lap_time_before: float


class LapSectorTracker:
    """Pure lap/sector state machine (§6). No I/O; only touched by the scraper thread.

    Sector i spans boundaries[i] -> boundaries[i+1] (last sector wraps to 1.0).
    Crossing boundary i (i >= 1) therefore completes sector i-1; the last sector is
    closed at the S/F line as `lap_time - sum(previous sectors)` (D5).
    """

    def __init__(self, count_outlap: bool = False) -> None:
        self.boundaries: list[float] = [0.0]
        self.count_outlap = count_outlap
        self._prev_pct: float | None = None
        self._prev_time: float | None = None
        self._prev_last_lap_time: float = 0.0
        self._armed: bool = False
        self._last_boundary_time: float | None = None
        self._current_lap_sectors: list[float] = []
        self._laps_counted: int = 0
        self._pending: _PendingLap | None = None
        self._current_driver_name: str | None = None

    def set_driver_name(self, name: str | None) -> None:
        self._current_driver_name = name

    def set_boundaries(self, boundaries: list[float]) -> None:
        self.boundaries = list(boundaries) if boundaries else [0.0]

    @property
    def sector_count(self) -> int:
        return len(self.boundaries)

    # ---- public API ------------------------------------------------------

    def process(self, frame: TelemetryFrame) -> list[TrackerEvent]:
        events: list[TrackerEvent] = []
        self._resolve_pending(frame, events)

        if not frame.connected or not frame.is_on_track or frame.on_pit_road:
            self._invalidate(events)
            self._remember(frame)
            return events

        prev_pct, prev_time = self._prev_pct, self._prev_time
        if prev_pct is None or prev_time is None:
            self._remember(frame)
            return events

        pct, now = frame.lap_dist_pct, frame.session_time

        if self._is_teleport(prev_pct, pct):
            self._invalidate(events)
            self._remember(frame)
            return events

        if prev_pct > WRAP_HIGH and pct < WRAP_LOW:
            cross = self._interpolate_wrap(prev_pct, pct, prev_time, now)
            # Boundaries between prev_pct and the line, then the line, then any
            # boundaries already passed on the new lap (multi-boundary ticks).
            self._cross_segment(prev_pct, prev_time, 1.0, cross, frame, events)
            self._cross_start_finish(cross, frame, events)
            self._cross_segment(0.0, cross, pct, now, frame, events)
        else:
            self._cross_segment(prev_pct, prev_time, pct, now, frame, events)

        self._remember(frame)
        return events

    def reset(self, frame: TelemetryFrame) -> None:
        """Clear everything for a new driver; lap numbering restarts at 1 (D2)."""
        self._laps_counted = 0
        self._pending = None
        self.resume(frame)
        # A counted out-lap has no known start, so its sectors are not reported.
        self._armed = self.count_outlap

    def resume(self, frame: TelemetryFrame) -> None:
        """Re-sync after a telemetry gap: drop the lap in progress, keep lap numbering."""
        self._pending = None
        self._armed = False
        self._last_boundary_time = None
        self._current_lap_sectors = []
        self._remember(frame)

    # ---- internals -------------------------------------------------------

    def _remember(self, frame: TelemetryFrame) -> None:
        self._prev_pct = frame.lap_dist_pct
        self._prev_time = frame.session_time
        self._prev_last_lap_time = frame.last_lap_time

    def _invalidate(self, events: list[TrackerEvent]) -> None:
        if self._armed:
            events.append(TrackerInvalidated())
        self._armed = False
        self._last_boundary_time = None
        self._current_lap_sectors = []

    def _cross_segment(
        self, p0: float, t0: float, p1: float, t1: float, frame: TelemetryFrame, events: list[TrackerEvent]
    ) -> None:
        for i, b in enumerate(self.boundaries):
            if b <= 0.0 or not (p0 < b <= p1):
                continue
            t = t0 if p1 == p0 or t1 == t0 else t0 + (b - p0) / (p1 - p0) * (t1 - t0)
            self._on_boundary(i, t, frame, events)

    def _on_boundary(self, index: int, t: float, frame: TelemetryFrame, events: list[TrackerEvent]) -> None:
        # The previous lap must be finalised before reporting sectors of this one.
        self._resolve_pending(frame, events, force=True)
        if not self._armed:
            return
        sector_index = index - 1
        if self._last_boundary_time is None or sector_index != len(self._current_lap_sectors):
            # Lap start unknown or a boundary was missed: sectors for this lap are partial.
            self._last_boundary_time = None
            return
        sector_time = t - self._last_boundary_time
        self._last_boundary_time = t
        self._current_lap_sectors.append(sector_time)
        events.append(SectorCompleted(
            driver_name=self._current_driver_name,
            sector_index=sector_index,
            time=sector_time,
            lap_number=self._laps_counted + 1,
        ))

    def _cross_start_finish(self, cross: float, frame: TelemetryFrame, events: list[TrackerEvent]) -> None:
        if self._armed:
            self._resolve_pending(frame, events, force=True)
            complete = (
                self._last_boundary_time is not None
                and len(self._current_lap_sectors) == len(self.boundaries) - 1
            )
            self._laps_counted += 1
            self._pending = _PendingLap(
                lap_number=self._laps_counted,
                driver_name=self._current_driver_name,
                crossing_time=cross,
                sectors=list(self._current_lap_sectors) if complete else None,
                last_lap_time_before=self._prev_last_lap_time,
            )
        # Every clean S/F crossing arms tracking for the new lap (out-lap discarded).
        self._armed = True
        self._last_boundary_time = cross
        self._current_lap_sectors = []
        self._resolve_pending(frame, events)

    def _resolve_pending(self, frame: TelemetryFrame, events: list[TrackerEvent], force: bool = False) -> None:
        p = self._pending
        if p is None:
            return
        updated = frame.last_lap_time != p.last_lap_time_before
        timed_out = frame.session_time - p.crossing_time >= LAST_LAP_GRACE_S
        if not (updated or timed_out or force):
            return
        if not updated:
            log.warning("LapLastLapTime did not change after lap %d; using %.3f", p.lap_number, frame.last_lap_time)
        self._pending = None

        lap_time = frame.last_lap_time
        if lap_time <= 0:
            # iRacing reports -1 for invalid laps.
            events.append(LapCompleted(
                driver_name=p.driver_name, lap_number=p.lap_number, lap_time=lap_time, sectors=[], valid=False,
            ))
            return

        sectors: list[float] = []
        if p.sectors is not None:
            final = lap_time - sum(p.sectors)
            events.append(SectorCompleted(
                driver_name=p.driver_name,
                sector_index=len(p.sectors),
                time=final,
                lap_number=p.lap_number,
            ))
            sectors = p.sectors + [final]
        events.append(LapCompleted(
            driver_name=p.driver_name, lap_number=p.lap_number, lap_time=lap_time, sectors=sectors, valid=True,
        ))

    @staticmethod
    def _is_teleport(prev_pct: float, curr_pct: float) -> bool:
        if abs(curr_pct - prev_pct) <= TELEPORT_DELTA:
            return False
        # A forward wrap over S/F is normal; anything else (incl. reversing over the line) is not.
        return not (prev_pct > WRAP_HIGH and curr_pct < WRAP_LOW)

    @staticmethod
    def _interpolate_wrap(prev_pct: float, curr_pct: float, prev_time: float, curr_time: float) -> float:
        if curr_time == prev_time:
            return prev_time
        fraction = (1.0 - prev_pct) / ((1.0 - prev_pct) + curr_pct)
        return prev_time + fraction * (curr_time - prev_time)
