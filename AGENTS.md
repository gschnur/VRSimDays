# VRSimDays — Agent Instructions

## What this repo is

A static-site tool for planning and tracking VR sim-racing events. No build system, no package manager, no framework. Serve the files directly from disk.

## How to run

Any static server works. Quick options:

```
python3 -m http.server 8080
```
or
```
npx serve .
```

Then open `http://localhost:8080`. No build step.

## Entry points

| File              | Role                                                                         |
|-------------------|------------------------------------------------------------------------------|
| `index.html`      | Main page: event info, car/track reference tables, embedded calculator       |
| `calculator.html` | Event time calculator (fetched and injected into `index.html` via `fetch()`) |
| `app.js`          | Calculator logic: car/track combos, time estimates, export/import, autosave  |
| `tracking.html`   | Standalone live event tracker: lap-time logging, standings, CSV/JSON export  |
| `tracking.js`     | Tracker logic: driver/combo management, time parsing, autosave, export       |

## Data model

Car and track data is **duplicated** in two places:
- `app.js` — `CARS` and `TRACKS` arrays (calculator)
- `tracking.js` — same `CARS` and `TRACKS` arrays (tracker)

Any change to a car name, track name, id, offset, or base time must be applied to **both** files. The CSV files (`WebApp/originalTableSourceData/Cars.csv`, `WebApp/originalTableSourceData/Traks.csv`) are reference data only — they are not read at runtime.

Track image filenames follow the pattern `<TrackName>-<Config>.png` with spaces removed (e.g. `WebApp/trackImages/LimeRockPark-GrandPrix.png`). The `getTrackImagePath()` function in `tracking.js` derives the path from the track name string by splitting on `" - "` and stripping spaces.

## Key behaviors

- **Autosave**: Both `app.js` and `tracking.js` persist state to `localStorage` on every change. Keys: `vrSimEventCalculator_autosave_v1` and `vrSimRacingState_v1`.
- **Export/Import**: `app.js` exports `event-schedule.json` which can be imported into `tracking.html` to pre-populate drivers and combos.
- **Time format**: The tracker accepts `m:ss.sss` or plain seconds. Parsing is in `parseTimeToSeconds()` in `tracking.js`.
- **Tailwind**: Loaded from CDN (`cdn.tailwindcss.com`) in every HTML file. No local Tailwind install.
- **Mermaid**: `index.html` loads Mermaid v11 from jsDelivr for the flowchart diagram.

## Conventions

- No linting, formatting, or type-checking configured.
- Commits should keep `app.js` and `tracking.js` in sync when car/track data changes.
- All styling is inline or in `<style>` blocks within the HTML files.
