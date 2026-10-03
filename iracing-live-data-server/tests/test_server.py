from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect

from irlds.models import SessionStats
from irlds.scraper import ScraperThread
from irlds.server import IRLDSServer
from irlds.sources.fake import FakeSource
from irlds.tracker import LapSectorTracker

Msg = dict[str, Any]


class Harness:
    def __init__(self, server: IRLDSServer) -> None:
        self.server = server

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.server.port}"


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    # FakeSource advances 1/60 s of session time per poll; polling at 240 Hz runs
    # the synthetic car at 4x real time (1 s lap -> 0.25 s wall clock).
    source = FakeSource(lap_time=1.0, sector_splits=[0.33, 0.66])
    boundaries = source.sector_boundaries() or [0.0]
    tracker = LapSectorTracker()
    tracker.set_boundaries(boundaries)
    stats = SessionStats()
    stats.sector_count = len(boundaries)
    queue: asyncio.Queue = asyncio.Queue()

    scraper = ScraperThread(source, tracker, queue, poll_hz=240)
    server = IRLDSServer(stats, queue, reset_hook=scraper.request_reset, host="127.0.0.1", port=0)
    await server.start()
    scraper.start(asyncio.get_running_loop())
    try:
        yield Harness(server)
    finally:
        scraper.stop()
        source.close()
        await server.stop()


async def recv(ws: ClientConnection, timeout: float = 3.0) -> Msg:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def recv_until(ws: ClientConnection, pred: Callable[[Msg], bool], timeout: float = 5.0) -> tuple[Msg, list[Msg]]:
    """Receive until pred matches; return the match and everything received before it."""
    seen: list[Msg] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        msg = await recv(ws, max(0.01, deadline - loop.time()))
        if pred(msg):
            return msg, seen
        seen.append(msg)


async def connect_synced(url: str) -> tuple[ClientConnection, Msg, Msg]:
    ws = await connect(url)
    hello = await recv(ws)
    snapshot = await recv(ws)
    return ws, hello, snapshot


def of_type(t: str) -> Callable[[Msg], bool]:
    return lambda m: m["type"] == t


async def do_reset(ws: ClientConnection, name: Any) -> tuple[Msg, Msg]:
    await ws.send(json.dumps({"type": "reset", "data": {"driver_name": name}}))
    ack, _ = await recv_until(ws, of_type("reset_ack"))
    snap, _ = await recv_until(ws, of_type("snapshot"))
    return ack, snap


class TestConnect:
    async def test_hello_and_snapshot_on_connect(self, harness: Harness) -> None:
        ws, hello, snapshot = await connect_synced(harness.url)
        async with ws:
            assert hello["type"] == "hello"
            assert hello["seq"] is None
            assert hello["data"]["clients"] == 1
            assert hello["data"]["sector_count"] == 3
            assert hello["data"]["driver_name"] is None
            assert "server_version" in hello["data"]
            assert "iracing_connected" in hello["data"]

            assert snapshot["type"] == "snapshot"
            assert snapshot["seq"] is None
            assert isinstance(snapshot["data"]["as_of_seq"], int)
            assert snapshot["data"]["clients"] == 1
            assert snapshot["data"]["driver_name"] is None

    async def test_client_count_status_broadcasts(self, harness: Harness) -> None:
        ws1, _, _ = await connect_synced(harness.url)
        async with ws1:
            ws2, hello2, _ = await connect_synced(harness.url)
            assert hello2["data"]["clients"] == 2
            status, _ = await recv_until(ws1, lambda m: m["type"] == "status" and m["data"]["clients"] == 2)
            assert isinstance(status["seq"], int)

            await ws2.close()
            status, _ = await recv_until(ws1, lambda m: m["type"] == "status" and m["data"]["clients"] == 1)
            assert isinstance(status["seq"], int)


class TestBroadcasts:
    async def test_updates_reach_all_clients_with_increasing_seq(self, harness: Harness) -> None:
        ws1, _, snap1 = await connect_synced(harness.url)
        ws2, _, snap2 = await connect_synced(harness.url)
        async with ws1, ws2:
            await do_reset(ws1, "Driver 1")

            per_client: list[list[Msg]] = []
            for ws, snap in ((ws1, snap1), (ws2, snap2)):
                _, before = await recv_until(ws, of_type("lap_update"))
                msgs = [m for m in before if m["seq"] is not None]
                seqs = [m["seq"] for m in msgs]
                assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
                assert all(s > snap["data"]["as_of_seq"] for s in seqs)
                per_client.append(msgs)

            for msgs in per_client:
                assert any(m["type"] == "sector_update" for m in msgs)

            # Both clients see the same sector_update broadcasts (by seq).
            sec1 = {m["seq"] for m in per_client[0] if m["type"] == "sector_update"}
            sec2 = {m["seq"] for m in per_client[1] if m["type"] == "sector_update"}
            assert sec1 & sec2


class TestReset:
    async def test_reset_ack_and_empty_snapshot(self, harness: Harness) -> None:
        ws, _, _ = await connect_synced(harness.url)
        async with ws:
            await do_reset(ws, "Warmup")
            await recv_until(ws, of_type("lap_update"))  # accumulate some state

            ack, snap = await do_reset(ws, "  Jane Doe  ")
            assert ack["seq"] is None
            assert ack["data"] == {"ok": True, "driver_name": "Jane Doe"}
            assert isinstance(snap["seq"], int)
            assert snap["data"]["as_of_seq"] == snap["seq"]
            d = snap["data"]
            assert d["driver_name"] == "Jane Doe"
            assert d["lap_count"] == 0
            assert d["last_lap"] is None
            assert d["best_lap"] is None
            assert d["optimal_lap_time"] is None
            assert d["best_sector_times"] == [None, None, None]
            assert d["current_lap_sectors"] == []

    async def test_reset_request_id_echoed(self, harness: Harness) -> None:
        ws, _, _ = await connect_synced(harness.url)
        async with ws:
            await ws.send(json.dumps({"type": "reset", "request_id": "r1", "data": {"driver_name": "A"}}))
            ack, _ = await recv_until(ws, of_type("reset_ack"))
            assert ack["request_id"] == "r1"

    @pytest.mark.parametrize("bad", [None, "", "   ", "x" * 65, 42, ["A"]])
    async def test_invalid_driver_name_rejected(self, harness: Harness, bad: Any) -> None:
        ws, _, _ = await connect_synced(harness.url)
        async with ws:
            await do_reset(ws, "Valid Driver")
            await recv_until(ws, of_type("lap_update"))

            data = {} if bad is None else {"driver_name": bad}
            await ws.send(json.dumps({"type": "reset", "data": data}))
            err, between = await recv_until(ws, of_type("error"))
            assert err["seq"] is None
            assert err["data"]["code"] == "invalid_driver_name"
            assert err["data"]["request_type"] == "reset"

            await ws.send(json.dumps({"type": "get_snapshot"}))
            snap, more = await recv_until(ws, lambda m: m["type"] == "snapshot" and m["seq"] is None)
            assert snap["data"]["driver_name"] == "Valid Driver"
            assert snap["data"]["lap_count"] >= 1  # stats not cleared
            assert not any(m["type"] in ("reset_ack", "snapshot") for m in between + more)

    async def test_driver_name_stamped_across_resets(self, harness: Harness) -> None:
        ws, _, _ = await connect_synced(harness.url)
        async with ws:
            _, snap = await do_reset(ws, "Driver 1")
            _, msgs = await recv_until(ws, lambda m: m["type"] == "lap_update" and m["data"]["lap_number"] >= 2)
            for m in msgs:
                if m["type"] in ("sector_update", "lap_update"):
                    assert m["data"]["driver_name"] == "Driver 1"

            await ws.send(json.dumps({"type": "reset", "data": {"driver_name": "Driver 2"}}))
            snap, _ = await recv_until(ws, lambda m: m["type"] == "snapshot" and m["seq"] is not None)
            assert snap["data"]["driver_name"] == "Driver 2"

            last, msgs = await recv_until(ws, lambda m: m["type"] == "lap_update" and m["data"]["lap_number"] >= 2)
            updates = [m for m in msgs + [last] if m["type"] in ("sector_update", "lap_update")]
            assert updates
            assert all(m["data"]["driver_name"] == "Driver 2" for m in updates)


class TestMisc:
    async def test_bad_json_returns_error_without_disconnect(self, harness: Harness) -> None:
        ws, _, _ = await connect_synced(harness.url)
        async with ws:
            await ws.send("{not json")
            err, _ = await recv_until(ws, of_type("error"))
            assert err["data"]["code"] == "bad_json"
            assert err["seq"] is None

            await ws.send(json.dumps({"no_type": True}))
            err, _ = await recv_until(ws, of_type("error"))
            assert err["data"]["code"] == "invalid_message"

            await ws.send(json.dumps({"type": "bogus"}))
            err, _ = await recv_until(ws, of_type("error"))
            assert err["data"]["code"] == "unknown_type"

            await ws.send(json.dumps({"type": "ping", "request_id": "p1"}))
            pong, _ = await recv_until(ws, of_type("pong"))
            assert pong["seq"] is None
            assert pong["request_id"] == "p1"

    async def test_get_snapshot_is_direct(self, harness: Harness) -> None:
        ws, _, _ = await connect_synced(harness.url)
        async with ws:
            await ws.send(json.dumps({"type": "get_snapshot"}))
            snap, _ = await recv_until(ws, lambda m: m["type"] == "snapshot")
            assert snap["seq"] is None
            assert "as_of_seq" in snap["data"]

    async def test_return_to_pits_without_pit_actions(self, harness: Harness) -> None:
        ws, _, _ = await connect_synced(harness.url)
        async with ws:
            await ws.send(json.dumps({"type": "return_to_pits", "data": {}}))
            ack, _ = await recv_until(ws, of_type("pit_ack"))
            assert ack["seq"] is None
            assert ack["data"]["ok"] is False
