# Home Surveillance Cam

A lightweight Python + FastAPI localhost surveillance server for a USB webcam, structured so features like motion detection, recording, alerts, and authentication can be added cleanly later.

## Stack

- **Capture & Encoding**: OpenCV (`opencv-python-headless`) in a dedicated background thread with automatic reconnection and an extensible `frame_hooks` pipeline.
- **Web & Streaming Server**: FastAPI + Uvicorn serving an MJPEG stream (`/video_feed`), instant snapshots (`/snapshot`), and live telemetry (`/api/status`).
- **Frontend**: Zero-build dark-mode HTML/CSS/JS dashboard (`static/`).

## Quick Start (Windows PowerShell)

```powershell
# Activate the virtual environment (already created in .venv)
.\.venv\Scripts\Activate.ps1

# Run the localhost server
python app.py
```

Then open **http://127.0.0.1:8000** in your browser.

### Useful CLI Options

```powershell
# Custom resolution, FPS, port, or camera index
python app.py --camera 0 --width 1920 --height 1080 --fps 30 --port 8000

# Expose on your local network later (only when ready)
python app.py --host 0.0.0.0 --port 8000
```

## Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/` | `GET` | Live surveillance viewer UI |
| `/video_feed` | `GET` | MJPEG live stream (`multipart/x-mixed-replace`) |
| `/snapshot` | `GET` | Instant JPEG snapshot from the latest frame |
| `/api/status` | `GET` | Camera telemetry (online, resolution, FPS, viewers, uptime) |
| `/api/timestamp` | `POST` | Toggle on-frame timestamp overlay (`{"enabled": true}`) |

## Project Structure

- `config.py` — Environment-backed configuration defaults
- `camera.py` — Threaded `CameraStream` capture loop + `frame_hooks` extension point
- `app.py` — FastAPI server, streaming routes, and CLI entrypoint
- `static/` — Lightweight live viewer (`index.html`, `styles.css`, `app.js`)
