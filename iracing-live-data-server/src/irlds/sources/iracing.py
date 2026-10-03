from __future__ import annotations

import logging
from typing import Any

from irlds.models import TelemetryFrame

log = logging.getLogger("irlds.sources.iracing")

SINGLE_SECTOR = [0.0]


class IRacingSource:
    """pyirsdk-backed telemetry source. Only uses the permitted API surface (§7.1).

    Blocking; called from the scraper thread only.
    """

    def __init__(self) -> None:
        self._ir: Any = None
        self._import_failed = False
        self._connected = False
        self._last_session_update: int | None = None
        self._boundaries: list[float] | None = None
        self._session_sig: str = ""
        self._warned_sigs: set[str] = set()

    # ---- connection ------------------------------------------------------

    def _ensure_connected(self) -> bool:
        if self._ir is None:
            if self._import_failed:
                return False
            try:
                import irsdk
            except ImportError:
                self._import_failed = True
                log.error("pyirsdk not installed; iRacing source unavailable")
                return False
            self._ir = irsdk.IRSDK()

        ir = self._ir
        if ir.is_initialized and ir.is_connected:
            if not self._connected:
                self._connected = True
                log.info("pyirsdk connected")
            return True

        if ir.is_initialized:
            # Was running, sim went away: shut down and retry startup on a later tick.
            self._disconnect()
            return False

        try:
            ir.startup()
        except Exception as e:
            log.debug("pyirsdk startup failed: %s", e)
            return False
        if ir.is_initialized and ir.is_connected:
            self._connected = True
            log.info("pyirsdk connected")
            return True
        return False

    def _disconnect(self) -> None:
        if self._connected:
            log.info("pyirsdk disconnected")
        self._connected = False
        self._last_session_update = None
        if self._ir is not None:
            try:
                self._ir.shutdown()
            except Exception:
                pass

    # ---- session info ----------------------------------------------------

    def _maybe_refresh_session_info(self) -> None:
        update = self._ir.last_session_info_update
        if update == self._last_session_update:
            return
        self._last_session_update = update
        self._boundaries = self._read_boundaries()
        self._session_sig = self._read_signature(self._boundaries)

    def _read_signature(self, boundaries: list[float]) -> str:
        """Track identity from WeekendInfo.TrackID (unique per track configuration).

        Falls back to the sector layout if WeekendInfo is unavailable.
        """
        try:
            weekend = self._ir["WeekendInfo"]
            track_id = weekend["TrackID"] if weekend else None
            if track_id is not None:
                sig = f"track:{track_id}"
                if sig != self._session_sig:
                    name = weekend.get("TrackDisplayName") or weekend.get("TrackName") or "?"
                    config = weekend.get("TrackConfigName") or ""
                    log.info("Track: %s %s (TrackID %s)", name, config, track_id)
                return sig
        except Exception as e:
            log.debug("WeekendInfo unreadable: %s", e)
        return "sectors:" + ",".join(f"{b:.6f}" for b in boundaries)

    def _read_boundaries(self) -> list[float]:
        reason = "missing"
        try:
            split = self._ir["SplitTimeInfo"]
            sectors = split["Sectors"] if split else None
            if sectors:
                bounds = [float(s["SectorStartPct"]) for s in sectors]
                if bounds[0] == 0.0 and all(a < b for a, b in zip(bounds, bounds[1:])) and bounds[-1] < 1.0:
                    if bounds != self._boundaries:
                        log.info("Sector boundaries: %s", bounds)
                    return bounds
                reason = f"malformed {bounds}"
        except Exception as e:
            reason = f"unreadable ({e})"
        sig = f"fallback:{reason}"
        if sig not in self._warned_sigs:
            self._warned_sigs.add(sig)
            log.warning("SplitTimeInfo sectors %s; falling back to single-sector mode", reason)
        return list(SINGLE_SECTOR)

    # ---- TelemetrySource -------------------------------------------------

    def poll(self) -> TelemetryFrame | None:
        if not self._ensure_connected():
            return None
        ir = self._ir
        try:
            ir.freeze_var_buffer_latest()
            self._maybe_refresh_session_info()
            return TelemetryFrame(
                session_time=float(ir["SessionTime"]),
                lap_dist_pct=float(ir["LapDistPct"]),
                lap_completed=int(ir["LapCompleted"]),
                lap_current=int(ir["Lap"]),
                last_lap_time=float(ir["LapLastLapTime"]),
                on_pit_road=bool(ir["OnPitRoad"]),
                is_on_track=bool(ir["IsOnTrack"]),
                connected=True,
            )
        except Exception as e:
            log.warning("poll error, reconnecting: %s", e)
            self._disconnect()
            return None

    def sector_boundaries(self) -> list[float] | None:
        return self._boundaries

    def session_signature(self) -> str:
        return self._session_sig

    def close(self) -> None:
        self._disconnect()
        self._ir = None
