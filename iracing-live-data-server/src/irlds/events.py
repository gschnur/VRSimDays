from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class SectorCompleted:
    event_type: Literal["sector_completed"] = "sector_completed"
    driver_name: str | None = None
    sector_index: int = 0
    time: float = 0.0
    lap_number: int = 0


@dataclass(slots=True)
class LapCompleted:
    event_type: Literal["lap_completed"] = "lap_completed"
    driver_name: str | None = None
    lap_number: int = 0
    lap_time: float = 0.0
    sectors: list[float] = field(default_factory=list)
    valid: bool = True


@dataclass(slots=True)
class ResetCompleted:
    event_type: Literal["reset_completed"] = "reset_completed"
    driver_name: str | None = None


@dataclass(slots=True)
class TrackerInvalidated:
    event_type: Literal["tracker_invalidated"] = "tracker_invalidated"


@dataclass(slots=True)
class StatusChanged:
    event_type: Literal["status_changed"] = "status_changed"
    connected: bool = False


TrackerEvent = SectorCompleted | LapCompleted | ResetCompleted | TrackerInvalidated | StatusChanged
