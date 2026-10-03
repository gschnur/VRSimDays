# iRacing Live Data Server (IRLDS)

Real-time lap and sector tracking for iRacing, exposing data via WebSocket to connected clients.

## Setup

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
python -m irlds
```

With fake telemetry source (no iRacing needed):

```bash
python -m irlds --fake-source
```

## Config

See `config.toml` for server, scraper, and pit action settings.

## Manual Verify Checklist

1. Run a few laps in Test Drive; compare reported lap times to the iRacing HUD.
2. Verify sector sums equal lap time and that sector count matches the track.
3. Verify `reset` between drivers zeroes stats and renames the driver.
4. Verify out-lap handling and an invalid lap behave as expected.
5. Verify the pit hotkey (and fallback, if configured).

## Known Limitations

1. Windows only (pyautogui/pygetwindow require a desktop session).
2. Pit action is best-effort; requires iRacing in the foreground.
3. Single server instance; no clustering.
4. Player car only; no multi-car or spectator data.
5. Open WebSocket on localhost; no authentication.

## Troubleshooting

| Symptom | Check |
|---|---|
| `iracing_connected: false` forever | Is iRacing running and in a session? |
| Client can't connect | Is the server running? Host/port in config? |
| Sector times look wrong | Track may lack `SplitTimeInfo`; check logs. |
| `pit_ack ok:false` | Check `pit_actions.window_title`; iRacing must be visible. |
