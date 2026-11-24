# EYEz (`surveillance_cam`)

A lightweight multi-camera Python + FastAPI localhost home surveillance NVR for USB webcams, featuring a matte-black & tactical-orange **EYEz** dashboard rendered in **Iosevka**, click-to-focus camera grid cards, continuous 5-minute H.264 loop recording, and structured `C:\SurveillanceData` storage with rolling retention.

## Documentation

Full architecture, design decisions (ADRs), API reference, storage schema, and changelog are maintained in a synchronized pair:

- **Markdown:** [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md)
- **Standalone HTML (open in any browser):** [`docs/DOCUMENTATION.html`](docs/DOCUMENTATION.html)

Whenever you update `docs/DOCUMENTATION.md`, keep the HTML copy in sync with:

```powershell
.\.venv\Scripts\python.exe scripts/sync_docs.py
.\.venv\Scripts\python.exe scripts/sync_docs.py --check
```

## Quick Start (Windows PowerShell)

```powershell
# Run using the included virtual environment
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:8000** in your browser.

### Optional CLI Arguments

```powershell
.\.venv\Scripts\python.exe app.py --port 8000 --data-dir C:\SurveillanceData --segment-seconds 300 --max-storage-gb 50 --max-days 7
```

## Project Structure

- `config.py` — Persistent JSON configuration store (`C:\SurveillanceData\config.json`)
- `storage.py` — Structured `C:\SurveillanceData` file layout, indexing, clip locking, and rolling retention cleanup
- `recorder.py` — Non-blocking PyAV H.264 continuous loop recorder & thumbnail generator
- `camera.py` — Multi-camera USB auto-discovery (`CameraManager`) and threaded capture (`CameraStream`)
- `app.py` — FastAPI server with multi-camera, recordings, HTTP range playback, and storage endpoints
- `static/` — Two-tab dark glassmorphic dashboard (`index.html`, `styles.css`, `app.js`)
- `docs/` — Synchronized project documentation (`DOCUMENTATION.md` & `DOCUMENTATION.html`)
- `scripts/sync_docs.py` — Deterministic Markdown → HTML documentation sync tool
