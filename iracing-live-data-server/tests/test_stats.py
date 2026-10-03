from __future__ import annotations

import pytest
from irlds.models import SessionStats, LapRecord, SectorRecord


class TestSessionStatsReset:
    def test_initial_state(self) -> None:
        stats = SessionStats()
        assert stats.driver_name is None
        assert stats.current_lap == 0
        assert stats.last_lap is None
        assert stats.best_lap is None
        assert stats.lap_count == 0

    def test_reset_clears_everything(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("Driver A")
        stats.lap_count = 5
        stats.current_lap = 4
        stats.reset("Driver B")
        assert stats.driver_name == "Driver B"
        assert stats.current_lap == 0
        assert stats.last_lap is None
        assert stats.best_lap is None
        assert stats.lap_count == 0
        assert stats.best_sector_times == [None, None, None]
        assert stats.optimal_lap_time is None

    def test_reset_preserves_sector_count(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset()
        assert stats.sector_count == 3


class TestSessionStatsBestLap:
    def test_first_valid_lap_is_best(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("D")
        lap = LapRecord(driver_name="D", lap_number=1, lap_time=95.0, sectors=[SectorRecord(0, 30.0), SectorRecord(1, 32.0), SectorRecord(2, 33.0)])
        stats.apply_lap(lap, "D")
        assert stats.best_lap is lap
        assert stats.best_lap_number == 1

    def test_faster_lap_replaces_best(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("D")
        stats.apply_lap(LapRecord("D", 1, 95.0, [SectorRecord(0, 30.0), SectorRecord(1, 32.0), SectorRecord(2, 33.0)]), "D")
        stats.apply_lap(LapRecord("D", 2, 92.0, [SectorRecord(0, 29.0), SectorRecord(1, 31.0), SectorRecord(2, 32.0)]), "D")
        assert stats.best_lap_number == 2
        assert stats.best_lap.lap_time == 92.0

    def test_invalid_lap_not_best(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("D")
        stats.apply_lap(LapRecord("D", 1, 95.0, [], valid=True), "D")
        stats.apply_lap(LapRecord("D", 2, 90.0, [], valid=False), "D")
        assert stats.best_lap_number == 1


class TestSessionStatsOptimal:
    def test_optimal_computed_when_all_sectors_have_values(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("D")
        stats.apply_sector(0, 30.0, "D", 1)
        stats.apply_sector(1, 31.0, "D", 1)
        stats.apply_sector(2, 30.5, "D", 1)
        assert stats.optimal_lap_time == pytest.approx(91.5)

    def test_optimal_is_none_when_sector_missing(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("D")
        stats.apply_sector(0, 30.0, "D", 1)
        assert stats.optimal_lap_time is None


class TestSessionStatsSnapshot:
    def test_snapshot_contains_driver(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("Jane")
        snap = stats.to_snapshot(as_of_seq=10)
        assert snap["driver_name"] == "Jane"
        assert snap["as_of_seq"] == 10
        assert snap["sector_count"] == 3

    def test_snapshot_empty_after_reset(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("X")
        snap = stats.to_snapshot()
        assert snap["lap_count"] == 0
        assert snap["last_lap"] is None
        assert snap["best_lap"] is None


class TestSessionStatsSectorBest:
    def test_best_sector_improves(self) -> None:
        stats = SessionStats()
        stats.sector_count = 3
        stats.reset("D")
        stats.apply_sector(0, 31.0, "D", 1)
        assert stats.best_sector_times[0] == 31.0
        stats.apply_sector(0, 30.0, "D", 2)
        assert stats.best_sector_times[0] == 30.0
