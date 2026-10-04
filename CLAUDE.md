# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The repo has two independent parts:

1. **`docs/`**: a static site (no build, no package manager) for planning and tracking VR sim-racing events. It's served straight from disk, and `docs/` looks like the GitHub Pages root.
2. **`iracing-live-data-server/`** (IRLDS): a Python WebSocket server that reads iRacing telemetry and pushes live lap/sector stats to the tracker page (LET, "Live Event Tracking"), plus a browser client module for it.

`AGENTS.md` only points here; keep all agent instructions in this file.

## Static site (`docs/`)

Run it with `cd docs && python3 -m http.server 8080`. There is no lint, build or test step.

- `index.html` loads `calculator.html` with `fetch()` and injects it, so the page has to be served over HTTP, not opened from `file://`. Calculator logic is in `app.js`.
- `tracking.html` + `tracking.js` make up the standalone live tracker.
- Car and track data (the `CARS` and `TRACKS` arrays) is **duplicated** in `app.js` and `tracking.js`. Any change to a name, id, offset or base time must be made in both files. The CSVs in `docs/originalTableSourceData/` are reference only and aren't read at runtime.
- Track images are in `docs/trackImages/`. `getTrackImagePath()` in `tracking.js` builds the filename from the track name: it splits on `" - "`, strips spaces and adds `.png`.
- Both pages autosave to localStorage (`vrSimEventCalculator_autosave_v1` and `vrSimRacingTrackingState_v1`). The calculator exports `event-schedule.json`, and the tracker can import it.
- Tailwind is loaded from its CDN and Mermaid v11 from jsDelivr. All styling is inline or in `<style>` blocks.

## IRLDS (`iracing-live-data-server/`)

Run every command from `iracing-live-data-server/`. `main.py` there is an unused PyCharm stub; the real entry point is `src/irlds/__main__.py`.

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"

python -m irlds --fake-source            # synthetic car; works on Linux (no iRacing)
python -m irlds --config config.toml --log-level DEBUG

python -m pytest                          # all Python tests (asyncio_mode=auto)
python -m pytest tests/test_tracker.py -k some_name   # single test
node --test tests/js/*.test.js            # JS client tests, Node 18+, no npm install

python -m http.server 8080                # then open /tools/test_client.html (dev test page)
```

The real source needs Windows with iRacing running and `pyautogui`. The tests and `--fake-source` run anywhere.

### Architecture

The process runs two threads, and `app.py` (`IRLDSApp.main`) wires them together:

- **Scraper thread** (`scraper.py` `ScraperThread`): polls a `TelemetrySource` at `poll_hz` and passes each frame to `LapSectorTracker` (`tracker.py`). The tracker derives sector and lap times by interpolating `LapDistPct` crossings, because iRacing doesn't publish live sector times. The resulting `TrackerEvent`s (`events.py`) go into an `asyncio.Queue` via `call_soon_threadsafe`.
- **Asyncio event loop** (`server.py` `IRLDSServer`): consumes the queue, applies events to `SessionStats` (`models.py`) and broadcasts protocol messages. `commands.py` handles client commands. A `reset` goes back to the scraper thread through `ScraperThread.request_reset` (a locked slot). `return_to_pits` runs `pit_actions.py` (pyautogui keystrokes) off the loop.
- `BoundarySyncSource` in `app.py` wraps the source. Whenever the sector boundaries or `session_signature()` change (track change, detected from `WeekendInfo.TrackID`), it re-arms the tracker.
- Sources implement the `TelemetrySource` protocol in `sources/base.py`: `iracing.py` (pyirsdk) and `fake.py`. `IRLDSApp` also accepts injected `source=` and `pit_actions=` objects; the tests use this.
- Startup order: the WebSocket server starts first, then the scraper. The server works without iRacing running.
- `client/let_client.js` is a dependency-free UMD-style script (`window.IRLDS.LetClient` in the browser, `require()` in Node). It handles reconnect with backoff, `seq` gap detection with snapshot resync, and a merged `state.snapshot`.

### Invariants (from the implementation plan, `SlopAi/IMPLEMENTATION_PLAN_rev4.md` §0.2)

- **Thread ownership:** only the scraper thread mutates tracker state. `SessionStats` and the client set are touched only on the event loop.
- **Never block the asyncio loop.** pyirsdk and pyautogui are synchronous.
- **Don't invent pyirsdk APIs.** Use only the calls listed in plan §7.1. If something else seems needed, leave a `# TODO(verify)` comment and a note on the README's manual checklist.
- The wire protocol (envelope `{type, seq, ts, data, request_id?}`; see the README protocol table) must be matched exactly. Only broadcasts carry `seq`; direct replies have `seq: null`, and snapshots carry `as_of_seq`. Changes to the protocol must be made in `protocol.py`/`server.py`, `let_client.js`, the README and both test suites together.
- Best and optimal times update only when a lap completes **valid**. Lap numbers are relative to the last `reset`.
