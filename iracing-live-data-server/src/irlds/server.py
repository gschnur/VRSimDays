from __future__ import annotations

import asyncio
import logging
import re
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable

import websockets
from websockets.asyncio.server import Server, ServerConnection, serve

from irlds.commands import CommandHandler, PitActionsLike
from irlds.events import (
    LapCompleted,
    ResetCompleted,
    SectorCompleted,
    StatusChanged,
    TrackerEvent,
    TrackerInvalidated,
)
from irlds.models import LapRecord, SectorRecord, SessionStats
from irlds.protocol import encode, event_to_lap_update_data, event_to_sector_update_data

log = logging.getLogger("irlds.server")

try:
    SERVER_VERSION = version("irlds")
except PackageNotFoundError:
    SERVER_VERSION = "0.0.0"

# Default origin policy: any localhost page, plus clients that send no Origin header.
DEFAULT_ORIGINS: list[str | re.Pattern[str] | None] = [
    re.compile(r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"),
    None,
]

ResetHook = Callable[[str], None]


class IRLDSServer:
    """WebSocket server, client set, broadcasts and the event consumer.

    Everything here runs on the asyncio event loop (agent rule 4): `stats` and the
    client sets are only touched from this loop.
    """

    def __init__(
        self,
        stats: SessionStats,
        event_queue: asyncio.Queue[TrackerEvent],
        reset_hook: ResetHook | None = None,
        pit_actions: PitActionsLike | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        allowed_origins: list[str] | None = None,
    ) -> None:
        self.stats = stats
        self._queue = event_queue
        self._reset_hook = reset_hook
        self._host = host
        self._port = port
        self._origins: list[Any] = list(allowed_origins) if allowed_origins else list(DEFAULT_ORIGINS)
        self.commands = CommandHandler(self, pit_actions)

        # All connected clients (for the `clients` count).
        self._clients: set[ServerConnection] = set()
        # Clients that have received hello + snapshot and now receive broadcasts.
        self._synced: set[ServerConnection] = set()
        self._seq = 0
        self.iracing_connected = False
        self._pending_reset_acks: list[tuple[ServerConnection, str | None]] = []

        self._server: Server | None = None
        self._consumer_task: asyncio.Task[None] | None = None

    # ---- lifecycle -------------------------------------------------------

    @property
    def port(self) -> int:
        """Actual bound port (useful when started with port 0)."""
        if self._server is None:
            return self._port
        return int(next(iter(self._server.sockets)).getsockname()[1])

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def start(self) -> None:
        self._server = await serve(
            self._handler,
            self._host,
            self._port,
            origins=self._origins,
            ping_interval=20,
        )
        self._consumer_task = asyncio.create_task(self.event_consumer(), name="event_consumer")
        log.info("WebSocket server listening on ws://%s:%d", self._host, self.port)

    async def stop(self) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
        if self._server is not None:
            self._server.close()  # closes clients with 1001 (going away)
            await self._server.wait_closed()
            self._server = None

    # ---- connections -----------------------------------------------------

    async def _handler(self, ws: ServerConnection) -> None:
        self._clients.add(ws)
        log.info("client connected: %s (total %d)", ws.remote_address, len(self._clients))
        try:
            # Other clients learn the new count; the new client gets it in hello/snapshot.
            self.broadcast_status()
            await ws.send(encode("hello", self._hello_data(), seq=None))
            await ws.send(self.snapshot_message())
            # Broadcasts missed between building the snapshot and here are recovered by
            # the client's seq-gap detection.
            self._synced.add(ws)
            async for raw in ws:
                await self.commands.handle(ws, raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            self._synced.discard(ws)
            self._pending_reset_acks = [(c, r) for c, r in self._pending_reset_acks if c is not ws]
            log.info("client disconnected: %s (total %d)", ws.remote_address, len(self._clients))
            self.broadcast_status()

    def _hello_data(self) -> dict[str, Any]:
        return {
            "server_version": SERVER_VERSION,
            "sector_count": self.stats.sector_count,
            "iracing_connected": self.iracing_connected,
            "driver_name": self.stats.driver_name,
            "clients": len(self._clients),
        }

    def _snapshot_data(self) -> dict[str, Any]:
        data = self.stats.to_snapshot(as_of_seq=self._seq)
        data["iracing_connected"] = self.iracing_connected
        data["clients"] = len(self._clients)
        return data

    def snapshot_message(self, request_id: str | None = None) -> str:
        """Direct-reply snapshot (seq: null)."""
        return encode("snapshot", self._snapshot_data(), seq=None, request_id=request_id)

    # ---- broadcasts ------------------------------------------------------

    def broadcast(self, msg_type: str, data: dict[str, Any]) -> int:
        """Send to all synced clients with the next seq. Returns the seq."""
        self._seq += 1
        websockets.broadcast(self._synced, encode(msg_type, data, seq=self._seq))
        return self._seq

    def broadcast_status(self) -> None:
        self.broadcast("status", {"iracing_connected": self.iracing_connected, "clients": len(self._clients)})

    def _broadcast_snapshot(self) -> None:
        # The snapshot reflects everything up to and including itself: as_of_seq == seq.
        data = self._snapshot_data()
        data["as_of_seq"] = self._seq + 1
        self.broadcast("snapshot", data)

    # ---- commands --------------------------------------------------------

    def request_reset(self, ws: ServerConnection, driver_name: str, request_id: str | None) -> None:
        """Called by CommandHandler with an already-validated name."""
        self._pending_reset_acks.append((ws, request_id))
        if self._reset_hook is not None:
            self._reset_hook(driver_name)
        else:
            # No scraper: apply directly through the normal event path.
            self._queue.put_nowait(ResetCompleted(driver_name=driver_name))

    # ---- event consumer --------------------------------------------------

    async def event_consumer(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self.apply_event(event)
            except Exception as e:
                log.error("event_consumer failed on %r: %s", event, e, exc_info=True)

    async def apply_event(self, event: TrackerEvent) -> None:
        stats = self.stats
        if isinstance(event, SectorCompleted):
            stats.apply_sector(event.sector_index, event.time, event.driver_name, event.lap_number)
            self.broadcast("sector_update", event_to_sector_update_data(event, stats.to_snapshot()))
        elif isinstance(event, LapCompleted):
            record = LapRecord(
                driver_name=event.driver_name,
                lap_number=event.lap_number,
                lap_time=event.lap_time,
                sectors=[SectorRecord(index=i, time=t, valid=event.valid) for i, t in enumerate(event.sectors)],
                valid=event.valid,
            )
            stats.apply_lap(record, event.driver_name)
            self.broadcast("lap_update", event_to_lap_update_data(event, stats.to_snapshot()))
        elif isinstance(event, ResetCompleted):
            stats.reset(event.driver_name)
            log.info("session reset for driver %r", event.driver_name)
            acks, self._pending_reset_acks = self._pending_reset_acks, []
            # Snapshot is built after the acks are sent so it reflects any client changes.
            for ws, request_id in acks:
                msg = encode("reset_ack", {"ok": True, "driver_name": event.driver_name}, seq=None, request_id=request_id)
                await self._safe_send(ws, msg)
            self._broadcast_snapshot()
        elif isinstance(event, StatusChanged):
            self.iracing_connected = event.connected
            self.broadcast_status()
        elif isinstance(event, TrackerInvalidated):
            stats.discard_current_lap()

    async def _safe_send(self, ws: ServerConnection, msg: str) -> None:
        # Bounded so a slow requester cannot stall the event consumer.
        try:
            await asyncio.wait_for(ws.send(msg), timeout=1.0)
        except (websockets.ConnectionClosed, asyncio.TimeoutError):
            pass
