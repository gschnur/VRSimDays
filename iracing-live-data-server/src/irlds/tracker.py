from __future__ import annotations

import logging
from dataclasses import dataclass, field

from irlds.events import (
    LapCompleted,
    SectorCompleted,
    TrackerEvent,
    TrackerInvalidated,
)
from irlds.models import TelemetryFrame

log = logging.getLogger("irlds.tracker")


class LapSectorTracker:
    def __init__(self, count_outlap: bool = False) -> None:
        self.boundaries: list[float] = []
        self.count_outlap = count_outlap
        self._prev_pct: float | None = None
        self._prev_time: float | None = None
        self._armed: bool = False
        self._baseline_lap_completed: int = 0
        self._current_lap_start_time: float | None = None
        self._current_lap_sectors: list[float] = []
        self._current_driver_name: str | None = None

    def set_driver_name(self, name: str | None) -> None:
        self._current_driver_name = name

    def set_boundaries(self, boundaries: list[float]) -> None:
        self.boundaries = list(boundaries)

    def process(self, frame: TelemetryFrame) -> list[TrackerEvent]:
        events: list[TrackerEvent] = []

        if not frame.connected or not frame.is_on_track:
            if self._armed:
                events.append(TrackerInvalidated())
                self._armed = False
                self._current_lap_sectors = []
                self._current_lap_start_time = None
            self._prev_pct = frame.lap_dist_pct
            self._prev_time = frame.session_time
            return events

        if frame.on_pit_road:
            if self._armed:
                events.append(TrackerInvalidated())
                self._armed = False
                self._current_lap_sectors = []
                self._current_lap_start_time = None
            self._prev_pct = frame.lap_dist_pct
            self._prev_time = frame.session_time
            return events

        prev_pct = self._prev_pct
        prev_time = self._prev_time

        if prev_pct is None or prev_time is None:
            self._prev_pct = frame.lap_dist_pct
            self._prev_time = frame.session_time
            return events

        if self._is_teleport(prev_pct, frame.lap_dist_pct):
            if self._armed:
                events.append(TrackerInvalidated())
                self._armed = False
                self._current_lap_sectors = []
                self._current_lap_start_time = None
            self._prev_pct = frame.lap_dist_pct
            self._prev_time = frame.session_time
            return events

        wrapped = False
        if prev_pct > 0.9 and frame.lap_dist_pct < 0.1:
            crossing_time = self._interpolate_wrap(prev_pct, frame.lap_dist_pct, prev_time, frame.session_time)
            self._current_lap_start_time = crossing_time

            if self._armed and frame.last_lap_time > 0:
                lap_number = frame.lap_completed - self._baseline_lap_completed
                final_sector_time = frame.last_lap_time - sum(self._current_lap_sectors)
                if len(self._current_lap_sectors) < len(self.boundaries):
                    events.append(SectorCompleted(
                        driver_name=self._current_driver_name,
                        sector_index=len(self._current_lap_sectors),
                        time=final_sector_time,
                        lap_number=lap_number,
                    ))
                events.append(LapCompleted(
                    driver_name=self._current_driver_name,
                    lap_number=lap_number,
                    lap_time=frame.last_lap_time,
                    sectors=list(self._current_lap_sectors) + [final_sector_time],
                    valid=True,
                ))
                self._current_lap_sectors = []
                self._armed = True
            elif self._armed and frame.last_lap_time <= 0:
                events.append(LapCompleted(
                    driver_name=self._current_driver_name,
                    lap_number=frame.lap_completed - self._baseline_lap_completed,
                    lap_time=frame.last_lap_time,
                    sectors=[],
                    valid=False,
                ))
                self._current_lap_sectors = []
                self._armed = True
            else:
                if not self.count_outlap:
                    self._armed = True
                self._current_lap_sectors = []
            wrapped = True

        if not wrapped:
            crossed = self._crossed_boundaries(prev_pct, frame.lap_dist_pct, prev_time, frame.session_time)
            for boundary_idx, crossing_t in crossed:
                sector_time = crossing_t - (self._current_lap_start_time or prev_time)
                if self._current_lap_start_time is None:
                    sector_time = 0.0
                if self._armed:
                    events.append(SectorCompleted(
                        driver_name=self._current_driver_name,
                        sector_index=boundary_idx,
                        time=sector_time,
                        lap_number=frame.lap_completed - self._baseline_lap_completed,
                    ))
                    self._current_lap_sectors.append(sector_time)

        self._prev_pct = frame.lap_dist_pct
        self._prev_time = frame.session_time
        return events

    def reset(self, frame: TelemetryFrame) -> None:
        self._armed = False
        self._baseline_lap_completed = frame.lap_completed
        self._prev_pct = frame.lap_dist_pct
        self._prev_time = frame.session_time
        self._current_lap_sectors = []
        self._current_lap_start_time = None

    def _is_teleport(self, prev_pct: float, curr_pct: float) -> bool:
        delta = abs(curr_pct - prev_pct)
        if delta > 0.5:
            if prev_pct > 0.9 and curr_pct < 0.1:
                return False
            if prev_pct < 0.1 and curr_pct > 0.9:
                return True
            return True
        return False

    def _interpolate_wrap(self, prev_pct: float, curr_pct: float, prev_time: float, curr_time: float) -> float:
        if curr_time == prev_time:
            return prev_time
        fraction = (1.0 - prev_pct) / ((1.0 - prev_pct) + curr_pct)
        return prev_time + fraction * (curr_time - prev_time)

    def _crossed_boundaries(self, prev_pct: float, curr_pct: float, prev_time: float, curr_time: float) -> list[tuple[int, float]]:
        results: list[tuple[int, float]] = []
        for i, b in enumerate(self.boundaries):
            if b == 0.0:
                continue
            if prev_pct < b <= curr_pct:
                if curr_time == prev_time:
                    t = prev_time
                else:
                    t = prev_time + (b - prev_pct) / (curr_pct - prev_pct) * (curr_time - prev_time)
                results.append((i, t))
        return results
