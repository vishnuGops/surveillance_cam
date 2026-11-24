# HomeWatch NVR — Project & Architecture Documentation

> **Single Source of Truth:** This document (`docs/DOCUMENTATION.md`) is synchronized with `docs/DOCUMENTATION.html` via `python scripts/sync_docs.py`. Every feature change, API addition, or architectural decision must be recorded here and synced.

---

## 1. Overview

**HomeWatch NVR (`surveillance_cam`)** is a lightweight, local-first multi-camera home surveillance application built with Python, FastAPI, OpenCV, and PyAV. It turns a Windows PC with one or more USB webcams into a browser-accessible Network Video Recorder (NVR) with continuous 5-minute H.264 loop recording, structured disk storage on `C:`, rolling retention cleanup, and a modern two-tab dashboard.

### Current Feature Set (`v0.2.0`)

- **Multi-Camera USB Auto-Discovery:** Automatically scans connected USB webcams on startup and on demand (`Scan USB`), pulls Windows PnP friendly device names, and persists per-camera configuration.
- **Live Multi-Camera Streaming:** Independent background capture thread per camera serving simultaneous MJPEG viewers without exclusive hardware contention.
- **Continuous 5-Minute H.264 Loop Recording:** Dedicated per-camera PyAV encoder thread recording browser-playable MP4 loops (`libx264` + `yuv420p` + `faststart`) with wall-clock PTS timing and auto-generated JPEG thumbnails.
- **Structured `C:\SurveillanceData` Storage:** Organizes recordings by `<camera_id>/<YYYY-MM-DD>/<HH-MM-SS>.mp4` alongside `.jpg` thumbnails, `.meta.json` sidecars, snapshots, and `config.json`.
- **Rolling Storage Retention & Star Protection:** Automatically deletes the oldest unstarred clips past the configured size cap (default **50 GB**) or retention window (default **7 days**). Starred/locked clips are immune to automatic cleanup and manual deletion.
- **Two-Tab Web Dashboard:**
  - **Cameras:** Glassmorphic responsive Grid / Focus wall, live `REC` segment timers, loop progress bars, inline rename modal, timestamp toggle, fullscreen, and snapshot saving.
  - **Recordings:** Integrated HTML5 `<video>` theater with HTTP `206 Partial Content` scrubbing, `0.5× / 1× / 2× / 4×` speed controls, prev/next loop stepping, camera/date/starred filters, star/lock toggle, download, and delete.

---

## 2. System Architecture

### Module Map

| File | Responsibility |
| --- | --- |
| `app.py` | FastAPI application factory, lifespan hooks, MJPEG streaming endpoints, REST APIs for cameras/recordings/storage, and CLI entrypoint. |
| `camera.py` | `CameraManager` (USB auto-discovery, Windows friendly name lookup, periodic retention sweep) and `CameraStream` (per-camera capture thread, timestamp HUD, MJPEG encoding, `frame_hooks`). |
| `recorder.py` | `LoopRecorder` — isolated per-camera encoder thread converting BGR frames into rotating H.264 MP4 segments, thumbnails, and metadata sidecars. |
| `storage.py` | `StorageManager` — structured path allocation under `C:\SurveillanceData`, path-traversal validation, clip indexing, star/lock persistence, and two-pass rolling retention cleanup. |
| `config.py` | `AppSettings` and thread-safe `ConfigStore` persisted atomically to `C:\SurveillanceData\config.json`. |
| `static/index.html` | Semantic two-tab dashboard shell + native `<dialog>` modals for storage settings and camera renaming. |
| `static/styles.css` | Dark glassmorphic UI using CSS Grid, container queries (`@container`), logical properties, `aspect-ratio`, and CSS custom properties for progress bars. |
| `static/app.js` | State management, camera wall reconciliation, bandwidth-saving stream pausing on tab switch, recording theater controls, and API polling. |
| `scripts/sync_docs.py` | Deterministic generator converting `docs/DOCUMENTATION.md` into the standalone `docs/DOCUMENTATION.html` with drift checking (`--check`). |

### Data & Threading Flow

```text
USB Webcam #N
     │
     ▼
[CameraStream Capture Thread]  (OpenCV CAP_DSHOW + MJPG @ target FPS)
     │
     ├──► Optional frame_hooks (extensible for motion / AI detection)
     ├──► Optional timestamp + REC overlay
     │
     ├──► Non-blocking Queue (max 60 frames)
     │         │
     │         ▼
     │    [LoopRecorder Encoder Thread]  (PyAV libx264, yuv420p, movflags=faststart)
     │         │
     │         ▼  (every 5 min or on stop)
     │    C:\SurveillanceData\recordings\<cam_id>\<YYYY-MM-DD>\<HH-MM-SS>.{mp4,jpg,meta.json}
     │         │
     │         ▼
     │    [StorageManager.enforce_retention()]  (age pass -> size cap pass; skips starred)
     │
     └──► JPEG Encode ──► Condition Notify ──► FastAPI /api/cameras/{id}/stream (MJPEG)
                                                FastAPI /api/cameras/{id}/snapshot
```

---

## 3. Design Choices & Architectural Decisions (ADRs)

| ID | Decision | Rationale |
| --- | --- | --- |
| **ADR-01** | **FastAPI + Uvicorn over Flask** | Native async streaming (`StreamingResponse`), clean Pydantic request validation, built-in lifespan startup/shutdown hooks, and zero-friction readiness for future WebSockets/SSE alerts. |
| **ADR-02** | **Single capture thread per camera with `threading.Condition`** | USB webcams on Windows lock exclusively to one process/handle. Broadcasting encoded frames via a condition variable lets unlimited browser tabs view the same camera with zero busy-waiting. |
| **ADR-03** | **`CAP_DSHOW` + constructor `params` (`MJPG` fourcc) on Windows** | DirectShow opens USB webcams faster than MSMF on Windows, and passing `CAP_PROP_FOURCC=MJPG`, width, height, and FPS directly to the `cv2.VideoCapture(idx, CAP_DSHOW, params)` constructor negotiates hardware MJPG (~30 FPS at 720p) instead of silently staying in uncompressed YUY2 (~7.5 FPS). |
| **ADR-04** | **PyAV (`libx264` / `yuv420p` / `faststart`) over OpenCV `VideoWriter`** | OpenCV's default `mp4v` codec does not play in Chrome/Edge HTML5 `<video>` elements. PyAV bundles `libx264` directly inside `.venv` (no external `ffmpeg` install required) and produces compact, browser-native MP4s with instant HTTP range scrubbing. |
| **ADR-05** | **Wall-clock millisecond PTS (`Fraction(1, 1000)`)** | USB webcam framerates fluctuate with ambient lighting/auto-exposure (e.g., 8 FPS at night vs 30 FPS in daylight). Using monotonic wall-clock PTS guarantees every 5-minute clip plays back at accurate real-time speed. |
| **ADR-06** | **Atomic `.part.mp4` recording & startup recovery** | Recording into `.part.mp4` and renaming to `.mp4` on flush prevents the Recordings tab from listing incomplete/unplayable files. Stale `.part.mp4` files from power loss are cleaned on startup. |
| **ADR-07** | **Isolated recorder thread + bounded queue (`maxsize=60`)** | Decouples H.264 CPU encoding and disk writes from the capture thread so live MJPEG monitoring stays responsive even under multi-camera load. |
| **ADR-08** | **Two-pass rolling retention with Star/Lock immunity** | Protects `C:` from filling up during 24/7 recording (Pass 1: delete unlocked clips older than `max_retention_days`; Pass 2: delete oldest unlocked clips until under `max_storage_gb`), while guaranteeing starred clips are never pruned. |
| **ADR-09** | **Zero-build vanilla HTML/CSS/JS + pause streams on Recordings tab** | Keeps the stack lightweight with zero Node build pipeline. Pausing hidden MJPEG `<img>` elements when switching to Recordings frees browser decoding/network resources for smooth MP4 playback. |
| **ADR-10** | **Single-source Markdown → HTML doc sync (`scripts/sync_docs.py`)** | Keeps `docs/DOCUMENTATION.md` and standalone `docs/DOCUMENTATION.html` strictly synchronized with verifiable SHA-256 sync checks. |

---

## 4. Storage Layout & Data Schema

All runtime data is stored under `C:\SurveillanceData` (overridable via `SURVEILLANCE_DATA_DIR` or `--data-dir`):

```text
C:\SurveillanceData\
├── config.json
├── snapshots\
│   └── cam-0_20261124_002510.jpg
└── recordings\
    └── cam-0\
        └── 2026-11-24\
            ├── 00-25-00.mp4         # Browser-playable H.264 MP4 (faststart)
            ├── 00-25-00.jpg         # 480px JPEG preview thumbnail
            └── 00-25-00.meta.json   # Sidecar metadata & lock status
```

### Recording Metadata Sidecar (`*.meta.json`)

```json
{
  "camera_id": "cam-0",
  "camera_name": "NexiGo N60 FHD Webcam",
  "started_at": "2026-11-24T00:25:00",
  "ended_at": "2026-11-24T00:30:00",
  "duration_seconds": 300.0,
  "width": 1280,
  "height": 720,
  "frames": 7420,
  "locked": false
}
```

### Persistent Configuration (`C:\SurveillanceData\config.json`)

```json
{
  "segment_duration_seconds": 300,
  "max_storage_gb": 50.0,
  "max_retention_days": 7,
  "auto_record_new_cameras": true,
  "cameras": {
    "cam-0": {
      "id": "cam-0",
      "index": 0,
      "name": "NexiGo N60 FHD Webcam",
      "enabled": true,
      "recording": true,
      "show_timestamp": true,
      "width": 1280,
      "height": 720,
      "fps": 30
    }
  }
}
```

---

## 5. API Reference

### Multi-Camera Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/cameras` | Returns all registered cameras with live telemetry, recording timers, storage stats, and settings. |
| `POST` | `/api/cameras/scan` | Probes USB indices (`0..max_probe_cameras`) and registers any newly connected cameras. |
| `PATCH` | `/api/cameras/{cam_id}` | Updates camera fields: `name`, `recording`, `show_timestamp`, `enabled`. Persists to `config.json`. |
| `GET` | `/api/cameras/{cam_id}/stream` | Live MJPEG stream (`multipart/x-mixed-replace; boundary=frame`). |
| `GET` | `/api/cameras/{cam_id}/snapshot` | Returns latest JPEG frame. Pass `?save=1` to also archive to `C:\SurveillanceData\snapshots\`. |

### Recordings & Playback Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/recordings` | Lists finalized clips (newest first). Query params: `camera_id`, `date` (`YYYY-MM-DD`), `starred_only` (`bool`). |
| `GET` | `/api/recordings/media/{clip_id}` | Serves H.264 `.mp4` with HTTP `206 Partial Content` range support. Pass `?download=1` for attachment download. |
| `GET` | `/api/recordings/thumb/{clip_id}` | Serves the clip's JPEG preview thumbnail (`Cache-Control: max-age=3600`). |
| `PATCH` | `/api/recordings/lock/{clip_id}` | Sets `{"locked": true | false}` to star/protect or unprotect a clip. |
| `DELETE` | `/api/recordings/item/{clip_id}` | Deletes an unlocked clip + thumbnail + metadata. Returns `409 Conflict` if starred/locked. |

### Storage & Retention Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/storage` | Returns `C:` disk space stats, total recordings bytes, clip/locked counts, and active retention settings. |
| `PATCH` | `/api/storage/settings` | Updates `max_storage_gb`, `max_retention_days`, `segment_duration_seconds`, and `auto_record_new_cameras`, then runs retention cleanup. |
| `POST` | `/api/storage/cleanup` | Manually triggers rolling retention cleanup immediately. |

### Legacy Convenience Aliases (First Camera)

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/video_feed` | MJPEG stream of the first registered camera. |
| `GET` | `/snapshot` | Latest JPEG snapshot of the first registered camera. |
| `GET` | `/api/status` | Summary status (`cameras_total`, `cameras_online`, `cameras_recording`, `storage`). |

---

## 6. Configuration, Environment Variables & CLI

### Running the Server

```powershell
# Standard localhost startup
.\.venv\Scripts\python.exe app.py

# Custom storage path, port, or loop settings
.\.venv\Scripts\python.exe app.py --host 127.0.0.1 --port 8000 --data-dir C:\SurveillanceData --segment-seconds 300 --max-storage-gb 50 --max-days 7
```

### Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `SURVEILLANCE_DATA_DIR` | `C:\SurveillanceData` | Root directory for recordings, snapshots, and `config.json`. |
| `SURVEILLANCE_HOST` | `127.0.0.1` | Bind host (`0.0.0.0` to expose on LAN when ready). |
| `SURVEILLANCE_PORT` | `8000` | HTTP server port. |
| `SURVEILLANCE_SEGMENT_SECONDS` | `300` | Default continuous loop duration in seconds (5 minutes). |
| `SURVEILLANCE_MAX_STORAGE_GB` | `50.0` | Rolling storage budget in GB (`0` disables size cap). |
| `SURVEILLANCE_MAX_RETENTION_DAYS` | `7` | Rolling age retention in days (`0` disables age cap). |
| `SURVEILLANCE_AUTO_RECORD` | `true` | Automatically start loop recording on newly discovered cameras. |
| `SURVEILLANCE_WIDTH` | `1280` | Default requested capture width. |
| `SURVEILLANCE_HEIGHT` | `720` | Default requested capture height. |
| `SURVEILLANCE_FPS` | `30` | Default target capture FPS. |
| `SURVEILLANCE_JPEG_QUALITY` | `80` | MJPEG frame compression quality (`10–100`). |
| `SURVEILLANCE_MAX_CAMERAS` | `8` | Upper USB index bound for camera auto-discovery. |

---

## 7. Web Dashboard Guide

1. **Header Bar:** Switch between **Cameras** and **Recordings**, click the **Storage** pill to inspect `C:` disk space and adjust retention limits, or click **Scan USB** after plugging in additional webcams.
2. **Cameras Tab:**
   - Switch between **Grid** (responsive multi-cam wall) and **Focus** (single expanded camera view).
   - Each card shows live online status, pulsing `REC` loop timer + progress bar, resolution/FPS HUD, and quick actions (**Rec On/Off**, **Snapshot**, **TS**, **Rename**, **Focus**, **Full**).
   - Toggling **Rec On → Rec Off** immediately flushes and saves the current loop so it appears in **Recordings**.
3. **Recordings Tab:**
   - Filter clips by **Camera**, **Date**, or **★ Starred Only**.
   - Play directly in the theater with native timeline scrubbing, `0.5× / 1× / 2× / 4×` speed pills, **Prev / Next** loop navigation, **Star** protection, **Download**, and **Delete**.

---

## 8. Keeping Docs in Sync

`docs/DOCUMENTATION.md` is the editable source file, and `docs/DOCUMENTATION.html` is generated deterministically from it.

```powershell
# Regenerate docs/DOCUMENTATION.html from docs/DOCUMENTATION.md
.\.venv\Scripts\python.exe scripts/sync_docs.py

# Verify both files are in sync (exits non-zero if out of sync)
.\.venv\Scripts\python.exe scripts/sync_docs.py --check
```

---

## 9. Changelog

### `v0.2.2` — 2026-11-24
- Fixed DirectShow MJPG negotiation in `camera.py` by passing `CAP_PROP_FOURCC=MJPG`, width, height, and FPS via `cv2.VideoCapture(index, CAP_DSHOW, params)`, boosting USB 720p capture from ~7.5 FPS (`YUY2`) to ~30 FPS (`MJPG`).
- Enhanced **Focus** layout mode to expand to full theater width and show a quick camera switcher bar (`#focus-strip`) when multiple cameras are connected.

### `v0.2.1` — 2026-11-24
- Moved burned-in OpenCV timestamp overlay from top-left to bottom-left (`camera.py`) so it never overlaps the floating `LIVE` / `REC` HUD pills.
- Added global `[hidden] { display: none !important; }` rule in `static/styles.css` so turning off recording immediately hides the red `REC` badge instead of leaving it stuck at `00:00`.
- Cleared and unloaded `<video>` playback via `selectClip(null)` + `recordingPlayer.load()` when deleting recordings (including when the final clip is deleted).

### `v0.2.0` — 2026-11-24
- Added multi-camera USB auto-discovery (`CameraManager`, `Scan USB`, Windows friendly device names, persistent `config.json`).
- Added continuous 5-minute H.264 loop recording (`recorder.py` via PyAV `libx264` + `faststart` + JPEG thumbnails).
- Added structured `C:\SurveillanceData` storage layout (`storage.py`) with two-pass rolling retention (50 GB / 7 days default) and Star/Lock clip protection.
- Redesigned UI into a sleek glassmorphic two-tab dashboard (**Cameras** and **Recordings**) with Grid/Focus view, native `<dialog>` modals, playback speed controls, and HTTP range scrubbing.
- Added synchronized Markdown + standalone HTML documentation (`docs/DOCUMENTATION.md`, `docs/DOCUMENTATION.html`, `scripts/sync_docs.py`).

### `v0.1.0` — 2026-11-23
- Initial lightweight localhost FastAPI + OpenCV USB webcam streaming server (`app.py`, `camera.py`, `config.py`, `static/`).
- Added live MJPEG streaming (`/video_feed`), instant JPEG snapshot (`/snapshot`), telemetry (`/api/status`), and timestamp overlay toggle.
