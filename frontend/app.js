let map;
let markers = {}; // ssrc -> Leaflet Marker
let repeatersData = [];
let wsControl;
let wsAudio;

// DOM Elements
const hostInput = document.getElementById('hostInput');
const locationInput = document.getElementById('locationInput');
const searchBtn = document.getElementById('searchBtn');
const bandSelect = document.getElementById('bandSelect');
const squelchSlider = document.getElementById('squelchSlider');
const squelchValue = document.getElementById('squelchValue');
const radiusSlider = document.getElementById('radiusSlider');
const radiusValue = document.getElementById('radiusValue');
const wsStatus = document.getElementById('ws-status');
const wsText = document.getElementById('ws-text');
const repeaterList = document.getElementById('repeaterList');
const repeaterCount = document.getElementById('repeaterCount');

const audioPanel = document.getElementById('audio-panel');
const stopAudioBtn = document.getElementById('stopAudioBtn');
const audioRepeaterCallsign = document.getElementById('audio-repeater-callsign');
const audioRepeaterFreq = document.getElementById('audio-repeater-freq');

// Custom Icons
const defaultIcon = L.divIcon({
    className: 'custom-icon',
    html: `<div style="width:16px;height:16px;background:#3b82f6;border-radius:50%;border:2px solid #fff;box-shadow:0 0 5px rgba(0,0,0,0.5);"></div>`,
    iconSize: [16, 16]
});

const activeIcon = L.divIcon({
    className: 'custom-icon',
    html: `<div style="width:20px;height:20px;background:#10b981;border-radius:50%;border:2px solid #fff;box-shadow:0 0 15px #10b981;"></div>`,
    iconSize: [20, 20]
});

// Init Map
function initMap() {
    map = L.map('map').setView([38.5, -91.0], 5); // Default US center

    // Use CartoDB Dark Matter tiles for modern look
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsControl = new WebSocket(`${protocol}//${window.location.host}/ws/control`);

    wsControl.onopen = () => {
        wsStatus.className = 'status-dot connected';
        wsText.textContent = `Connected to ${hostInput.value}`;
        // Auto search on load
        triggerSearch();
    };

    wsControl.onclose = () => {
        wsStatus.className = 'status-dot disconnected';
        wsText.textContent = 'Disconnected - Retrying...';
        setTimeout(connectWebSocket, 3000);
    };

    wsControl.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'results') {
            handleSearchResults(data);
        } else if (data.type === 'activity') {
            handleActivityUpdate(data);
        } else if (data.type === 'error') {
            alert(data.message);
        }
    };
}

function triggerSearch() {
    if (wsControl.readyState !== WebSocket.OPEN) return;

    // Clear Existing
    for (let id in markers) {
        map.removeLayer(markers[id]);
    }
    markers = {};
    repeaterList.innerHTML = '';

    wsControl.send(JSON.stringify({
        type: 'search',
        radiod_host: hostInput.value,
        location: locationInput.value,
        band: bandSelect.value,
        squelch: parseFloat(squelchSlider.value),
        radius: parseFloat(radiusSlider.value)
    }));
}

function handleSearchResults(data) {
    wsText.textContent = `Connected to ${hostInput.value}`;
    repeatersData = data.repeaters;
    repeaterCount.textContent = repeatersData.length;

    if (data.lat && data.lon) {
        map.setView([data.lat, data.lon], 9);
        L.marker([data.lat, data.lon], {
            icon: L.divIcon({
                className: 'custom-icon',
                html: `<div style="width:12px;height:12px;background:#ef4444;border-radius:50%;border:2px solid #fff;"></div>`
            })
        }).addTo(map).bindPopup('Your Location');
    }

    repeatersData.forEach(rep => {
        const lat = parseFloat(rep.Lat || rep.lat);
        const lon = parseFloat(rep.Long || rep.lng || rep.lon);
        const freqHz = parseFloat(rep.Downlink || rep.freq) * 1e6;

        // Add Marker
        const marker = L.marker([lat, lon], { icon: defaultIcon }).addTo(map);
        marker.bindPopup(`
            <div class="dark-popup">
                <h4>${rep.Callsign || 'Unknown'}</h4>
                <p><strong>Freq:</strong> ${rep.Downlink || rep.freq} MHz</p>
                <p><strong>Offset:</strong> ${rep.Offset || 'None'}</p>
                <p><strong>Tone:</strong> ${rep.Tone || '-'}</p>
                <button onclick="listenToRepeater(${freqHz}, '${rep.Callsign}', '${rep.Downlink}')" style="margin-top:10px; padding: 5px; font-size: 0.8rem;">Listen Live</button>
            </div>
        `);
        markers[freqHz] = marker;

        // Add List Item
        const li = document.createElement('li');
        li.className = 'repeater-item';
        li.id = `rep-${freqHz}`;
        li.innerHTML = `
            <div class="rep-header">
                <span class="rep-call">${rep.Callsign || 'RPT'}</span>
                <span class="rep-freq">${rep.Downlink || rep.freq}</span>
            </div>
            <div class="rep-details">
                <span>Dist: ${rep.distance_km.toFixed(1)} km</span>
                <span>Tone: ${rep.Tone || '-'}</span>
            </div>
            <div class="signal-meter">
                <div class="signal-fill" id="sig-${freqHz}"></div>
            </div>
        `;
        li.onclick = () => {
            map.setView([lat, lon], 12);
            marker.openPopup();
        };
        repeaterList.appendChild(li);
    });
}

function handleActivityUpdate(data) {
    const freqHz = data.freq;
    const isAct = data.isActive;
    const snr = parseFloat(data.snr);

    const li = document.getElementById(`rep-${freqHz}`);
    const sigFill = document.getElementById(`sig-${freqHz}`);
    const marker = markers[freqHz];

    if (li && sigFill && marker) {
        if (isAct) {
            li.classList.add('active-signal');
            marker.setIcon(activeIcon);
        } else {
            li.classList.remove('active-signal');
            marker.setIcon(defaultIcon);
        }

        // Map SNR to 0-100% (assuming max around 30dB for UI scale)
        const pct = Math.max(0, Math.min(100, (snr / 30) * 100));
        sigFill.style.width = `${pct}%`;
    }
}

let audioCtx = null;
let nextAudioTime = 0;

function initAudio() {
    if (!audioCtx) {
        // ka9q RadiodStream typically emits 48000 Hz or the channel's sample rate.
        // The backend asks for 12000 Hz in radio_controller.py
        audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 12000 });
    }
    if (audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
    nextAudioTime = 0;
}

function listenToRepeater(freqHz, callsign, freq) {
    // Disconnect old audio if any
    if (wsAudio) {
        wsAudio.close();
    }

    initAudio();

    audioRepeaterCallsign.textContent = callsign;
    audioRepeaterFreq.textContent = freq + ' MHz';
    audioPanel.classList.remove('hidden');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsAudio = new WebSocket(`${protocol}//${window.location.host}/ws/audio/${freqHz}`);
    wsAudio.binaryType = 'arraybuffer';

    wsAudio.onmessage = (event) => {
        // Data is raw Float32Array from backend RadiodStream
        const floats = new Float32Array(event.data);
        if (floats.length === 0) return;

        const buffer = audioCtx.createBuffer(1, floats.length, audioCtx.sampleRate);
        buffer.copyToChannel(floats, 0);

        const source = audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(audioCtx.destination);

        // Schedule playback smoothly
        if (nextAudioTime < audioCtx.currentTime) {
            nextAudioTime = audioCtx.currentTime + 0.05; // 50ms buffer
        }
        source.start(nextAudioTime);
        nextAudioTime += buffer.duration;
    };

    // Close popup
    map.closePopup();
}

stopAudioBtn.addEventListener('click', () => {
    if (wsAudio) {
        wsAudio.close();
        wsAudio = null;
    }
    audioPanel.classList.add('hidden');
});

// Event Listeners
searchBtn.addEventListener('click', triggerSearch);
locationInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') triggerSearch();
});
bandSelect.addEventListener('change', triggerSearch);

squelchSlider.addEventListener('input', (e) => {
    squelchValue.textContent = e.target.value;
});
squelchSlider.addEventListener('change', (e) => {
    if (wsControl.readyState === WebSocket.OPEN) {
        // Resend search to update squelch setting globally
        triggerSearch();
    }
});

radiusSlider.addEventListener('input', (e) => {
    radiusValue.textContent = e.target.value;
});
radiusSlider.addEventListener('change', (e) => {
    if (wsControl.readyState === WebSocket.OPEN) {
        triggerSearch();
    }
});

// App Entry
initMap();
connectWebSocket();
