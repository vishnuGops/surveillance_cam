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

### 24/7 Always-On Mode (System Tray + Auto-Start + Auto-Revive)

```powershell
# Install and launch EYEz in the Windows System Tray (auto-starts on reboot & revives if closed)
.\scripts\install_autostart.ps1

# Check live 24/7 status, Tailscale URL & logs
.\scripts\status_eyez.ps1

# Enable persistent tailnet-only HTTPS access on port 8443 (from any Tailscale device)
.\scripts\setup_tailscale.ps1

# Uninstall auto-start and stop EYEz
.\scripts\uninstall_autostart.ps1
```

### Manual Foreground Run

```powershell
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
- `night_vision.py` — Per-camera real-time Auto Night Vision (temporal denoise + gamma LUT + CLAHE)
- `eyez_service.py` — 24/7 Windows System Tray launcher, watchdog supervisor, and sleep prevention
- `static/` — Two-tab matte-black & orange EYEz dashboard (`index.html`, `styles.css`, `app.js`, bundled `Iosevka` fonts)
- `docs/` — Synchronized project documentation (`DOCUMENTATION.md` & `DOCUMENTATION.html`)
- `scripts/` — `install_autostart.ps1`, `uninstall_autostart.ps1`, `status_eyez.ps1`, and `sync_docs.py`
