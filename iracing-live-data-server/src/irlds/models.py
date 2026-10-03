from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TelemetryFrame:
    session_time: float
    lap_dist_pct: float
    lap_completed: int
    lap_current: int
    last_lap_time: float
    on_pit_road: bool
    is_on_track: bool
    connected: bool


@dataclass(slots=True)
class SectorRecord:
    index: int
    time: float
    valid: bool = True


@dataclass(slots=True)
class LapRecord:
    driver_name: str | None
    lap_number: int
    lap_time: float
    sectors: list[SectorRecord] = field(default_factory=list)
    valid: bool = True


@dataclass
class SessionStats:
    driver_name: str | None = None
    current_lap: int = 0
    last_lap: LapRecord | None = None
    best_lap: LapRecord | None = None
    best_lap_number: int = 0
    best_sector_times: list[float | None] = field(default_factory=list)
    optimal_lap_time: float | None = None
    current_lap_sector_times: list[float] = field(default_factory=list)
    lap_count: int = 0
    _sector_count: int = 0

    @property
    def sector_count(self) -> int:
        return self._sector_count

    @sector_count.setter
    def sector_count(self, value: int) -> None:
        # Sector bests from a different layout are meaningless; start them over.
        self._sector_count = value
        self.best_sector_times = [None] * value
        self.optimal_lap_time = None
        self.current_lap_sector_times = []

    def reset(self, driver_name: str | None = None) -> None:
        self.driver_name = driver_name
        self.current_lap = 0
        self.last_lap = None
        self.best_lap = None
        self.best_lap_number = 0
        self.best_sector_times = [None] * self._sector_count
        self.optimal_lap_time = None
        self.current_lap_sector_times = []
        self.lap_count = 0

    def apply_sector(self, index: int, time: float, driver_name: str | None, lap_number: int) -> None:
        """Record a sector of the lap in progress.

        Bests are only committed when the lap completes valid (§16-3): iRacing reports
        lap invalidity at the line, after the lap's sectors have been seen.
        """
        if 0 <= index < self._sector_count:
            self.current_lap = lap_number
            self.current_lap_sector_times.append(time)

    def apply_lap(self, lap_record: LapRecord, driver_name: str | None) -> None:
        self.lap_count += 1
        self.last_lap = lap_record
        # The next lap is now in progress and has no sectors yet.
        self.current_lap = lap_record.lap_number + 1
        self.current_lap_sector_times = []
        if not lap_record.valid:
            return
        if self.best_lap is None or lap_record.lap_time < self.best_lap.lap_time:
            self.best_lap = lap_record
            self.best_lap_number = lap_record.lap_number
        if len(lap_record.sectors) == self._sector_count:
            for i, sector in enumerate(lap_record.sectors):
                best = self.best_sector_times[i]
                if best is None or sector.time < best:
                    self.best_sector_times[i] = sector.time
            self._update_optimal()

    def discard_current_lap(self) -> None:
        """The lap in progress was invalidated (pit entry, teleport, disconnect)."""
        self.current_lap_sector_times = []

    def _update_optimal(self) -> None:
        if self.best_sector_times and all(t is not None for t in self.best_sector_times):
            self.optimal_lap_time = sum(t for t in self.best_sector_times if t is not None)

    def to_snapshot(self, as_of_seq: int | None = None) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "driver_name": self.driver_name,
            "sector_count": self._sector_count,
            "current_lap": self.current_lap,
            "lap_count": self.lap_count,
            "last_lap": _lap_to_dict(self.last_lap) if self.last_lap else None,
            "best_lap": _lap_to_dict(self.best_lap) if self.best_lap else None,
            "best_lap_number": self.best_lap_number,
            "best_sector_times": list(self.best_sector_times),
            "optimal_lap_time": self.optimal_lap_time,
            "current_lap_sectors": list(self.current_lap_sector_times),
        }
        if as_of_seq is not None:
            snapshot["as_of_seq"] = as_of_seq
        return snapshot


def _lap_to_dict(lap: LapRecord | None) -> dict[str, Any] | None:
    if lap is None:
        return None
    return {
        "driver_name": lap.driver_name,
        "lap_number": lap.lap_number,
        "lap_time": lap.lap_time,
        "sectors": [s.time for s in lap.sectors],
        "valid": lap.valid,
    }
