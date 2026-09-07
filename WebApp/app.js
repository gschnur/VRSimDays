// Hardcoded structured car dataset
const CARS = [
    { id: "bmw_m2_cs", name: "BMW M2 CS Racing (F87) - 2020", offset: -3.5 },
    { id: "bmw_m2_g87", name: "BMW M2 Racing (G87)", offset: -4.5 },
    { id: "mazda_mx5_global", name: "Mazda Global MX-5 Cup", offset: 0.0 },
    { id: "mazda_mx5_legacy", name: "Mazda [Legacy] MX-5 Cup & Roadster - 2010", offset: 1.5 },
    { id: "toyota_gr86", name: "Toyota GR86 (cup)", offset: -0.5 },
    { id: "porsche_718", name: "Porsche 718 Cayman GT4 Clubsport MR", offset: -7.0 },
    { id: "porsche_911", name: "Porsche 911 RSR", offset: -13.5 }
];

// Hardcoded structured track configuration dataset
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

// State Array for the live table selection rows
let activeCombos = [
    //{ carId: "mazda_mx5_global", trackId: "lime_rock_gp" }
];

// Holds any previously-entered driver names/times so they survive export -> import -> export cycles
let driverData = [];

// LocalStorage key used for autosave/restore
const AUTOSAVE_KEY = "vrSimEventCalculator_autosave_v1";

// Factory-default Event Parameters, used by the Reset button
const DEFAULT_PARAMETERS = {
    numDrivers: 4,
    accLaps: 3,
    hotLaps: 3,
    driverChange: 90,
    comboChange: 10
};

// Document Object Selectors
const carSelect = document.getElementById("carSelect");
const trackSelect = document.getElementById("trackSelect");
const addComboBtn = document.getElementById("addComboBtn");
const exportScheduleBtn = document.getElementById("exportScheduleBtn");
const comboTableBody = document.getElementById("comboTableBody");
const emptyState = document.getElementById("emptyState");
const importScheduleBtn = document.getElementById("importScheduleBtn");
const importFileInput = document.getElementById("importFileInput");
const autoSaveStatus = document.getElementById("autoSaveStatus");
const resetCalculatorBtn = document.getElementById("resetCalculatorBtn");

const numDriversInput = document.getElementById("numDrivers");
const accLapsInput = document.getElementById("accLaps");
const hotLapsInput = document.getElementById("hotLaps");
const driverChangeInput = document.getElementById("driverChange");
const comboChangeInput = document.getElementById("comboChange");
const totalTimeDisplay = document.getElementById("totalTimeDisplay");

// Setup application dropdown arrays and tracking inputs
function init() {
    CARS.forEach(car => {
        let sign = car.offset >= 0 ? "+" : "";
        carSelect.options[carSelect.options.length] = new Option(`${car.name} (${sign}${car.offset}s)`, car.id);
    });

    TRACKS.forEach(track => {
        trackSelect.options[trackSelect.options.length] = new Option(`${track.name} (${formatSecondsToMMSS(track.baseSeconds)})`, track.id);
    });

    addComboBtn.addEventListener("click", addCombo);
    exportScheduleBtn.addEventListener("click", exportEventSchedule);

    if (importScheduleBtn && importFileInput) {
        importScheduleBtn.addEventListener("click", () => importFileInput.click());
        importFileInput.addEventListener("change", handleImportFileSelected);
    }

    if (resetCalculatorBtn) {
        resetCalculatorBtn.addEventListener("click", resetCalculator);
    }

    [numDriversInput, accLapsInput, hotLapsInput, driverChangeInput, comboChangeInput].forEach(input => {
        input.addEventListener("input", () => {
            calculateEventTime();
            autoSave();
        });
    });

    // Restore any previously autosaved session before first render
    restoreAutoSave();

    renderGrid();
}

function formatSecondsToMMSS(totalSeconds) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = (totalSeconds % 60).toFixed(3);
    return `${minutes}:${seconds.padStart(6, '0')}`;
}

function addCombo() {
    activeCombos.push({ carId: carSelect.value, trackId: trackSelect.value });
    renderGrid();
    autoSave();
}

function removeCombo(index) {
    activeCombos.splice(index, 1);
    renderGrid();
    autoSave();
}

// Draw the application table dynamically
function renderGrid() {
    comboTableBody.innerHTML = "";
    if (activeCombos.length === 0) {
        emptyState.classList.remove("hidden");
    } else {
        emptyState.classList.add("hidden");
        activeCombos.forEach((item, index) => {
            const car = CARS.find(c => c.id === item.carId);
            const track = TRACKS.find(t => t.id === item.trackId);

            // Formula Execution: Base Benchmark Lap + Vehicle Modification Time Offset
            const calculatedTimeSeconds = track.baseSeconds + car.offset;

            const row = document.createElement("tr");
            row.className = "hover:bg-gray-750 transition-colors";
            row.innerHTML = `
                <td class="p-3 font-medium text-gray-200">${car.name}</td>
                <td class="p-3 text-gray-400">${track.name}</td>
                <td class="p-3 text-right font-mono text-emerald-400">${formatSecondsToMMSS(calculatedTimeSeconds)}</td>
                <td class="p-3 text-center">
                    <button onclick="removeCombo(${index})" class="text-red-400 hover:text-red-500 font-bold px-2 py-1 rounded hover:bg-red-500/10">✕</button>
                </td>
            `;
            comboTableBody.appendChild(row);
        });
    }
    calculateEventTime();
}

// Compute total time calculations based on current inputs
function calculateEventTime() {
    const drivers = parseInt(numDriversInput.value) || 0;
    const accLaps = parseInt(accLapsInput.value) || 0;
    const hotLaps = parseInt(hotLapsInput.value) || 0;
    const driverChangeSec = parseInt(driverChangeInput.value) || 0;
    const comboChangeMin = parseInt(comboChangeInput.value) || 0;

    let totalSeconds = 0;
    const numCombos = activeCombos.length;

    if (drivers > 0 && numCombos > 0) {
        activeCombos.forEach(item => {
            const car = CARS.find(c => c.id === item.carId);
            const track = TRACKS.find(t => t.id === item.trackId);
            const lapTimeSec = track.baseSeconds + car.offset;

            const dynamicLapTimePerDriver = (accLaps + hotLaps) * lapTimeSec;
            const activeRacingSeconds = drivers * dynamicLapTimePerDriver;
            const driverBufferSeconds = (drivers - 1) * driverChangeSec;

            totalSeconds += (activeRacingSeconds + driverBufferSeconds);
        });

        const totalComboBuffersSeconds = (numCombos - 1) * (comboChangeMin * 60);
        totalSeconds += totalComboBuffersSeconds;
    }

    if (totalSeconds <= 0) {
        totalTimeDisplay.innerText = "0h 0m 0s";
        return;
    }

    const hrs = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    const secs = Math.round(totalSeconds % 60);

    totalTimeDisplay.innerText = `${hrs}h ${mins}m ${secs}s`;
}

// Read the current Event Parameters panel into a plain object
function getParameters() {
    return {
        numDrivers: parseInt(numDriversInput.value) || 0,
        accLaps: parseInt(accLapsInput.value) || 0,
        hotLaps: parseInt(hotLapsInput.value) || 0,
        driverChange: parseInt(driverChangeInput.value) || 0,
        comboChange: parseInt(comboChangeInput.value) || 0
    };
}

// Push a parameters object back into the Event Parameters panel inputs
function setParameters(params) {
    if (!params) return;
    if (params.numDrivers !== undefined) numDriversInput.value = params.numDrivers;
    if (params.accLaps !== undefined) accLapsInput.value = params.accLaps;
    if (params.hotLaps !== undefined) hotLapsInput.value = params.hotLaps;
    if (params.driverChange !== undefined) driverChangeInput.value = params.driverChange;
    if (params.comboChange !== undefined) comboChangeInput.value = params.comboChange;
}

// Build the "combos" section of a schedule export, keyed with both the raw
// ids (needed to re-import into the dropdowns) and the human-readable fields
// (kept for anyone reading the exported JSON by hand).
function buildCombosForExport() {
    return activeCombos.map((item, index) => {
        const car = CARS.find(c => c.id === item.carId);
        const track = TRACKS.find(t => t.id === item.trackId);
        const parTimeSeconds = track.baseSeconds + car.offset;
        return {
            comboNumber: index + 1,
            carId: car.id,
            trackId: track.id,
            car: car.name,
            track: track.name,
            parTime: formatSecondsToMMSS(parTimeSeconds),
            parTimeSeconds: Math.round(parTimeSeconds * 1000) / 1000
        };
    });
}

// Reconcile driverData with the current numDrivers/combos so that any names
// or times a user already typed into a previously-exported sheet (then
// re-imported) are preserved across further exports.
function reconcileDriverData(numDrivers, combos) {
    const reconciled = [];
    for (let i = 0; i < numDrivers; i++) {
        const existing = driverData[i] || {};
        const driver = { name: existing.name || "" };
        combos.forEach(combo => {
            const key = `combo${combo.comboNumber}`;
            driver[key] = (existing[key] !== undefined) ? existing[key] : null;
        });
        reconciled.push(driver);
    }
    driverData = reconciled;
    return reconciled;
}

// Build a full snapshot of everything needed to continue later: the event
// parameters, the active car/track combos, and any driver data collected so far.
function buildStateSnapshot() {
    const params = getParameters();
    const combos = buildCombosForExport();
    const drivers = reconcileDriverData(params.numDrivers, combos);
    return {
        savedAt: new Date().toISOString(),
        parameters: params,
        combos,
        drivers
    };
}

// Build a blank/continued driver-combo schedule from current config and download it as JSON
function exportEventSchedule() {
    const params = getParameters();

    if (params.numDrivers <= 0) {
        alert("Set a number of drivers before exporting.");
        return;
    }
    if (activeCombos.length === 0) {
        alert("Add at least one car & track combo before exporting.");
        return;
    }

    const schedule = buildStateSnapshot();

    const blob = new Blob([JSON.stringify(schedule, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "event-schedule.json";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    autoSave();
}

// Apply a parsed schedule object (from an import or an autosave) to the live app state
function applySchedule(schedule) {
    if (!schedule || typeof schedule !== "object") {
        throw new Error("That file doesn't look like a valid event schedule.");
    }

    if (schedule.parameters) {
        setParameters(schedule.parameters);
    }

    if (Array.isArray(schedule.combos)) {
        activeCombos = schedule.combos.map(combo => {
            // Prefer the ids (new export format); fall back to matching by
            // display name for schedules exported before ids were included.
            const car = (combo.carId && CARS.find(c => c.id === combo.carId))
                || CARS.find(c => c.name === combo.car);
            const track = (combo.trackId && TRACKS.find(t => t.id === combo.trackId))
                || TRACKS.find(t => t.name === combo.track);
            if (!car || !track) return null;
            return { carId: car.id, trackId: track.id };
        }).filter(Boolean);
    }

    driverData = Array.isArray(schedule.drivers) ? schedule.drivers : [];

    renderGrid();
}

// Handle a user picking a previously-exported (or autosaved) JSON file to import
function handleImportFileSelected(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const schedule = JSON.parse(e.target.result);
            applySchedule(schedule);
            autoSave();
            alert("Event schedule imported — you're back where you left off.");
        } catch (err) {
            alert("Couldn't import that file: " + err.message);
        }
    };
    reader.onerror = () => alert("Couldn't read that file.");
    reader.readAsText(file);

    // Reset the input so selecting the same file again still fires 'change'
    importFileInput.value = "";
}

// Persist the current state to localStorage so a page refresh doesn't lose progress
function autoSave() {
    try {
        const snapshot = buildStateSnapshot();
        localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(snapshot));
        if (autoSaveStatus) {
            const time = new Date(snapshot.savedAt).toLocaleTimeString();
            autoSaveStatus.textContent = `Auto-saved at ${time}`;
        }
    } catch (err) {
        // Storage can fail (private browsing, quota, etc.) - fail silently
        // in the UI but leave a trace in the console for debugging.
        console.warn("Autosave failed:", err);
    }
}

// Wipe everything back to a blank slate: default parameters, no combos,
// no driver data, and no autosaved session to restore next time.
function resetCalculator() {
    const confirmed = confirm(
        "Reset the calculator? This clears all car/track combos, driver data, " +
        "and saved progress, and restores default parameters. This can't be undone."
    );
    if (!confirmed) return;

    setParameters(DEFAULT_PARAMETERS);
    activeCombos = [];
    driverData = [];

    try {
        localStorage.removeItem(AUTOSAVE_KEY);
    } catch (err) {
        console.warn("Could not clear autosave:", err);
    }

    if (autoSaveStatus) {
        autoSaveStatus.textContent = "Autosave enabled";
    }

    renderGrid();
}

// On load, silently restore the last autosaved session, if any
function restoreAutoSave() {
    try {
        const raw = localStorage.getItem(AUTOSAVE_KEY);
        if (!raw) return;
        const schedule = JSON.parse(raw);
        applySchedule(schedule);
        if (autoSaveStatus && schedule.savedAt) {
            const time = new Date(schedule.savedAt).toLocaleTimeString();
            autoSaveStatus.textContent = `Restored autosave from ${time}`;
        }
    } catch (err) {
        console.warn("Could not restore autosave:", err);
    }
}

// Launch application script tracking execution
init();
