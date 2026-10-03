from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from irlds.protocol import decode, encode

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

    from irlds.server import IRLDSServer

log = logging.getLogger("irlds.commands")

MAX_DRIVER_NAME_LEN = 64


class PitResultLike(Protocol):
    ok: bool
    detail: str


class PitActionsLike(Protocol):
    async def return_to_pits(self) -> PitResultLike: ...


def validate_driver_name(value: Any) -> str | None:
    """Return the trimmed name, or None if invalid (§9.4)."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or len(name) > MAX_DRIVER_NAME_LEN:
        return None
    return name


class CommandHandler:
    """Parses client messages and dispatches them. Runs on the event loop."""

    def __init__(self, server: IRLDSServer, pit_actions: PitActionsLike | None = None) -> None:
        self._server = server
        self._pit_actions = pit_actions

    async def handle(self, ws: ServerConnection, raw: str | bytes) -> None:
        if not isinstance(raw, str):
            await self._error(ws, "invalid_message", "binary frames are not supported")
            return
        try:
            msg = decode(raw)
        except json.JSONDecodeError:
            await self._error(ws, "bad_json", "message is not valid JSON")
            return
        except ValueError as e:
            await self._error(ws, "invalid_message", str(e))
            return

        msg_type = msg["type"]
        request_id = msg.get("request_id") if isinstance(msg.get("request_id"), str) else None
        data = msg.get("data")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            await self._error(ws, "invalid_message", "'data' must be an object", msg_type, request_id)
            return

        if msg_type == "reset":
            await self._reset(ws, data, request_id)
        elif msg_type == "get_snapshot":
            await ws.send(self._server.snapshot_message(request_id=request_id))
        elif msg_type == "ping":
            await ws.send(encode("pong", {}, seq=None, request_id=request_id))
        elif msg_type == "return_to_pits":
            await self._return_to_pits(ws, request_id)
        else:
            await self._error(ws, "unknown_type", f"unknown message type: {msg_type!r}", msg_type, request_id)

    async def _reset(self, ws: ServerConnection, data: dict[str, Any], request_id: str | None) -> None:
        name = validate_driver_name(data.get("driver_name"))
        if name is None:
            await self._error(
                ws,
                "invalid_driver_name",
                f"driver_name must be a non-empty string of at most {MAX_DRIVER_NAME_LEN} characters",
                "reset",
                request_id,
            )
            return
        # The ack and snapshot are sent once the scraper has applied the reset (D11).
        self._server.request_reset(ws, name, request_id)

    async def _return_to_pits(self, ws: ServerConnection, request_id: str | None) -> None:
        if self._pit_actions is None:
            ok, detail = False, "pit actions not configured"
        else:
            try:
                result = await self._pit_actions.return_to_pits()
                ok, detail = result.ok, result.detail
            except Exception as e:  # never raise to the WS handler
                log.error("return_to_pits failed: %s", e, exc_info=True)
                ok, detail = False, f"error: {e}"
        await ws.send(encode("pit_ack", {"ok": ok, "detail": detail}, seq=None, request_id=request_id))

    async def _error(
        self,
        ws: ServerConnection,
        code: str,
        message: str,
        request_type: str | None = None,
        request_id: str | None = None,
    ) -> None:
        data: dict[str, Any] = {"code": code, "message": message}
        if request_type is not None:
            data["request_type"] = request_type
        await ws.send(encode("error", data, seq=None, request_id=request_id))
