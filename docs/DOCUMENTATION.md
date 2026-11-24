# EYEz — Project & Architecture Documentation

> **Single Source of Truth:** This document (`docs/DOCUMENTATION.md`) is synchronized with `docs/DOCUMENTATION.html` via `python scripts/sync_docs.py`. Every feature change, API addition, or architectural decision must be recorded here and synced.

---

## 1. Overview

**EYEz (`surveillance_cam`)** is a lightweight, local-first multi-camera home surveillance application built with Python, FastAPI, OpenCV, and PyAV. It turns a Windows PC with one or more USB webcams into a matte-black & tactical-orange Network Video Recorder (NVR) with continuous 5-minute H.264 loop recording, structured disk storage on `C:`, rolling retention cleanup, and a Batcomputer-inspired two-tab dashboard rendered entirely in **Iosevka**.

### Current Feature Set (`v0.3.0`)

- **Multi-Camera USB Auto-Discovery:** Automatically scans connected USB webcams on startup and on demand (`SCAN USB`), pulls Windows PnP friendly device names, and persists per-camera configuration.
- **Live Multi-Camera Streaming (`30 FPS` MJPG):** Independent background capture thread per camera using DirectShow constructor parameters (`CAP_PROP_FOURCC=MJPG`) serving simultaneous MJPEG viewers without hardware contention.
- **Continuous 5-Minute H.264 Loop Recording:** Dedicated per-camera PyAV encoder thread recording browser-playable MP4 loops (`libx264` + `yuv420p` + `faststart`) with wall-clock PTS timing and auto-generated JPEG thumbnails.
- **Structured `C:\SurveillanceData` Storage:** Organizes recordings by `<camera_id>/<YYYY-MM-DD>/<HH-MM-SS>.mp4` alongside `.jpg` thumbnails, `.meta.json` sidecars, snapshots, and `config.json`.
- **Rolling Storage Retention & Star Protection:** Automatically deletes the oldest unstarred clips past the configured size cap (default **50 GB**) or retention window (default **7 days**). Starred/locked clips are immune to automatic cleanup and manual deletion.
- **EYEz Two-Tab Tactical Dashboard (Matte Black + Orange + Iosevka):**
  - **Cameras (`01`):** Multi-column Grid view with labeled camera cards (`CH-01 // NAME`), targeting reticles, click-to-focus cards, expansion standby slot when 1 camera is connected, and full-width Focus theater with `← BACK TO GRID` and channel switcher pills.
  - **Recordings (`02`):** Integrated HTML5 `<video>` theater with HTTP `206 Partial Content` scrubbing, `0.5× / 1× / 2× / 4×` speed controls, prev/next loop stepping, camera/date/locked filters, star/lock toggle, download, and delete.

---

## 2. System Architecture

### Module Map

| File | Responsibility |
| --- | --- |
| `app.py` | FastAPI application factory, lifespan hooks, MJPEG streaming endpoints, REST APIs for cameras/recordings/storage, and CLI entrypoint. |
| `camera.py` | `CameraManager` (USB auto-discovery, Windows friendly name lookup, periodic retention sweep) and `CameraStream` (per-camera capture thread, night vision hook, timestamp HUD, MJPEG encoding, `frame_hooks`). |
| `night_vision.py` | `NightVisionProcessor` — per-camera low-light software night vision (`auto` / `on` / `off`) with luminance hysteresis, precomputed shadow-lift gamma LUT, `YCrCb` CLAHE contrast, and motion-aware temporal denoising. |
| `recorder.py` | `LoopRecorder` — isolated per-camera encoder thread converting BGR frames into rotating H.264 MP4 segments, thumbnails, and metadata sidecars. |
| `storage.py` | `StorageManager` — structured path allocation under `C:\SurveillanceData`, path-traversal validation, clip indexing, star/lock persistence, and two-pass rolling retention cleanup. |
| `config.py` | `AppSettings` and thread-safe `ConfigStore` persisted atomically to `C:\SurveillanceData\config.json`. |
| `static/index.html` | Semantic two-tab dashboard shell + native `<dialog>` modals for storage settings and camera renaming. |
| `static/styles.css` | Matte-black + tactical-orange EYEz design system with bundled `Iosevka` `@font-face` rules, corner targeting reticles, CSS Grid, and container queries (`@container`). |
| `static/fonts/` | Locally bundled `Iosevka` Latin `.woff2` weights (`400`, `500`, `600`, `700`) for 100% offline localhost rendering. |
| `static/app.js` | State management, camera wall reconciliation, bandwidth-saving stream pausing on tab switch, recording theater controls, and API polling. |
| `scripts/sync_docs.py` | Deterministic generator converting `docs/DOCUMENTATION.md` into the standalone `docs/DOCUMENTATION.html` with drift checking (`--check`). |
| `eyez_service.py` | 24/7 Windows System Tray launcher & watchdog supervisor (single-instance Named Mutex, crash/hang auto-restart, `SetThreadExecutionState` sleep prevention, rotating logs). |
| `scripts/install_autostart.ps1` | Registers the interactive-session Windows Scheduled Task (`EYEz Surveillance`) with At-Logon + 1-minute auto-revive triggers and a Start Menu shortcut. |
| `scripts/uninstall_autostart.ps1` | Removes the Scheduled Task and stops running EYEz processes cleanly. |
| `scripts/status_eyez.ps1` | Prints Scheduled Task state, active PIDs, live API health, Tailscale status, and recent log entries. |
| `scripts/setup_tailscale.ps1` | Configures persistent, tailnet-only HTTPS access (`tailscale serve --bg --https=8443 http://127.0.0.1:8000`) without interfering with port `443` services or Funnel. |

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
| **ADR-05** | **Wall-clock millisecond PTS (`codec_context.time_base = Fraction(1, 1000)`)** | USB webcam framerates fluctuate (e.g., 8–30.4 FPS). Setting both `stream.time_base` AND `stream.codec_context.time_base` to `Fraction(1, 1000)` prevents 30+ FPS frames from rounding to duplicate `1/30` ticks (which otherwise causes FFmpeg muxer `EINVAL`) and guarantees real-time playback speed. |
| **ADR-06** | **Atomic `.part.mp4` recording & startup recovery** | Recording into `.part.mp4` and renaming to `.mp4` on flush prevents the Recordings tab from listing incomplete/unplayable files. Stale `.part.mp4` files from power loss are cleaned on startup. |
| **ADR-07** | **Isolated recorder thread + bounded queue (`maxsize=60`)** | Decouples H.264 CPU encoding and disk writes from the capture thread so live MJPEG monitoring stays responsive even under multi-camera load. |
| **ADR-08** | **Two-pass rolling retention with Star/Lock immunity** | Protects `C:` from filling up during 24/7 recording (Pass 1: delete unlocked clips older than `max_retention_days`; Pass 2: delete oldest unlocked clips until under `max_storage_gb`), while guaranteeing starred clips are never pruned. |
| **ADR-09** | **Zero-build vanilla HTML/CSS/JS + pause streams on Recordings tab** | Keeps the stack lightweight with zero Node build pipeline. Pausing hidden MJPEG `<img>` elements when switching to Recordings frees browser decoding/network resources for smooth MP4 playback. |
| **ADR-10** | **Single-source Markdown → HTML doc sync (`scripts/sync_docs.py`)** | Keeps `docs/DOCUMENTATION.md` and standalone `docs/DOCUMENTATION.html` strictly synchronized with verifiable SHA-256 sync checks. |
| **ADR-11** | **Locally bundled `Iosevka` `.woff2` + Matte-Black/Orange EYEz UI** | Bundling `Iosevka` (`400–700`) under `static/fonts/` guarantees crisp Batcomputer typography with zero external CDN dependency on localhost, while click-to-focus grid cards keep multi-camera switching immediate and intuitive. |
| **ADR-12** | **Per-camera Auto Software Night Vision (`night_vision.py`)** | Applies motion-aware temporal denoising + precomputed shadow-lift gamma LUT + `YCrCb` luminance CLAHE before both MJPEG streaming and H.264 recording, with hysteresis thresholds (`enter < 68`, `exit > 88`, `1.5s` hold) so lighting flickers never toggle mode rapidly. |
| **ADR-13** | **Interactive-Session Task Scheduler + System Tray Watchdog (`eyez_service.py`) over Session 0 Windows Service** | Windows 10/11 Session 0 services frequently lose DirectShow (`CAP_DSHOW`) / Camera Privacy access to USB webcams. Running `eyez_service.py` via an Interactive-logon Scheduled Task with At-Logon + 1-minute watchdog triggers, a Named Mutex (`Local\EYEzSurveillanceServiceMutex`), unlimited `ExecutionTimeLimit`, and `SetThreadExecutionState(ES_SYSTEM_REQUIRED)` delivers reliable 24/7 USB camera access, auto-revive on close/crash, and sleep prevention without blocking monitor power-off. |
| **ADR-14** | **Tailnet-Only HTTPS via `tailscale serve --https=8443` to `127.0.0.1:8000`** | Keeping EYEz bound strictly to `127.0.0.1:8000` avoids LAN exposure and Windows Firewall holes, guarantees continuous local recording when Tailscale pauses for Surfshark, and isolates EYEz on dedicated tailnet-only HTTPS port `8443` so port `443` Tailscale Funnel services remain untouched and EYEz is never exposed to the public internet. |

---

## 4. Storage Layout & Data Schema

All runtime data is stored under `C:\SurveillanceData` (overridable via `SURVEILLANCE_DATA_DIR` or `--data-dir`):

```text
C:\SurveillanceData\
├── config.json
├── logs\
│   └── eyez.log                     # Rotating watchdog + server logs (5 MB × 5)
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
| `PATCH` | `/api/cameras/{cam_id}` | Updates camera fields: `name`, `recording`, `night_mode` (`auto\|on\|off`), `enabled`. Persists to `config.json`. |
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
| `POST` | `/api/recordings/bulk-delete` | Deletes multiple unlocked clips (`{"ids": [...]}`), skipping any starred/locked clips safely and returning deleted/skipped counts + updated storage stats. |

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
# 24/7 Production Mode (Windows System Tray + Auto-Start on Reboot + Crash/Close Auto-Revive)
.\scripts\install_autostart.ps1

# Check 24/7 service health, Tailscale URL & recent logs
.\scripts\status_eyez.ps1

# Configure persistent Tailscale tailnet-only HTTPS proxy (port 8443)
.\scripts\setup_tailscale.ps1

# Stop and remove 24/7 auto-start
.\scripts\uninstall_autostart.ps1

# Manual foreground run (for development)
.\.venv\Scripts\python.exe app.py
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

1. **Header Bar (`EYEz`):** Switch between `01 CAMERAS` and `02 RECORDINGS`, click the **VAULT** pill to inspect `C:` disk space and adjust retention limits, or click **SCAN USB** after plugging in additional webcams.
2. **Cameras Tab:**
   - **GRID view:** Shows available cameras as named tactical cards (`CH-01 // CAMERA NAME`) in a multi-column grid with targeting reticles; clicking any card header or video viewport immediately focuses that camera.
   - **FOCUS view:** Expands the selected camera full-width with a top command strip (`← BACK TO GRID` + channel switcher pills) while pausing hidden camera streams to save bandwidth.
   - Card controls (**● REC / REC OFF**, **NV:AUTO/ON/OFF**, **SNAP**, **RENAME**, **FULL**) remain visible in both Grid and Focus views; timestamps are always burned into the bottom-left of every feed and recording. Toggling recording off immediately archives the current loop into **Recordings**.
3. **Recordings Tab:**
   - Filter clips by **Camera**, **Date**, or **★ LOCKED ONLY**.
   - Use per-clip checkboxes (with **Shift+Click** range selection), **SELECT ALL**, and the trash **Delete** icon to purge multiple unlocked recordings at once (starred/locked clips remain protected).
   - Select any clip to load it paused, then click the centered tactical Play/Pause overlay to watch with native timeline scrubbing, `0.5× / 1× / 2× / 4×` speed pills, **PREV / NEXT** loop navigation, **STAR / LOCK** protection, **DOWNLOAD**, and **DELETE**.

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

### `v0.6.1` — 2026-11-24
- Added Tailscale tailnet-only HTTPS remote access (`scripts/setup_tailscale.ps1`) on dedicated port `8443` (`https://vish-homeserver.tail796df0.ts.net:8443` → `http://127.0.0.1:8000`), keeping existing port `443` Funnel routes isolated and ensuring zero local recording disruption when Tailscale pauses for Surfshark.
- Added live Tailscale online/URL status reporting to `scripts/status_eyez.ps1`.

### `v0.6.0` — 2026-11-24
- Added `eyez_service.py`: 24/7 Windows System Tray launcher & watchdog supervisor with single-instance Windows Named Mutex, automatic crash & HTTP hang recovery, `SetThreadExecutionState` PC sleep prevention (allowing monitor off), rotating logs at `C:\SurveillanceData\logs\eyez.log`, and programmatic `assets/eyez.ico` export.
- Added `scripts/install_autostart.ps1`, `scripts/uninstall_autostart.ps1`, and `scripts/status_eyez.ps1` to manage the interactive-session Windows Scheduled Task (`EYEz Surveillance`) with At-Logon startup and 1-minute auto-revive watchdog triggers.

### `v0.5.0` — 2026-11-24
- Added multi-selection checkboxes (including **Shift+Click** range selection), **SELECT ALL** (with indeterminate state), selected count indicator, and a bulk **Delete** trash-icon button to the **Recordings** archive sidebar.
- Added `POST /api/recordings/bulk-delete` in `app.py` to delete selected unlocked clips in one batch while safely skipping starred/locked clips.

### `v0.4.1` — 2026-11-24
- Fixed **Focus** mode viewport sizing in `static/styles.css` (`block-size: clamp(300px, calc(100dvb - 19.5rem), 760px)` + `overflow: clip` + `min-block-size: 0` on `<img>`) so the entire 16:9 video frame (including the bottom-left timestamp) and all card action buttons (`REC`, `NV`, `SNAP`, `RENAME`, `FULL`) fit cleanly on screen with zero clipping.
- Enforced always-on timestamps in `camera.py` and `config.py`, and removed the `TS` toggle button from camera cards.

### `v0.4.0` — 2026-11-24
- Added per-camera **Auto Night Vision** (`night_vision.py`) with `NV:AUTO / NV:ON / NV:OFF` controls persisted in `config.json`: enhances both live feeds and recorded H.264 MP4s via motion-aware temporal denoising, shadow-lift gamma LUT, and `YCrCb` luminance CLAHE with anti-flicker hysteresis.
- Added a glowing **green eye HUD icon** (`NV`) on the video viewport whenever Night Vision is actively engaged (plus `| NV` in the burned-in timestamp overlay).
- Refined the **Recordings** video center overlay: clicking Play hides the icon immediately; tapping the playing video keeps playing while revealing the Pause icon (auto-hides after 2.6s); clicking the Pause icon pauses playback; added an opaque matte-backed orange buffering spinner that cleanly masks default browser spinners.

### `v0.3.2` — 2026-11-24
- Disabled auto-selection and autoplay in the **Recordings** tab; users now select a clip from the archive list and click a YouTube-style centered tactical Play/Pause overlay to start or pause playback.
- Removed the `NVR // LOCALHOST` badge from the top header bar for a cleaner **EYEz** wordmark.

### `v0.3.1` — 2026-11-24
- Fixed `av.error.ArgumentError` (`EINVAL`) muxing crash at 30+ FPS in `recorder.py` by explicitly setting `stream.codec_context.time_base = Fraction(1, 1000)` alongside `stream.time_base` so sub-33ms frames never collide on identical `1/30` encoder ticks.
- Updated `_close_segment(discard=True)` on encode exceptions with a brief retry backoff so errors never spam 0-second broken clips.
- Clarified camera card telemetry wording (`N VIEWERS · M SAVED` instead of `WATCH · LOOPS`).

### `v0.3.0` — 2026-11-24
- Rebranded application to **EYEz** with a Batcomputer-inspired matte-black (`#070708` / `#0e0e11`) and tactical-orange (`#ff6a00`) design system and corner targeting reticles.
- Bundled `Iosevka` Latin `.woff2` font weights (`400`, `500`, `600`, `700`) under `static/fonts/` and applied `Iosevka` across the entire UI.
- Redesigned **Grid** view into a multi-column card matrix with prominent channel/camera name plates (`CH-01 // NAME`), hover `[ CLICK TO FOCUS ]` cues, one-click Focus entry on any card, and a `← BACK TO GRID` focus command bar.
- Synced `docs/DOCUMENTATION.html` styling to the EYEz matte-black & orange palette.

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
