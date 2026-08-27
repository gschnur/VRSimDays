// Hardcoded structured car dataset (mirrors the Event Time Calculator)
const CARS = [
    { id: "bmw_m2_cs", name: "BMW M2 CS Racing (F87) - 2020", offset: -3.5 },
    { id: "bmw_m2_g87", name: "BMW M2 Racing (G87)", offset: -4.5 },
    { id: "mazda_mx5_global", name: "Mazda Global MX-5 Cup", offset: 0.0 },
    { id: "mazda_mx5_legacy", name: "Mazda [Legacy] MX-5 Cup & Roadster - 2010", offset: 1.5 },
    { id: "toyota_gr86", name: "Toyota GR86 (cup)", offset: -0.5 },
    { id: "porsche_718", name: "Porsche 718 Cayman GT4 Clubsport MR", offset: -7.0 },
    { id: "porsche_911", name: "Porsche 911 RSR", offset: -13.5 }
];

// Hardcoded structured track configuration dataset (mirrors the Event Time Calculator)
const TRACKS = [
    { id: "lime_rock_gp", name: "Lime Rock Park - Grand Prix", baseSeconds: 61.575 },
    { id: "red_bull_gp", name: "Red Bull Ring - Grand Prix", baseSeconds: 111.067 },
    { id: "red_bull_nat", name: "Red Bull Ring - National", baseSeconds: 59.739 },
    { id: "red_bull_north", name: "Red Bull Ring - North", baseSeconds: 56.511 },
    { id: "road_atlanta_full", name: "Road Atlanta - Full Course", baseSeconds: 97.847 },
    { id: "road_atlanta_club", name: "Road Atlanta - Club", baseSeconds: 68.4 },
    { id: "road_atlanta_short", name: "Road Atlanta - Short", baseSeconds: 66.421 },
    { id: "laguna_seca", name: "Laguna Seca", baseSeconds: 99.629 },
    { id: "suzuka_gp", name: "Suzuka - Grand Prix", baseSeconds: 147.127 },
    { id: "suzuka_east", name: "Suzuka - East", baseSeconds: 58.673 },
    { id: "suzuka_west", name: "Suzuka - West", baseSeconds: 91.734 },
    { id: "tsukuba_2000", name: "Tsukuba - 2000 Full", baseSeconds: 63.863 },
    { id: "virginia_full", name: "Virginia International - Full Course", baseSeconds: 131.200 },
    { id: "phoenix_road", name: "Phoenix Raceway - Road Course", baseSeconds: 68.354 },
    { id: "daytona_road", name: "Daytona - Road Course", baseSeconds: 142.0 },
    { id: "mount_panorama", name: "Mount Panorama Circuit", baseSeconds: 155.818 }
];

// State: combos on the event schedule, and one row per driver
// combo: { key, carName, trackName, parTimeSeconds|null }
// driver: { id, name, times: { [comboKey]: { raw: string, seconds: number|null } } }
let combos = [];
let drivers = [];
let nextComboKey = 1;
let nextDriverId = 1;
let currentComboSpotlightIndex = 0;

// Document Object Selectors
const carSelect = document.getElementById("carSelect");
const trackSelect = document.getElementById("trackSelect");
const addComboBtn = document.getElementById("addComboBtn");
const addDriverBtn = document.getElementById("addDriverBtn");
const importBtn = document.getElementById("importBtn");
const importFile = document.getElementById("importFile");
const importFileName = document.getElementById("importFileName");

const trackingTableHead = document.getElementById("trackingTableHead");
const trackingTableBody = document.getElementById("trackingTableBody");
const emptyState = document.getElementById("emptyState");

const comboSpotlightEmpty = document.getElementById("comboSpotlightEmpty");
const comboSpotlightContent = document.getElementById("comboSpotlightContent");
const comboSpotlightImg = document.getElementById("comboSpotlightImg");
const comboSpotlightNoImage = document.getElementById("comboSpotlightNoImage");
const comboSpotlightCar = document.getElementById("comboSpotlightCar");
const comboSpotlightTrack = document.getElementById("comboSpotlightTrack");
const comboSpotlightParTime = document.getElementById("comboSpotlightParTime");
const comboSpotlightCounter = document.getElementById("comboSpotlightCounter");
const comboSpotlightPrevBtn = document.getElementById("comboSpotlightPrevBtn");
const comboSpotlightNextBtn = document.getElementById("comboSpotlightNextBtn");

const standingsList = document.getElementById("standingsList");
const standingsEmptyState = document.getElementById("standingsEmptyState");
const leaderNameDisplay = document.getElementById("leaderNameDisplay");
const leaderTimeDisplay = document.getElementById("leaderTimeDisplay");

const autosaveStatus = document.getElementById("autosaveStatus");
const clearSavedBtn = document.getElementById("clearSavedBtn");
const exportCsvBtn = document.getElementById("exportCsvBtn");
const exportJsonBtn = document.getElementById("exportJsonBtn");
const exportTrackingCsvBtn = document.getElementById("exportTrackingCsvBtn");
const exportTrackingJsonBtn = document.getElementById("exportTrackingJsonBtn");

const STORAGE_KEY = "vrSimRacingTrackingState_v1";

function init() {
    CARS.forEach(car => {
        let sign = car.offset >= 0 ? "+" : "";
        carSelect.options[carSelect.options.length] = new Option(`${car.name} (${sign}${car.offset}s)`, car.id);
    });

    TRACKS.forEach(track => {
        trackSelect.options[trackSelect.options.length] = new Option(`${track.name} (${formatSecondsToMMSS(track.baseSeconds)})`, track.id);
    });

    addComboBtn.addEventListener("click", () => addCombo());
    addDriverBtn.addEventListener("click", () => addDriver());
    importBtn.addEventListener("click", () => importFile.click());
    importFile.addEventListener("change", handleImportFile);

    if (clearSavedBtn) clearSavedBtn.addEventListener("click", clearSavedState);
    if (exportCsvBtn) exportCsvBtn.addEventListener("click", exportStandingsCSV);
    if (exportJsonBtn) exportJsonBtn.addEventListener("click", exportStandingsJSON);
    if (exportTrackingCsvBtn) exportTrackingCsvBtn.addEventListener("click", exportTrackingCSV);
    if (exportTrackingJsonBtn) exportTrackingJsonBtn.addEventListener("click", exportTrackingJSON);
    if (comboSpotlightPrevBtn) comboSpotlightPrevBtn.addEventListener("click", showPreviousComboSpotlight);
    if (comboSpotlightNextBtn) comboSpotlightNextBtn.addEventListener("click", showNextComboSpotlight);

    loadState();
    renderAll();
}

// ---------- Time helpers ----------

function formatSecondsToMMSS(totalSeconds) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = (totalSeconds % 60).toFixed(3);
    return `${minutes}:${seconds.padStart(6, '0')}`;
}

// Accepts "m:ss.sss" or plain seconds like "83.456". Returns seconds (number) or null if blank/invalid.
function parseTimeToSeconds(str) {
    if (str === null || str === undefined) return null;
    const trimmed = String(str).trim();
    if (trimmed === "") return null;

    if (trimmed.includes(":")) {
        const parts = trimmed.split(":");
        if (parts.length !== 2) return NaN;
        const mins = parseFloat(parts[0]);
        const secs = parseFloat(parts[1]);
        if (isNaN(mins) || isNaN(secs) || mins < 0 || secs < 0) return NaN;
        return (mins * 60) + secs;
    }

    const val = parseFloat(trimmed);
    if (isNaN(val) || val < 0) return NaN;
    return val;
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatGap(seconds) {
    const sign = seconds < 0 ? "-" : "+";
    const abs = Math.abs(seconds);
    return `${sign}${formatSecondsToMMSS(abs)}`;
}

// ---------- Combo management ----------

function addCombo() {
    const car = CARS.find(c => c.id === carSelect.value);
    const track = TRACKS.find(t => t.id === trackSelect.value);
    if (!car || !track) return;

    const key = `c${nextComboKey++}`;
    combos.push({
        key,
        carName: car.name,
        trackName: track.name,
        parTimeSeconds: track.baseSeconds + car.offset
    });

    drivers.forEach(driver => {
        driver.times[key] = { raw: "", seconds: null };
    });

    currentComboSpotlightIndex = combos.length - 1;
    renderAll();
    saveState();
}

function removeCombo(key) {
    const removedIndex = combos.findIndex(c => c.key === key);
    combos = combos.filter(c => c.key !== key);
    drivers.forEach(driver => {
        delete driver.times[key];
    });
    if (removedIndex !== -1 && removedIndex <= currentComboSpotlightIndex) {
        currentComboSpotlightIndex = Math.max(0, currentComboSpotlightIndex - 1);
    }
    renderAll();
    saveState();
}

// ---------- Combo Spotlight (track image + estimated lap time) ----------

// Track names are stored as "Track Base Name - Config Name". Image files are
// named "TrackBaseName-ConfigName.png" (spaces stripped from each segment).
function getTrackImagePath(trackName) {
    if (!trackName) return "./trackName.png";
    const segments = trackName.split(" - ").map(part => part.replace(/\s+/g, ""));
    return `./${segments.join("-")}.png`;
}

function showPreviousComboSpotlight() {
    if (combos.length === 0) return;
    currentComboSpotlightIndex = (currentComboSpotlightIndex - 1 + combos.length) % combos.length;
    renderComboSpotlight();
}

function showNextComboSpotlight() {
    if (combos.length === 0) return;
    currentComboSpotlightIndex = (currentComboSpotlightIndex + 1) % combos.length;
    renderComboSpotlight();
}

function handleComboImageError(imgEl) {
    imgEl.classList.add("hidden");
    if (comboSpotlightNoImage) comboSpotlightNoImage.classList.remove("hidden");
}

function renderComboSpotlight() {
    if (!comboSpotlightContent || !comboSpotlightEmpty) return;

    if (combos.length === 0) {
        comboSpotlightContent.classList.add("hidden");
        comboSpotlightEmpty.classList.remove("hidden");
        comboSpotlightCounter.textContent = "Combo 0 of 0";
        return;
    }

    if (currentComboSpotlightIndex >= combos.length) {
        currentComboSpotlightIndex = combos.length - 1;
    }
    if (currentComboSpotlightIndex < 0) {
        currentComboSpotlightIndex = 0;
    }

    comboSpotlightEmpty.classList.add("hidden");
    comboSpotlightContent.classList.remove("hidden");

    const combo = combos[currentComboSpotlightIndex];

    comboSpotlightImg.classList.remove("hidden");
    comboSpotlightNoImage.classList.add("hidden");
    comboSpotlightImg.src = getTrackImagePath(combo.trackName);

    comboSpotlightCar.textContent = combo.carName;
    comboSpotlightTrack.textContent = combo.trackName;
    comboSpotlightParTime.textContent = typeof combo.parTimeSeconds === "number"
        ? formatSecondsToMMSS(combo.parTimeSeconds)
        : "--";

    comboSpotlightCounter.textContent = `Combo ${currentComboSpotlightIndex + 1} of ${combos.length}`;
}

// ---------- Driver management ----------

function addDriver(name) {
    const driver = { id: nextDriverId++, name: name || "", times: {} };
    combos.forEach(combo => {
        driver.times[combo.key] = { raw: "", seconds: null };
    });
    drivers.push(driver);
    renderAll();
    saveState();
}

function removeDriver(id) {
    drivers = drivers.filter(d => d.id !== id);
    renderAll();
    saveState();
}

function updateDriverName(id, value) {
    const driver = drivers.find(d => d.id === id);
    if (!driver) return;
    driver.name = value;
    renderStandings(); // name changes don't affect table structure, just standings labels
    saveState();
}

function updateDriverTime(id, comboKey, value) {
    const driver = drivers.find(d => d.id === id);
    if (!driver) return;
    const seconds = parseTimeToSeconds(value);
    driver.times[comboKey] = { raw: value, seconds: isNaN(seconds) ? null : seconds };

    const input = document.querySelector(`input[data-driver-id="${id}"][data-combo-key="${comboKey}"]`);
    if (input) {
        input.classList.toggle("is-invalid", value.trim() !== "" && isNaN(seconds));
    }

    updateDriverTotalCell(id);
    renderStandings();
    saveState();
}

// ---------- Import ----------

function handleImportFile(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (drivers.length > 0 || combos.length > 0) {
        const proceed = confirm("Importing will replace the current drivers and combos on this page. Continue?");
        if (!proceed) {
            importFile.value = "";
            return;
        }
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);
            applyImportedSchedule(data);
            importFileName.textContent = `Loaded: ${file.name}`;
        } catch (err) {
            alert("That file doesn't look like a valid event-schedule.json export.");
        }
    };
    reader.readAsText(file);
    importFile.value = "";
}

function applyImportedSchedule(data) {
    if (!data || !Array.isArray(data.combos) || !Array.isArray(data.drivers)) {
        alert("That file doesn't look like a valid event-schedule.json export.");
        return;
    }

    combos = [];
    drivers = [];
    nextComboKey = 1;
    nextDriverId = 1;
    currentComboSpotlightIndex = 0;

    const orderedCombos = [...data.combos].sort((a, b) => (a.comboNumber || 0) - (b.comboNumber || 0));
    orderedCombos.forEach(combo => {
        combos.push({
            key: `c${nextComboKey++}`,
            carName: combo.car || "Unknown Car",
            trackName: combo.track || "Unknown Track",
            parTimeSeconds: typeof combo.parTimeSeconds === "number" ? combo.parTimeSeconds : null
        });
    });

    data.drivers.forEach(driverData => {
        const driver = { id: nextDriverId++, name: driverData.name || "", times: {} };
        combos.forEach(combo => {
            driver.times[combo.key] = { raw: "", seconds: null };
        });
        drivers.push(driver);
    });

    renderAll();
    saveState();
}

// ---------- Autosave (localStorage) ----------

function saveState() {
    try {
        const state = { combos, drivers, nextComboKey, nextDriverId, savedAt: Date.now() };
        localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        updateAutosaveStatus(state.savedAt);
    } catch (err) {
        console.error("Autosave failed:", err);
        if (autosaveStatus) autosaveStatus.textContent = "Autosave failed";
    }
}

function loadState() {
    let raw;
    try {
        raw = localStorage.getItem(STORAGE_KEY);
    } catch (err) {
        console.error("Could not access saved data:", err);
        return false;
    }
    if (!raw) {
        updateAutosaveStatus(null);
        return false;
    }
    try {
        const state = JSON.parse(raw);
        if (!state || !Array.isArray(state.combos) || !Array.isArray(state.drivers)) {
            updateAutosaveStatus(null);
            return false;
        }
        combos = state.combos;
        drivers = state.drivers;
        nextComboKey = state.nextComboKey || (combos.length + 1);
        nextDriverId = state.nextDriverId || (drivers.length + 1);
        updateAutosaveStatus(state.savedAt);
        return true;
    } catch (err) {
        console.error("Failed to load saved data:", err);
        updateAutosaveStatus(null);
        return false;
    }
}

function updateAutosaveStatus(timestamp) {
    if (!autosaveStatus) return;
    if (!timestamp) {
        autosaveStatus.textContent = "Not saved yet";
        return;
    }
    const time = new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    autosaveStatus.textContent = `Autosaved ${time}`;
}

function clearSavedState() {
    const proceed = confirm("This clears the autosaved data stored in this browser and resets the page. This can't be undone. Continue?");
    if (!proceed) return;
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch (err) {
        console.error("Failed to clear saved data:", err);
    }
    combos = [];
    drivers = [];
    nextComboKey = 1;
    nextDriverId = 1;
    currentComboSpotlightIndex = 0;
    updateAutosaveStatus(null);
    renderAll();
}

// ---------- Export ----------

function downloadFile(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function timestampForFilename() {
    return new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
}

function getRankedStandings() {
    const results = drivers.map(driver => {
        const { total, completed } = computeDriverTotal(driver);
        return {
            id: driver.id,
            name: driver.name.trim() || `Driver ${driver.id}`,
            total,
            completed
        };
    });
    const ranked = results.filter(r => r.completed > 0).sort((a, b) => a.total - b.total);
    const unranked = results.filter(r => r.completed === 0);
    return { ranked, unranked };
}

function csvEscape(value) {
    const str = String(value);
    if (/[",\r\n]/.test(str)) {
        return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
}

function exportStandingsCSV() {
    const { ranked, unranked } = getRankedStandings();
    if (ranked.length === 0 && unranked.length === 0) {
        alert("There are no standings to export yet.");
        return;
    }

    const leader = ranked[0];
    const rows = [["Position", "Driver", "Combos Completed", "Total Time", "Gap to Leader"]];

    ranked.forEach((r, index) => {
        const gap = index === 0 ? "Leader" : formatGap(r.total - leader.total);
        rows.push([index + 1, r.name, `${r.completed}/${combos.length}`, formatSecondsToMMSS(r.total), gap]);
    });

    unranked.forEach(r => {
        rows.push(["-", r.name, `0/${combos.length}`, "No times", "-"]);
    });

    const csv = rows.map(row => row.map(csvEscape).join(",")).join("\r\n");
    downloadFile(`standings_${timestampForFilename()}.csv`, csv, "text/csv;charset=utf-8;");
}

function exportStandingsJSON() {
    const { ranked, unranked } = getRankedStandings();
    if (ranked.length === 0 && unranked.length === 0) {
        alert("There are no standings to export yet.");
        return;
    }

    const leader = ranked[0];
    const payload = {
        exportedAt: new Date().toISOString(),
        combos: combos.map(c => ({ car: c.carName, track: c.trackName })),
        standings: ranked.map((r, index) => ({
            position: index + 1,
            name: r.name,
            combosCompleted: r.completed,
            totalCombos: combos.length,
            totalTimeSeconds: Number(r.total.toFixed(3)),
            totalTimeFormatted: formatSecondsToMMSS(r.total),
            gapToLeaderSeconds: index === 0 ? null : Number((r.total - leader.total).toFixed(3))
        })),
        noTimeYet: unranked.map(r => r.name)
    };

    downloadFile(`standings_${timestampForFilename()}.json`, JSON.stringify(payload, null, 2), "application/json");
}

function exportTrackingCSV() {
    if (drivers.length === 0 || combos.length === 0) {
        alert("There's no tracking data to export yet.");
        return;
    }

    const header = ["Driver", ...combos.map((c, i) => `Combo ${i + 1}: ${c.carName} — ${c.trackName}`), "Total"];
    const rows = [header];

    drivers.forEach(driver => {
        const name = driver.name.trim() || `Driver ${driver.id}`;
        const cells = combos.map(combo => {
            const entry = driver.times[combo.key];
            return entry && entry.raw ? entry.raw : "";
        });
        const { total, completed } = computeDriverTotal(driver);
        rows.push([name, ...cells, completed > 0 ? formatSecondsToMMSS(total) : ""]);
    });

    const csv = rows.map(row => row.map(csvEscape).join(",")).join("\r\n");
    downloadFile(`event_tracking_${timestampForFilename()}.csv`, csv, "text/csv;charset=utf-8;");
}

function exportTrackingJSON() {
    if (drivers.length === 0 || combos.length === 0) {
        alert("There's no tracking data to export yet.");
        return;
    }

    const payload = {
        exportedAt: new Date().toISOString(),
        combos: combos.map((c, i) => ({
            comboNumber: i + 1,
            car: c.carName,
            track: c.trackName,
            parTimeSeconds: c.parTimeSeconds
        })),
        drivers: drivers.map(driver => {
            const { total, completed } = computeDriverTotal(driver);
            return {
                name: driver.name.trim() || `Driver ${driver.id}`,
                times: combos.map(combo => {
                    const entry = driver.times[combo.key] || { raw: "", seconds: null };
                    return {
                        car: combo.carName,
                        track: combo.trackName,
                        raw: entry.raw || "",
                        seconds: entry.seconds
                    };
                }),
                combosCompleted: completed,
                totalCombos: combos.length,
                totalTimeSeconds: completed > 0 ? Number(total.toFixed(3)) : null,
                totalTimeFormatted: completed > 0 ? formatSecondsToMMSS(total) : null
            };
        })
    };

    downloadFile(`event_tracking_${timestampForFilename()}.json`, JSON.stringify(payload, null, 2), "application/json");
}

// ---------- Rendering ----------

function renderAll() {
    renderTableHead();
    renderTableBody();
    renderStandings();
    renderComboSpotlight();
}

function renderTableHead() {
    // Remove existing combo <th> columns (everything between the first and last two fixed columns)
    const existingComboThs = trackingTableHead.querySelectorAll("th[data-combo-key]");
    existingComboThs.forEach(th => th.remove());

    const totalTh = trackingTableHead.querySelector("th:nth-last-child(2)");

    combos.forEach((combo, index) => {
        const th = document.createElement("th");
        th.setAttribute("data-combo-key", combo.key);
        th.className = "py-3.5 px-4 font-bold text-right";
        th.innerHTML = `
            <div class="flex flex-col items-end gap-0.5">
                <div class="flex items-center gap-2">
                    <span class="text-gray-300">Combo ${index + 1}</span>
                    <button class="text-red-400 hover:text-red-500 font-bold normal-case text-[11px]" onclick="removeCombo('${combo.key}')" title="Remove combo">✕</button>
                </div>
                <span class="text-[9px] normal-case font-normal text-gray-500 max-w-[140px] truncate" title="${escapeHtml(combo.carName)} — ${escapeHtml(combo.trackName)}">${escapeHtml(combo.carName)}</span>
                <span class="text-[9px] normal-case font-normal text-gray-600 max-w-[140px] truncate" title="${escapeHtml(combo.trackName)}">${escapeHtml(combo.trackName)}</span>
            </div>
        `;
        trackingTableHead.insertBefore(th, totalTh);
    });
}

function renderTableBody() {
    trackingTableBody.innerHTML = "";

    if (drivers.length === 0 || combos.length === 0) {
        emptyState.classList.remove("hidden");
        return;
    }
    emptyState.classList.add("hidden");

    drivers.forEach(driver => {
        const row = document.createElement("tr");
        row.setAttribute("data-driver-row", driver.id);

        let comboCellsHtml = "";
        combos.forEach(combo => {
            const entry = driver.times[combo.key] || { raw: "", seconds: null };
            const invalidClass = entry.raw.trim() !== "" && entry.seconds === null ? " is-invalid" : "";
            comboCellsHtml += `
                <td class="p-2.5 text-right">
                    <input type="text"
                        class="time-input${invalidClass} bg-input-dark border border-gray-800-force rounded-lg px-2 py-1.5 text-xs text-white text-right focus:outline-none focus:border-red-500 transition-colors font-mono"
                        placeholder="m:ss.sss"
                        value="${escapeHtml(entry.raw)}"
                        data-driver-id="${driver.id}"
                        data-combo-key="${combo.key}"
                        oninput="updateDriverTime(${driver.id}, '${combo.key}', this.value)">
                </td>
            `;
        });

        row.innerHTML = `
            <td class="p-2.5 sticky left-0 bg-inherit">
                <input type="text"
                    class="bg-input-dark border border-gray-800-force rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-red-500 transition-colors w-36"
                    placeholder="Driver name"
                    value="${escapeHtml(driver.name)}"
                    oninput="updateDriverName(${driver.id}, this.value)">
            </td>
            ${comboCellsHtml}
            <td class="p-2.5 text-right font-mono text-emerald-400 font-semibold" data-total-cell="${driver.id}"></td>
            <td class="p-2.5 text-center">
                <button onclick="removeDriver(${driver.id})" class="text-red-400 hover:text-red-500 font-bold px-2 py-1 rounded hover:bg-red-500/10">✕</button>
            </td>
        `;
        trackingTableBody.appendChild(row);
        updateDriverTotalCell(driver.id);
    });
}

function computeDriverTotal(driver) {
    let total = 0;
    let completed = 0;
    combos.forEach(combo => {
        const entry = driver.times[combo.key];
        if (entry && entry.seconds !== null) {
            total += entry.seconds;
            completed += 1;
        }
    });
    return { total, completed };
}

function updateDriverTotalCell(driverId) {
    const driver = drivers.find(d => d.id === driverId);
    if (!driver) return;
    const cell = document.querySelector(`[data-total-cell="${driverId}"]`);
    if (!cell) return;

    const { total, completed } = computeDriverTotal(driver);
    cell.textContent = completed > 0 ? formatSecondsToMMSS(total) : "--";
}

function renderStandings() {
    if (drivers.length === 0 || combos.length === 0) {
        standingsList.innerHTML = "";
        standingsEmptyState.classList.remove("hidden");
        leaderNameDisplay.textContent = "No times yet";
        leaderTimeDisplay.textContent = "--";
        return;
    }

    const results = drivers.map(driver => {
        const { total, completed } = computeDriverTotal(driver);
        return {
            id: driver.id,
            name: driver.name.trim() || `Driver ${driver.id}`,
            total,
            completed
        };
    });

    const ranked = results.filter(r => r.completed > 0).sort((a, b) => a.total - b.total);
    const unranked = results.filter(r => r.completed === 0);

    if (ranked.length === 0) {
        standingsList.innerHTML = "";
        standingsEmptyState.classList.remove("hidden");
        leaderNameDisplay.textContent = "No times yet";
        leaderTimeDisplay.textContent = "--";
        return;
    }
    standingsEmptyState.classList.add("hidden");

    const leader = ranked[0];
    leaderNameDisplay.textContent = leader.name;
    leaderTimeDisplay.textContent = formatSecondsToMMSS(leader.total);

    const medalColors = ["text-amber-400", "text-gray-300", "text-orange-600"];

    let html = "";
    ranked.forEach((r, index) => {
        const posColor = medalColors[index] || "text-gray-500";
        const gap = index === 0 ? "Leader" : formatGap(r.total - leader.total);
        html += `
            <div class="flex items-center justify-between px-5 py-3.5">
                <div class="flex items-center gap-3">
                    <span class="w-6 text-sm font-black ${posColor}">${index + 1}</span>
                    <span class="text-xs font-semibold text-gray-200">${escapeHtml(r.name)}</span>
                    <span class="text-[10px] text-gray-500 font-mono">${r.completed}/${combos.length} combos</span>
                </div>
                <div class="flex items-center gap-4">
                    <span class="text-[10px] font-mono ${index === 0 ? 'text-emerald-400' : 'text-gray-500'}">${gap}</span>
                    <span class="text-xs font-mono font-bold text-white">${formatSecondsToMMSS(r.total)}</span>
                </div>
            </div>
        `;
    });

    unranked.forEach(r => {
        html += `
            <div class="flex items-center justify-between px-5 py-3.5 opacity-50">
                <div class="flex items-center gap-3">
                    <span class="w-6 text-sm font-black text-gray-600">-</span>
                    <span class="text-xs font-semibold text-gray-400">${escapeHtml(r.name)}</span>
                    <span class="text-[10px] text-gray-600 font-mono">0/${combos.length} combos</span>
                </div>
                <span class="text-xs font-mono text-gray-600">No times</span>
            </div>
        `;
    });

    standingsList.innerHTML = html;
}

// Launch application script tracking execution
init();
