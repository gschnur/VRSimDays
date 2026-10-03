from __future__ import annotations

import logging

from irlds.models import TelemetryFrame
from irlds.sources.base import TelemetrySource

log = logging.getLogger("irlds.sources.iracing")


class IRacingSource:
    """pyirsdk-backed telemetry source. Only uses the permitted API surface per spec §7.1."""

    def __init__(self) -> None:
        self._ir: object | None = None
        self._initialized = False
        self._last_session_update: int = 0
        self._boundaries: list[float] | None = None
        self._session_sig: str = ""

    def _ensure_started(self) -> bool:
        try:
            import irsdk
        except ImportError:
            log.error("pyirsdk not installed")
            return False

        if not self._initialized:
            try:
                self._ir = irsdk.IRSDK()
                self._ir.startup()
                self._initialized = True
                log.info("pyirsdk started")
            except Exception as e:
                log.warning("pyirsdk startup failed: %s", e)
                return False

        if self._ir is None:
            return False

        if not getattr(self._ir, "is_initialized", False):
            return False

        if not getattr(self._ir, "is_connected", False):
            return False

        last_update = getattr(self._ir, "last_session_info_update", 0)
        if last_update and last_update != self._last_session_update:
            self._last_session_update = last_update
            self._refresh_session_info()

        return True

    def _refresh_session_info(self) -> None:
        if self._ir is None:
            return
        try:
            split_info = self._ir["SplitTimeInfo"]
            if split_info and "Sectors" in split_info:
                sectors = split_info["Sectors"]
                if sectors and len(sectors) > 1:
                    bounds = [s["SectorStartPct"] for s in sectors]
                    if bounds[0] == 0.0:
                        self._boundaries = bounds
                        log.info("Sector boundaries updated: %s", bounds)
                        return
        except Exception as e:
            log.warning("Failed to read sector boundaries: %s", e)
        if self._boundaries is None:
            self._boundaries = [0.0]
            log.warning("Falling back to single-sector mode")
        try:
            track = self._ir["TrackName"] if self._ir else "unknown"
            self._session_sig = f"{track}-{self._last_session_update}"
        except Exception:
            self._session_sig = f"session-{self._last_session_update}"

    def poll(self) -> TelemetryFrame | None:
        if not self._ensure_started():
            return None

        if self._ir is None:
            return None

        try:
            self._ir.freeze_var_buffer_latest()

            session_time = float(self._ir["SessionTime"])
            lap_dist_pct = float(self._ir["LapDistPct"])
            lap_completed = int(self._ir["LapCompleted"])
            lap_current = int(self._ir["Lap"])
            last_lap_time = float(self._ir["LapLastLapTime"])
            on_pit_road = bool(self._ir["OnPitRoad"])
            is_on_track = bool(self._ir["IsOnTrack"])

            if self._boundaries is None:
                self._refresh_session_info()

            return TelemetryFrame(
                session_time=session_time,
                lap_dist_pct=lap_dist_pct,
                lap_completed=lap_completed,
                lap_current=lap_current,
                last_lap_time=last_lap_time,
                on_pit_road=on_pit_road,
                is_on_track=is_on_track,
                connected=True,
            )
        except Exception as e:
            log.debug("poll error: %s", e)
            self._initialized = False
            self._ir = None
            return None

    def sector_boundaries(self) -> list[float] | None:
        self._ensure_started()
        return self._boundaries

    def session_signature(self) -> str:
        return self._session_sig

    def close(self) -> None:
        if self._ir is not None:
            try:
                self._ir.shutdown()
            except Exception:
                pass
            self._ir = None
            self._initialized = False
