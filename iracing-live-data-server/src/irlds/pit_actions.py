"""Return-to-pits via keystrokes (§11).

pyautogui only works when the target window is in the foreground and the desktop
is unlocked (no headless / locked sessions). Everything here is best-effort.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from irlds.config import PitActionsConfig

log = logging.getLogger("irlds.pit_actions")

WINDOW_NOT_FOUND = "iRacing window not found"


@dataclass(slots=True)
class PitResult:
    ok: bool
    detail: str


class WindowNotFound(Exception):
    pass


def _default_focus_window(title: str) -> None:
    """Find the window by title and bring it to the foreground. Raises WindowNotFound."""
    import pygetwindow  # Windows-only; imported lazily so tests run anywhere

    windows = pygetwindow.getWindowsWithTitle(title)
    if not windows:
        raise WindowNotFound(title)
    windows[0].activate()


def _default_send_hotkey(keys: list[str]) -> None:
    import pyautogui

    pyautogui.hotkey(*keys)


class PitActions:
    """Blocking keystroke work runs in a worker thread via asyncio.to_thread (agent rule 3)."""

    def __init__(
        self,
        config: PitActionsConfig,
        focus_window: Callable[[str], None] | None = None,
        send_hotkey: Callable[[list[str]], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._focus_window = focus_window or _default_focus_window
        self._send_hotkey = send_hotkey or _default_send_hotkey
        self._sleep = sleep
        self._lock = asyncio.Lock()
        if focus_window is None and send_hotkey is None:
            self._configure_pyautogui()

    def _configure_pyautogui(self) -> None:
        try:
            import pyautogui

            pyautogui.FAILSAFE = self._config.failsafe
        except Exception as e:  # missing display / not Windows: fail at use time instead
            log.warning("pyautogui unavailable: %s", e)

    async def return_to_pits(self) -> PitResult:
        if not self._config.enabled:
            return PitResult(ok=False, detail="disabled")
        async with self._lock:  # repeated commands never overlap
            try:
                return await asyncio.to_thread(self._run_blocking)
            except Exception as e:  # never raise to the WS handler
                log.error("return_to_pits failed: %s", e, exc_info=True)
                return PitResult(ok=False, detail=f"error: {e}")

    def _run_blocking(self) -> PitResult:
        cfg = self._config
        fallback = cfg.fallback_key_sequence
        title = cfg.window_title

        try:
            self._focus_window(title)
        except WindowNotFound:
            # Retry once; if the window appears, use the fallback (if configured).
            log.warning("window %r not found; retrying", title)
            self._sleep(cfg.pre_delay_ms / 1000.0)
            try:
                self._focus_window(title)
            except WindowNotFound:
                return PitResult(ok=False, detail=WINDOW_NOT_FOUND)
            if fallback:
                return self._attempt(fallback, "fallback")
            return self._attempt(cfg.key_sequence, "primary")

        try:
            return self._attempt(cfg.key_sequence, "primary", raise_errors=bool(fallback))
        except Exception as e:
            log.warning("primary key sequence failed (%s); trying fallback", e)
            self._focus_window(title)
            return self._attempt(fallback, "fallback")

    def _attempt(self, sequence: list[list[str]], label: str, raise_errors: bool = False) -> PitResult:
        self._sleep(self._config.pre_delay_ms / 1000.0)
        try:
            for step in sequence:
                self._send_hotkey(list(step))
        except Exception as e:
            if raise_errors:
                raise
            log.error("%s key sequence failed: %s", label, e)
            return PitResult(ok=False, detail=f"{label} failed: {e}")
        log.info("return_to_pits sent (%s)", label)
        return PitResult(ok=True, detail=label)


@dataclass
class FakePitActions:
    """Records calls; returns a scripted result. For tests and --fake-source."""

    result: PitResult = field(default_factory=lambda: PitResult(ok=True, detail="primary"))
    delay: float = 0.0
    calls: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    max_concurrent: int = 0
    _active: int = 0

    async def return_to_pits(self) -> PitResult:
        async with self._lock:
            self.calls += 1
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
            try:
                if self.delay:
                    await asyncio.sleep(self.delay)
                return self.result
            finally:
                self._active -= 1
