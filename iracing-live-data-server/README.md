# iRacing Live Data Server (IRLDS)

Real-time lap and sector tracking for iRacing (Test Drive / Time Trial). IRLDS polls
the sim via `pyirsdk`, derives lap and sector statistics for the current driver, and
pushes them over a WebSocket to the Live Event Tracking (LET) page. LET can reset the
session for the next driver and ask IRLDS to send the car back to the pits.

Platform: **Windows** (iRacing + `pyautogui`). The server, tests and `--fake-source`
demo also run on Linux/macOS.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
python -m pip install -e ".[dev]"
```

**pyirsdk version:** not yet pinned. After verifying against the sim (checklist below),
pin the tested version in `pyproject.toml` (`pyirsdk==<version>`) and record it here.

## Run

```bash
python -m irlds                         # real iRacing source
python -m irlds --fake-source           # synthetic car, no iRacing needed
python -m irlds --config path\to\config.toml --log-level DEBUG
```

The WebSocket server starts first (and works without iRacing running), then the
scraper. Stop with Ctrl+C; clients are closed with code 1001.

### Dev test page

Serve the repo over HTTP so the page sends a localhost origin, then open the page:

```bash
python -m http.server 8080
# http://localhost:8080/tools/test_client.html
```

Opening the page from `file://` sends `Origin: null`; add `"null"` to
`server.allowed_origins` to allow that.

## Config (`config.toml`)

| Key | Default | Notes |
|---|---|---|
| `server.host` | `127.0.0.1` | `0.0.0.0` exposes it on the network (no auth!) |
| `server.port` | `8765` | |
| `server.allowed_origins` | `[]` | Added to the default (any `http(s)://localhost` / `127.0.0.1` origin, or no Origin header). `"null"` allows `file://` pages. |
| `scraper.poll_hz` | `60` | |
| `scraper.count_outlap` | `false` | |
| `pit_actions.enabled` | `true` | `false` → `pit_ack {ok:false, detail:"disabled"}` |
| `pit_actions.window_title` | `iRacing.com Simulator` | |
| `pit_actions.key_sequence` | `[["alt","r"]]` | **Placeholder — verify against your iRacing controls.** Each step is a list of keys pressed together. |
| `pit_actions.fallback_key_sequence` | `[]` | Tried once if the primary sequence raised, or the window was only found on retry. |
| `pit_actions.pre_delay_ms` | `150` | Delay after focusing the window |
| `pit_actions.failsafe` | `true` | pyautogui failsafe (mouse to a screen corner aborts) |
| `logging.level` / `logging.file` | `INFO` / `irlds.log` | |

Environment overrides: `IRLDS_HOST`, `IRLDS_PORT`, `IRLDS_LOG_LEVEL`.

## Protocol summary

Every message is `{ "type", "seq", "ts", "data" }` (optional `request_id`, echoed in the
direct reply). `seq` numbers **broadcasts** only; direct replies have `seq: null`.
Snapshots carry `as_of_seq`: apply the snapshot, then only broadcasts with
`seq > as_of_seq`. A gap in `seq` means messages were missed — request a snapshot.

Server → client:

| type | delivery | data |
|---|---|---|
| `hello` | direct, on connect | `server_version, sector_count, iracing_connected, driver_name, clients` |
| `snapshot` | direct on connect / `get_snapshot`; broadcast after reset | full stats incl. `driver_name`, `as_of_seq`, `clients` |
| `sector_update` | broadcast | `driver_name, sector, time, lap_number, current_lap_sectors, best_sector_times, optimal_lap_time` |
| `lap_update` | broadcast | `driver_name, lap_number, lap_time, valid, sectors, best_lap_time, best_lap_number, best_sector_times, optimal_lap_time, current_lap` |
| `status` | broadcast | `iracing_connected, clients` |
| `reset_ack` | direct | `ok, driver_name` (followed by the broadcast `snapshot`) |
| `pit_ack` | direct | `ok, detail` (`primary` / `fallback` / error text) |
| `pong` | direct | `{}` |
| `error` | direct | `code, message, request_type?` — codes: `bad_json`, `invalid_message`, `unknown_type`, `invalid_driver_name` |

Client → server: `reset {driver_name}`, `return_to_pits {}`, `get_snapshot {}`, `ping {}`.

`driver_name` is trimmed and must be 1–64 characters; otherwise the reset is rejected
with `invalid_driver_name` and nothing changes. Before the first reset it is `null`.

## Open-question defaults

| # | Question | Default |
|---|---|---|
| 1 | Pit-return hotkey | `alt+r` placeholder, configurable; fallback empty |
| 2 | Count the out-lap? | No (`count_outlap = false`) |
| 3 | Invalid laps | Excluded from bests/optimal; reported with `valid: false` |
| 4 | Sector count | From `SplitTimeInfo`; single-sector fallback if missing |
| 5 | Network exposure | Localhost only; `0.0.0.0` opt-in |
| 6 | Multiple clients | All receive broadcasts; any client may `reset` / `return_to_pits` |
| 7 | Driver name | Free text, 1–64 chars after trim; reset rejected if missing/blank |
| 8 | Mid-run rename | Not supported (name changes only via `reset`) |
| 9 | LET from `file://` | Not recommended; allow `"null"` origin if needed |

## Manual verify checklist (needs the sim)

pyirsdk / iRacing behaviour:

1. `SplitTimeInfo.Sectors` is present and sensible for your tracks (count, first boundary `0.0`).
2. `LapLastLapTime` becomes valid exactly when `LapCompleted` increments (same tick vs one tick later).
3. `LapLastLapTime` reports `<= 0` for invalid laps in Time Trial.
4. `OnPitRoad` / `IsOnTrack` behave as expected when returning to the pits in Test Drive / Time Trial.
5. Reported lap times match the iRacing HUD to the millisecond; sector sums equal lap time.
6. The pit hotkey in `config.toml` matches your actual controls.

End-to-end:

1. Run a few laps in Test Drive; compare reported lap times to the iRacing HUD.
2. Verify sector sums equal lap time and that sector count matches the track.
3. Verify `reset` between "drivers" zeroes stats and renames the driver.
4. Verify out-lap handling and an invalid lap (cut/off-track) behave per the defaults above.
5. Verify the pit hotkey (and fallback, if configured).

## Browser client (`client/let_client.js`)

A dependency-free classic script shared by LET and the dev test page. In the browser it
exposes `window.IRLDS.LetClient`; in Node, `require("./client/let_client.js")`.

```js
const client = new IRLDS.LetClient({ url: "ws://127.0.0.1:8765" });
client.on("lap_update", (data) => render(client.state.snapshot));
client.connect();
client.reset("Jane Doe");      // false (and an "error" event, code "not_connected") if disconnected
client.returnToPits();
client.getSnapshot();
```

It reconnects with exponential backoff and jitter, rebuilds state from `hello` + `snapshot`
after every (re)connect, drops stale/duplicate `seq`, and on a `seq` gap emits `"gap"` and
requests a snapshot. Commands are never queued while disconnected. `client.state.snapshot`
is kept up to date by merging `sector_update` / `lap_update` / `status` broadcasts.

## Tests

```bash
python -m pytest
node --test tests/js/*.test.js      # Node 18+; no npm install needed
```

## Known limitations

1. **Windows only** for real use: `pyautogui`/`pygetwindow` need an unlocked desktop session.
2. **Pit action is best-effort**: iRacing must be in the foreground with the right key binding.
3. **pyirsdk compatibility** depends on the pinned version and the iRacing build; re-run the checklist after upgrades.
4. **Single server instance**: one process owns the stats.
5. **Player car only**: no multi-car or spectator data.
6. **No authentication**: if exposed beyond localhost, add auth/TLS.
7. **Browser origins**: `file://` pages send `Origin: null` (see config).

## Troubleshooting

| Symptom | Check |
|---|---|
| `iracing_connected: false` forever | Is iRacing running and in a session? Does `pyirsdk` match your install? Start order does not matter. |
| Client can't connect | Is the server running (`netstat -an \| findstr 8765`)? Host/port in config? Firewall? Origin list (esp. `file://` → `Origin: null`)? |
| Sector times look wrong or only one sector | Track may lack `SplitTimeInfo`; check the WARNING log (single-sector fallback). |
| Lap numbers don't restart | A `reset` must be sent (with a driver name); numbering is relative to the last reset. |
| `invalid_driver_name` error | Name empty, whitespace-only, not a string, or over 64 characters. |
| `pit_ack ok:false` "iRacing window not found" | Check `pit_actions.window_title`; iRacing must be running with a visible window. |
| `pit_ack ok:true` but nothing happens | Verify the key binding in iRacing controls; window focused; desktop unlocked. |
| Client keeps reconnecting | Server down, port mismatch, or origin rejected; see the server log. |
