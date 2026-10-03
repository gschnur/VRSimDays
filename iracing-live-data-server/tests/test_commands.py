from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator

import pytest
from websockets.asyncio.client import connect

from irlds.commands import validate_driver_name
from irlds.config import PitActionsConfig
from irlds.models import SessionStats
from irlds.pit_actions import WINDOW_NOT_FOUND, FakePitActions, PitActions, PitResult, WindowNotFound
from irlds.server import IRLDSServer


class FakeDesktop:
    """Stands in for pygetwindow/pyautogui."""

    def __init__(self, window_present: list[bool] | None = None, fail_keys: set[str] | None = None) -> None:
        # Successive focus attempts pop from this list; last value repeats.
        self.window_present = window_present or [True]
        self.fail_keys = fail_keys or set()
        self.focus_calls = 0
        self.hotkeys: list[list[str]] = []
        self._active = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()
        self.hotkey_delay = 0.0

    def focus(self, title: str) -> None:
        present = self.window_present[min(self.focus_calls, len(self.window_present) - 1)]
        self.focus_calls += 1
        if not present:
            raise WindowNotFound(title)

    def hotkey(self, keys: list[str]) -> None:
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            if self.hotkey_delay:
                time.sleep(self.hotkey_delay)
            if set(keys) & self.fail_keys:
                raise RuntimeError(f"cannot send {keys}")
            self.hotkeys.append(keys)
        finally:
            with self._lock:
                self._active -= 1


def make(cfg: PitActionsConfig, desktop: FakeDesktop) -> PitActions:
    return PitActions(cfg, focus_window=desktop.focus, send_hotkey=desktop.hotkey, sleep=lambda s: None)


class TestPitActions:
    async def test_success_primary(self) -> None:
        desktop = FakeDesktop()
        cfg = PitActionsConfig(key_sequence=[["alt", "r"], ["enter"]])
        result = await make(cfg, desktop).return_to_pits()
        assert result == PitResult(ok=True, detail="primary")
        assert desktop.hotkeys == [["alt", "r"], ["enter"]]

    async def test_window_not_found(self) -> None:
        desktop = FakeDesktop(window_present=[False])
        result = await make(PitActionsConfig(), desktop).return_to_pits()
        assert result == PitResult(ok=False, detail=WINDOW_NOT_FOUND)
        assert desktop.focus_calls == 2  # initial + one retry
        assert desktop.hotkeys == []

    async def test_disabled(self) -> None:
        desktop = FakeDesktop()
        result = await make(PitActionsConfig(enabled=False), desktop).return_to_pits()
        assert result == PitResult(ok=False, detail="disabled")
        assert desktop.focus_calls == 0

    async def test_overlapping_calls_are_serialised(self) -> None:
        desktop = FakeDesktop()
        desktop.hotkey_delay = 0.05
        pa = make(PitActionsConfig(), desktop)
        results = await asyncio.gather(*(pa.return_to_pits() for _ in range(3)))
        assert all(r.ok for r in results)
        assert len(desktop.hotkeys) == 3
        assert desktop.max_concurrent == 1

    async def test_fallback_when_primary_raises(self) -> None:
        desktop = FakeDesktop(fail_keys={"r"})
        cfg = PitActionsConfig(key_sequence=[["alt", "r"]], fallback_key_sequence=[["shift", "p"]])
        result = await make(cfg, desktop).return_to_pits()
        assert result == PitResult(ok=True, detail="fallback")
        assert desktop.hotkeys == [["shift", "p"]]

    async def test_fallback_when_window_found_on_retry(self) -> None:
        desktop = FakeDesktop(window_present=[False, True])
        cfg = PitActionsConfig(key_sequence=[["alt", "r"]], fallback_key_sequence=[["shift", "p"]])
        result = await make(cfg, desktop).return_to_pits()
        assert result == PitResult(ok=True, detail="fallback")
        assert desktop.hotkeys == [["shift", "p"]]

    async def test_primary_failure_without_fallback_reports_error(self) -> None:
        desktop = FakeDesktop(fail_keys={"r"})
        result = await make(PitActionsConfig(), desktop).return_to_pits()
        assert result.ok is False
        assert result.detail.startswith("primary failed")

    async def test_fallback_failure_reports_error(self) -> None:
        desktop = FakeDesktop(fail_keys={"r", "p"})
        cfg = PitActionsConfig(key_sequence=[["alt", "r"]], fallback_key_sequence=[["shift", "p"]])
        result = await make(cfg, desktop).return_to_pits()
        assert result.ok is False
        assert result.detail.startswith("fallback failed")


class TestValidateDriverName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Jane", "Jane"),
            ("  Jane Doe \t", "Jane Doe"),
            ("Zoë 🏁", "Zoë 🏁"),
            ("x" * 64, "x" * 64),
            ("x" * 65, None),
            ("", None),
            ("   ", None),
            (None, None),
            (5, None),
        ],
    )
    def test_cases(self, raw: object, expected: str | None) -> None:
        assert validate_driver_name(raw) == expected


@pytest.fixture
async def pit_server() -> AsyncIterator[tuple[IRLDSServer, FakePitActions]]:
    pit = FakePitActions(delay=0.05)
    server = IRLDSServer(SessionStats(), asyncio.Queue(), pit_actions=pit, host="127.0.0.1", port=0)
    await server.start()
    try:
        yield server, pit
    finally:
        await server.stop()


async def _recv_type(ws, t: str) -> dict:  # type: ignore[no-untyped-def]
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if msg["type"] == t:
            return msg


class TestReturnToPitsCommand:
    async def test_pit_ack(self, pit_server: tuple[IRLDSServer, FakePitActions]) -> None:
        server, pit = pit_server
        async with connect(f"ws://127.0.0.1:{server.port}") as ws:
            await ws.send(json.dumps({"type": "return_to_pits", "request_id": "q", "data": {}}))
            ack = await _recv_type(ws, "pit_ack")
            assert ack["seq"] is None
            assert ack["request_id"] == "q"
            assert ack["data"] == {"ok": True, "detail": "primary"}
            assert pit.calls == 1

    async def test_pit_ack_failure_detail(self, pit_server: tuple[IRLDSServer, FakePitActions]) -> None:
        server, pit = pit_server
        pit.result = PitResult(ok=False, detail=WINDOW_NOT_FOUND)
        async with connect(f"ws://127.0.0.1:{server.port}") as ws:
            await ws.send(json.dumps({"type": "return_to_pits"}))
            ack = await _recv_type(ws, "pit_ack")
            assert ack["data"] == {"ok": False, "detail": WINDOW_NOT_FOUND}

    async def test_overlapping_commands_from_two_clients(self, pit_server: tuple[IRLDSServer, FakePitActions]) -> None:
        server, pit = pit_server
        url = f"ws://127.0.0.1:{server.port}"
        async with connect(url) as a, connect(url) as b:
            await a.send(json.dumps({"type": "return_to_pits"}))
            await b.send(json.dumps({"type": "return_to_pits"}))
            acks = await asyncio.gather(_recv_type(a, "pit_ack"), _recv_type(b, "pit_ack"))
            assert all(x["data"]["ok"] for x in acks)
            assert pit.calls == 2
            assert pit.max_concurrent == 1

    async def test_raising_pit_actions_still_acks(self) -> None:
        class Boom:
            async def return_to_pits(self) -> PitResult:
                raise RuntimeError("boom")

        server = IRLDSServer(SessionStats(), asyncio.Queue(), pit_actions=Boom(), host="127.0.0.1", port=0)
        await server.start()
        try:
            async with connect(f"ws://127.0.0.1:{server.port}") as ws:
                await ws.send(json.dumps({"type": "return_to_pits"}))
                ack = await _recv_type(ws, "pit_ack")
                assert ack["data"]["ok"] is False
        finally:
            await server.stop()
