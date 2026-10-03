from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from typing import Any

import pytest

from irlds.sources.iracing import IRacingSource


class FakeIRSDK:
    """Implements only the pyirsdk surface IRLDS is allowed to use (§7.1)."""

    sim_running = True
    instances: list["FakeIRSDK"] = []

    def __init__(self) -> None:
        self.is_initialized = False
        self.is_connected = False
        self.last_session_info_update = 1
        self.startups = 0
        self.shutdowns = 0
        self.vars: dict[str, Any] = {
            "SessionTime": 12.5,
            "LapDistPct": 0.25,
            "LapCompleted": 3,
            "Lap": 4,
            "LapLastLapTime": 91.2,
            "OnPitRoad": False,
            "IsOnTrack": True,
            "SplitTimeInfo": {"Sectors": [{"SectorNum": 0, "SectorStartPct": 0.0}, {"SectorNum": 1, "SectorStartPct": 0.4}]},
        }
        FakeIRSDK.instances.append(self)

    def startup(self) -> bool:
        self.startups += 1
        self.is_initialized = self.is_connected = FakeIRSDK.sim_running
        return self.is_initialized

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.is_initialized = self.is_connected = False

    def freeze_var_buffer_latest(self) -> None:
        pass

    def __getitem__(self, key: str) -> Any:
        return self.vars[key]


@pytest.fixture
def irsdk() -> Iterator[type[FakeIRSDK]]:
    FakeIRSDK.sim_running = True
    FakeIRSDK.instances = []
    module = types.ModuleType("irsdk")
    module.IRSDK = FakeIRSDK  # type: ignore[attr-defined]
    saved = sys.modules.get("irsdk")
    sys.modules["irsdk"] = module
    try:
        yield FakeIRSDK
    finally:
        if saved is None:
            sys.modules.pop("irsdk", None)
        else:
            sys.modules["irsdk"] = saved


def test_poll_reads_frame_and_boundaries(irsdk: type[FakeIRSDK]) -> None:
    src = IRacingSource()
    frame = src.poll()
    assert frame is not None
    assert (frame.session_time, frame.lap_dist_pct, frame.lap_completed, frame.lap_current) == (12.5, 0.25, 3, 4)
    assert frame.last_lap_time == 91.2 and frame.is_on_track and not frame.on_pit_road
    assert src.sector_boundaries() == [0.0, 0.4]
    assert src.session_signature() != ""


def test_startup_retried_until_sim_runs(irsdk: type[FakeIRSDK]) -> None:
    irsdk.sim_running = False
    src = IRacingSource()
    assert src.poll() is None
    assert src.poll() is None
    irsdk.sim_running = True
    assert src.poll() is not None
    assert irsdk.instances[0].startups == 3


def test_connection_loss_shuts_down_and_reconnects(irsdk: type[FakeIRSDK]) -> None:
    src = IRacingSource()
    assert src.poll() is not None
    ir = irsdk.instances[0]
    ir.is_connected = False  # sim closed
    assert src.poll() is None
    assert ir.shutdowns == 1
    assert src.poll() is not None  # startup again
    assert ir.startups == 2


def test_poll_error_disconnects(irsdk: type[FakeIRSDK]) -> None:
    src = IRacingSource()
    assert src.poll() is not None
    ir = irsdk.instances[0]
    del ir.vars["LapDistPct"]
    assert src.poll() is None
    assert ir.shutdowns == 1


@pytest.mark.parametrize(
    "split",
    [None, {}, {"Sectors": []}, {"Sectors": [{"SectorStartPct": 0.1}, {"SectorStartPct": 0.5}]},
     {"Sectors": [{"SectorStartPct": 0.0}, {"SectorStartPct": 0.6}, {"SectorStartPct": 0.3}]}],
)
def test_single_sector_fallback(irsdk: type[FakeIRSDK], split: Any) -> None:
    src = IRacingSource()
    assert src.poll() is not None
    ir = irsdk.instances[0]
    ir.vars["SplitTimeInfo"] = split
    ir.last_session_info_update += 1
    assert src.poll() is not None
    assert src.sector_boundaries() == [0.0]


def test_session_info_only_reread_on_update(irsdk: type[FakeIRSDK]) -> None:
    src = IRacingSource()
    src.poll()
    sig = src.session_signature()
    ir = irsdk.instances[0]
    ir.vars["SplitTimeInfo"] = {"Sectors": [{"SectorStartPct": 0.0}, {"SectorStartPct": 0.3}, {"SectorStartPct": 0.7}]}
    src.poll()
    assert src.sector_boundaries() == [0.0, 0.4]  # unchanged until the update counter moves
    ir.last_session_info_update += 1
    src.poll()
    assert src.sector_boundaries() == [0.0, 0.3, 0.7]
    assert src.session_signature() != sig


def test_missing_pyirsdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "irsdk", None)  # makes `import irsdk` raise ImportError
    src = IRacingSource()
    assert src.poll() is None
    assert src.poll() is None
