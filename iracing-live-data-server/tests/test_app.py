from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

from websockets.asyncio.client import connect

from irlds.app import IRLDSApp
from irlds.config import Config
from irlds.sources.fake import FakeSource


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def recv_type(ws: Any, t: str, timeout: float = 5.0) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, deadline - loop.time())))
        if msg["type"] == t:
            return msg


def make_app(**kw: Any) -> IRLDSApp:
    cfg = Config()
    cfg.server.port = free_port()
    cfg.scraper.poll_hz = 240  # FakeSource runs at 4x real time
    return IRLDSApp(cfg, **kw)


async def test_fake_source_end_to_end() -> None:
    app = make_app(source=FakeSource(lap_time=1.0, sector_splits=[0.33, 0.66]), fake_source=True)
    task = asyncio.create_task(app.main())
    await asyncio.wait_for(app.started.wait(), 5)
    try:
        async with connect(f"ws://127.0.0.1:{app.config.server.port}") as ws:
            hello = await recv_type(ws, "hello")
            assert hello["data"]["clients"] == 1

            await ws.send(json.dumps({"type": "reset", "data": {"driver_name": "Demo"}}))
            await recv_type(ws, "reset_ack")
            lap = await recv_type(ws, "lap_update")
            assert lap["data"]["driver_name"] == "Demo"
            assert len(lap["data"]["sectors"]) == 3  # boundaries wired from the source

            await ws.send(json.dumps({"type": "get_snapshot"}))
            snap = await recv_type(ws, "snapshot")
            assert snap["data"]["sector_count"] == 3
            assert snap["data"]["iracing_connected"] is True

            await ws.send(json.dumps({"type": "return_to_pits"}))
            ack = await recv_type(ws, "pit_ack")
            assert ack["data"] == {"ok": True, "detail": "fake"}
    finally:
        app.request_stop()
        await asyncio.wait_for(task, 10)
    assert app.server is None


async def test_shutdown_closes_clients_with_1001() -> None:
    app = make_app(source=FakeSource(lap_time=1.0), fake_source=True)
    task = asyncio.create_task(app.main())
    await asyncio.wait_for(app.started.wait(), 5)
    async with connect(f"ws://127.0.0.1:{app.config.server.port}") as ws:
        await recv_type(ws, "hello")
        app.request_stop()
        await asyncio.wait_for(task, 10)
        await asyncio.wait_for(ws.wait_closed(), 5)
        assert ws.close_code == 1001


async def test_server_starts_without_iracing() -> None:
    class Disconnected:
        def poll(self) -> None:
            return None

        def sector_boundaries(self) -> None:
            return None

        def session_signature(self) -> str:
            return ""

        def close(self) -> None:
            pass

    app = make_app(source=Disconnected())
    task = asyncio.create_task(app.main())
    await asyncio.wait_for(app.started.wait(), 5)
    try:
        async with connect(f"ws://127.0.0.1:{app.config.server.port}") as ws:
            hello = await recv_type(ws, "hello")
            assert hello["data"]["iracing_connected"] is False

            # Reset while disconnected still applies (§8).
            await ws.send(json.dumps({"type": "reset", "data": {"driver_name": "Early"}}))
            ack = await recv_type(ws, "reset_ack")
            assert ack["data"]["driver_name"] == "Early"
    finally:
        app.request_stop()
        await asyncio.wait_for(task, 10)


async def test_session_change_updates_sector_count() -> None:
    source = FakeSource(lap_time=1.0, sector_splits=[0.5])
    app = make_app(source=source, fake_source=True)
    task = asyncio.create_task(app.main())
    await asyncio.wait_for(app.started.wait(), 5)
    try:
        async with connect(f"ws://127.0.0.1:{app.config.server.port}") as ws:
            await recv_type(ws, "hello")
            await asyncio.sleep(0.2)
            assert app.server is not None and app.server.stats.sector_count == 2

            # Simulate a track change with no sector info -> single-sector fallback.
            source.missing_sector_info = True
            source._session_sig = "fake-session-2"
            await asyncio.sleep(0.2)
            assert app.server.stats.sector_count == 1
    finally:
        app.request_stop()
        await asyncio.wait_for(task, 10)
