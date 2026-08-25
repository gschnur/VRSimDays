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

// Document Object Selectors
const carSelect = document.getElementById("carSelect");
const trackSelect = document.getElementById("trackSelect");
const addComboBtn = document.getElementById("addComboBtn");
const exportScheduleBtn = document.getElementById("exportScheduleBtn");
const comboTableBody = document.getElementById("comboTableBody");
const emptyState = document.getElementById("emptyState");

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
    [numDriversInput, accLapsInput, hotLapsInput, driverChangeInput, comboChangeInput].forEach(input => {
        input.addEventListener("input", calculateEventTime);
    });

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
}

function removeCombo(index) {
    activeCombos.splice(index, 1);
    renderGrid();
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

// Build a blank driver/combo schedule from current config and download it as JSON
function exportEventSchedule() {
    const numDrivers = parseInt(numDriversInput.value) || 0;

    if (numDrivers <= 0) {
        alert("Set a number of drivers before exporting.");
        return;
    }
    if (activeCombos.length === 0) {
        alert("Add at least one car & track combo before exporting.");
        return;
    }

    // Combos object: one entry per active combo, numbered in schedule order
    const combos = activeCombos.map((item, index) => {
        const car = CARS.find(c => c.id === item.carId);
        const track = TRACKS.find(t => t.id === item.trackId);
        const parTimeSeconds = track.baseSeconds + car.offset;
        return {
            comboNumber: index + 1,
            car: car.name,
            track: track.name,
            parTime: formatSecondsToMMSS(parTimeSeconds),
            parTimeSeconds: Math.round(parTimeSeconds * 1000) / 1000
        };
    });

    // Drivers object: one blank row per driver, with an empty time field per combo number
    const drivers = [];
    for (let i = 0; i < numDrivers; i++) {
        const driver = { name: "" };
        combos.forEach(combo => {
            driver[`combo${combo.comboNumber}`] = null;
        });
        drivers.push(driver);
    }

    const schedule = { drivers, combos };

    const blob = new Blob([JSON.stringify(schedule, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "event-schedule.json";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// Launch application script tracking execution
init();
