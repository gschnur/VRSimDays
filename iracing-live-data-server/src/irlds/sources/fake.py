from __future__ import annotations

import time
import math

from irlds.models import TelemetryFrame
from irlds.sources.base import TelemetrySource


class FakeSource:
    """Scripted telemetry source for testing without iRacing."""

    def __init__(
        self,
        lap_time: float = 90.0,
        sector_splits: list[float] | None = None,
        num_laps: int = 999,
        include_pit_entry: bool = False,
        include_invalid_lap: bool = False,
        include_teleport: bool = False,
        missing_sector_info: bool = False,
    ) -> None:
        self.lap_time = lap_time
        self.sector_splits = sector_splits if sector_splits is not None else [0.33, 0.66]
        self.num_laps = num_laps
        self.include_pit_entry = include_pit_entry
        self.include_invalid_lap = include_invalid_lap
        self.include_teleport = include_teleport
        self.missing_sector_info = missing_sector_info

        self._tick = 0
        self._running = True
        self._session_sig = "fake-session-1"

        sector_times: list[float] = []
        if self.sector_splits:
            prev = 0.0
            for sp in self.sector_splits:
                frac = (sp - prev)
                sector_times.append(self.lap_time * frac)
            frac = 1.0 - self.sector_splits[-1]
            sector_times.append(self.lap_time * frac)
        else:
            sector_times = [self.lap_time]
        self._sector_times = sector_times

        boundaries: list[float] = [0.0] + list(self.sector_splits)
        self._boundaries = boundaries

    def poll(self) -> TelemetryFrame | None:
        if not self._running:
            return None

        hz = 60
        dt = 1.0 / hz
        session_time = self._tick * dt

        lap_progress = (session_time % self.lap_time) / self.lap_time
        lap_completed = int(session_time // self.lap_time)
        lap_current = lap_completed + 1

        if lap_completed >= self.num_laps:
            return None

        on_pit_road = False
        is_on_track = True
        last_lap_time = 0.0

        if self.include_pit_entry and lap_completed == self.num_laps - 1 and lap_progress > 0.9:
            on_pit_road = True
            is_on_track = False

        if lap_progress < 0.02:
            last_lap_time = self.lap_time if (not self.include_invalid_lap or lap_completed != 1) else -1.0

        if self.include_teleport and self._tick == 500:
            lap_progress = 0.5

        self._tick += 1
        return TelemetryFrame(
            session_time=session_time,
            lap_dist_pct=lap_progress,
            lap_completed=lap_completed,
            lap_current=lap_current,
            last_lap_time=last_lap_time,
            on_pit_road=on_pit_road,
            is_on_track=is_on_track,
            connected=True,
        )

    def sector_boundaries(self) -> list[float] | None:
        if self.missing_sector_info:
            return None
        return list(self._boundaries)

    def session_signature(self) -> str:
        return self._session_sig

    def close(self) -> None:
        self._running = False
