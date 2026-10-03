from __future__ import annotations

import json
import time
from typing import Any

from irlds.events import TrackerEvent

_seq_counter = 0


def next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def reset_seq_counter() -> None:
    global _seq_counter
    _seq_counter = 0


def encode(msg_type: str, data: dict[str, Any] | None = None, seq: int | None = None, request_id: str | None = None) -> str:
    envelope: dict[str, Any] = {
        "type": msg_type,
        "seq": seq,
        "ts": time.time(),
    }
    if data is not None:
        envelope["data"] = data
    if request_id is not None:
        envelope["request_id"] = request_id
    return json.dumps(envelope)


def decode(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError("expected string")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("expected JSON object")
    if "type" not in obj:
        raise ValueError("missing 'type' field")
    return obj


def event_to_sector_update_data(event: TrackerEvent, stats_snapshot: dict[str, Any]) -> dict[str, Any]:
    from irlds.events import SectorCompleted
    if not isinstance(event, SectorCompleted):
        raise ValueError("expected SectorCompleted")
    return {
        "driver_name": event.driver_name,
        "sector": event.sector_index + 1,
        "time": event.time,
        "lap_number": event.lap_number,
        "current_lap_sectors": stats_snapshot.get("current_lap_sectors", []),
        "best_sector_times": stats_snapshot.get("best_sector_times", []),
        "optimal_lap_time": stats_snapshot.get("optimal_lap_time"),
    }


def event_to_lap_update_data(event: TrackerEvent, stats_snapshot: dict[str, Any]) -> dict[str, Any]:
    from irlds.events import LapCompleted
    if not isinstance(event, LapCompleted):
        raise ValueError("expected LapCompleted")
    return {
        "driver_name": event.driver_name,
        "lap_number": event.lap_number,
        "lap_time": event.lap_time,
        "valid": event.valid,
        "sectors": event.sectors,
        "best_lap_time": stats_snapshot["best_lap"]["lap_time"] if stats_snapshot.get("best_lap") else None,
        "best_lap_number": stats_snapshot.get("best_lap_number"),
        "best_sector_times": stats_snapshot.get("best_sector_times", []),
        "optimal_lap_time": stats_snapshot.get("optimal_lap_time"),
        "current_lap": stats_snapshot.get("current_lap"),
    }
