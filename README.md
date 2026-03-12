# repeater-monitor

A web-based VHF/UHF repeater monitor built on [ka9q-radio](https://github.com/ka9q/ka9q-radio) and [ka9q-python](https://github.com/mijahauan/ka9q-python).

Displays nearby repeaters on a live map, monitors them for activity via SNR-based squelch, and streams audio to the browser in real time.

## How It Works

The application connects to a running `radiod` instance through `ka9q-python`. It tells `ka9q-python` which frequencies to monitor (NFM demodulation at 12 kHz sample rate) and the library handles all RTP stream management, SSRC allocation, and multicast routing internally.

When a repeater's SNR exceeds the squelch threshold, the map marker turns green and the signal meter animates. Clicking "Listen Live" on any repeater opens a `ManagedStream` that delivers decoded audio samples over a WebSocket. 

**Note on Audio Alignment:** The Opus audio stream is aligned to 12000Hz (240 samples per 20ms) to match the internal `radiod` timing. This ensures a stable, gap-free stream without the repetitive noise common in mismatched decoding rates.

## Architecture

```
Browser (Leaflet map + Web Audio API)
  │
  ├── wss:///ws/control     ← search, activity updates (JSON)
  └── wss:///ws/audio/{freq} ← raw Float32 audio samples (binary)
  │
FastAPI + Uvicorn (backend/)
  │
  ├── radio_controller.py   ← channel setup, status polling, squelch
  ├── audio_streamer.py     ← ManagedStream → WebSocket bridge
  └── repeater_data.py      ← KML parser, grid square conversion
  │
ka9q-python
  │
radiod (ka9q-radio)
```

## Requirements

- Python 3.11+
- A running `radiod` instance (e.g., Airspy R2 with `radiod@airspy-generic`)
- [ka9q-python](https://github.com/ka9q/ka9q-python) installed in the venv

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Generate self-signed TLS certs for HTTPS (required for browser audio):

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -keyout certs/key.pem \
  -out certs/cert.pem -days 365 -nodes -subj '/CN=localhost'
```

## Usage

```bash
./repeater-monitor.sh start     # Start in background
./repeater-monitor.sh stop      # Stop
./repeater-monitor.sh restart   # Restart
./repeater-monitor.sh status    # Check if running
```

Then open `https://<hostname>:8000` in a browser.

### Controls

- **Radiod Host** — the mDNS name of your radiod status channel (e.g., `airspy-status.local`)
- **Grid Square** — Maidenhead locator or `lat,lon` for your location
- **Band Segment** — 2m, 1.25m, or 70cm sub-bands (matched to Airspy's ~5 MHz bandwidth)
- **Squelch** — SNR threshold in dB; repeaters above this light up green
- **Radius** — search radius in km for filtering repeaters from the KML dataset

## Repeater Data

Repeater locations are loaded from a KML file (`repeaters_*.kml`) exported from [RepeaterBook](https://www.repeaterbook.com). Place the KML in the project root.

## License

MIT
