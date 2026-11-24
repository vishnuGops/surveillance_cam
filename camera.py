"""Multi-camera USB webcam manager, capture threads, and recorder wiring."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import logging
import subprocess
import sys
import threading
import time
from typing import Any, Callable

import cv2

from config import AppSettings, CameraConfig, ConfigStore
from recorder import LoopRecorder
from storage import StorageManager

logger = logging.getLogger("surveillance.camera")

FrameHook = Callable[[Any, float], Any]


def _query_windows_camera_names() -> list[str]:
    """Best-effort query of connected camera friendly names on Windows."""
    if sys.platform != "win32":
        return []
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-PnpDevice -Class Camera,Image -Status OK "
                "| Select-Object -ExpandProperty FriendlyName "
                "| ConvertTo-Json -Compress"
            ),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        parsed = json.loads(result.stdout.strip())
        if isinstance(parsed, str):
            return [parsed]
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except Exception:
        logger.debug("Could not query Windows camera friendly names", exc_info=True)
    return []


def _probe_camera_index(index: int) -> bool:
    """Return True if a capture device opens and yields a frame at `index`."""
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    try:
        if not cap.isOpened():
            return False
        ok, frame = cap.read()
        return bool(ok and frame is not None)
    finally:
        cap.release()


class CameraStream:
    """Thread-safe capture stream + continuous loop recorder for one USB webcam."""

    def __init__(
        self,
        cam_config: CameraConfig,
        settings: AppSettings,
        storage: StorageManager,
        on_segment_complete: Callable[[Any], None] | None = None,
    ) -> None:
        self.config = cam_config
        self.settings = settings
        self.storage = storage
        self.frame_hooks: list[FrameHook] = []

        self.recorder = LoopRecorder(
            camera_id=cam_config.id,
            get_camera_name=lambda: self.config.name,
            get_segment_duration=lambda: self.settings.segment_duration_seconds,
            storage=storage,
            on_segment_complete=on_segment_complete,
        )

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cond = threading.Condition()

        self._latest_jpeg: bytes | None = None
        self._frame_id: int = 0
        self._online: bool = False
        self._error: str | None = None
        self._resolution: tuple[int, int] = (0, 0)
        self._fps: float = 0.0
        self._started_at: float = time.monotonic()
        self._active_viewers: int = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = time.monotonic()
        self.recorder.start(enabled=self.config.recording and self.config.enabled)
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"capture-{self.config.id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Started camera stream %s (index=%d, name=%s)",
            self.config.id,
            self.config.index,
            self.config.name,
        )

    def stop(self) -> None:
        self._stop_event.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self.recorder.stop()
        logger.info("Stopped camera stream %s", self.config.id)

    def set_recording(self, enabled: bool) -> None:
        self.config.recording = enabled
        self.recorder.set_enabled(enabled and self.config.enabled)

    def set_enabled(self, enabled: bool) -> None:
        self.config.enabled = enabled
        if enabled:
            self.start()
            self.recorder.set_enabled(self.config.recording)
        else:
            self.recorder.set_enabled(False)
            self.stop()

    def add_viewer(self) -> None:
        with self._cond:
            self._active_viewers += 1

    def remove_viewer(self) -> None:
        with self._cond:
            self._active_viewers = max(0, self._active_viewers - 1)

    def add_frame_hook(self, hook: FrameHook) -> None:
        self.frame_hooks.append(hook)

    def get_latest_jpeg(self) -> bytes | None:
        with self._cond:
            return self._latest_jpeg

    def wait_for_frame(
        self, last_frame_id: int, timeout: float = 2.0
    ) -> tuple[int, bytes | None]:
        with self._cond:
            if not self._stop_event.is_set() and self._frame_id == last_frame_id:
                self._cond.wait(timeout=timeout)
            return self._frame_id, self._latest_jpeg

    def get_status(self) -> dict[str, Any]:
        rec_status = self.recorder.get_status()
        with self._cond:
            return {
                "id": self.config.id,
                "index": self.config.index,
                "name": self.config.name,
                "enabled": self.config.enabled,
                "online": self._online,
                "resolution": {
                    "width": self._resolution[0],
                    "height": self._resolution[1],
                },
                "fps": round(self._fps, 1),
                "target_fps": self.config.fps,
                "show_timestamp": self.config.show_timestamp,
                "active_viewers": self._active_viewers,
                "uptime_seconds": round(time.monotonic() - self._started_at, 1),
                "error": self._error,
                "recording": rec_status,
                "stream_url": f"/api/cameras/{self.config.id}/stream",
                "snapshot_url": f"/api/cameras/{self.config.id}/snapshot",
            }

    def _open_capture(self) -> cv2.VideoCapture | None:
        backends: list[tuple[str, int]] = []
        if sys.platform == "win32":
            backends.append(("CAP_DSHOW", cv2.CAP_DSHOW))
            backends.append(("CAP_MSMF", cv2.CAP_MSMF))
        backends.append(("CAP_ANY", cv2.CAP_ANY))

        mjpg_fourcc = int(cv2.VideoWriter_fourcc(*"MJPG"))
        capture_params = [
            cv2.CAP_PROP_FOURCC,
            mjpg_fourcc,
            cv2.CAP_PROP_FRAME_WIDTH,
            int(self.config.width),
            cv2.CAP_PROP_FRAME_HEIGHT,
            int(self.config.height),
            cv2.CAP_PROP_FPS,
            int(self.config.fps),
        ]

        for name, backend in backends:
            # Passing FOURCC/resolution/FPS via constructor params ensures DirectShow
            # negotiates hardware MJPG (30 FPS) instead of falling back to YUY2 (7.5 FPS).
            cap = cv2.VideoCapture(self.config.index, backend, capture_params)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.config.index, backend)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FOURCC, mjpg_fourcc)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
                    cap.set(cv2.CAP_PROP_FPS, self.config.fps)

            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    raw_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                    fourcc_str = "".join(
                        chr((raw_fourcc >> (8 * i)) & 0xFF) for i in range(4)
                    ).strip("\x00")
                    logger.info(
                        "[%s] Opened index %d via %s (%dx%d, fourcc=%s)",
                        self.config.id,
                        self.config.index,
                        name,
                        actual_w,
                        actual_h,
                        fourcc_str or "unknown",
                    )
                    return cap
                cap.release()
            else:
                cap.release()
        return None

    def _draw_overlay(self, frame: Any) -> None:
        now_text = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        label = f"{self.config.name}  |  {now_text}"

        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.54
        thickness = 1
        (text_w, text_h), baseline = cv2.getTextSize(label, font, scale, thickness)

        frame_h = frame.shape[0]
        pad_x, pad_y = 10, 7
        box_h = text_h + baseline + pad_y * 2
        x1 = 12
        y2 = max(box_h + 4, frame_h - 14)
        y1 = y2 - box_h
        x2 = x1 + text_w + pad_x * 2

        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (8, 11, 17), -1)
        cv2.addWeighted(overlay, 0.62, frame, 0.38, 0, frame)

        text_org = (x1 + pad_x, y1 + pad_y + text_h)
        cv2.putText(
            frame,
            label,
            text_org,
            font,
            scale,
            (242, 246, 252),
            thickness,
            cv2.LINE_AA,
        )

    def _capture_loop(self) -> None:
        encode_params = [
            int(cv2.IMWRITE_JPEG_QUALITY),
            max(10, min(100, self.settings.jpeg_quality)),
        ]
        min_frame_interval = (
            1.0 / self.config.fps if self.config.fps > 0 else 0.0
        )
        frame_times: deque[float] = deque(maxlen=30)

        while not self._stop_event.is_set():
            cap = self._open_capture()
            if cap is None:
                with self._cond:
                    self._online = False
                    self._fps = 0.0
                    self._error = (
                        f"Camera {self.config.index} offline or busy. Reconnecting..."
                    )
                self._stop_event.wait(self.settings.reconnect_delay)
                continue

            consecutive_failures = 0
            frame_times.clear()

            try:
                while not self._stop_event.is_set():
                    loop_start = time.monotonic()
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        consecutive_failures += 1
                        if consecutive_failures >= 15:
                            logger.warning("[%s] Read failed; reconnecting...", self.config.id)
                            with self._cond:
                                self._online = False
                                self._fps = 0.0
                                self._error = "Signal lost; reconnecting..."
                            break
                        time.sleep(0.05)
                        continue

                    consecutive_failures = 0
                    now = time.monotonic()

                    for hook in self.frame_hooks:
                        try:
                            processed = hook(frame, now)
                            if processed is not None:
                                frame = processed
                        except Exception:
                            logger.exception("[%s] Frame hook failed", self.config.id)

                    if self.config.show_timestamp:
                        self._draw_overlay(frame)

                    if self.recorder.enabled:
                        self.recorder.submit_frame(frame, now)

                    encoded_ok, buffer = cv2.imencode(".jpg", frame, encode_params)
                    if not encoded_ok:
                        continue

                    frame_times.append(now)
                    fps = 0.0
                    if len(frame_times) >= 2:
                        span = frame_times[-1] - frame_times[0]
                        if span > 0:
                            fps = (len(frame_times) - 1) / span

                    height, width = frame.shape[:2]
                    jpeg_bytes = buffer.tobytes()

                    with self._cond:
                        self._latest_jpeg = jpeg_bytes
                        self._frame_id += 1
                        self._online = True
                        self._error = None
                        self._resolution = (width, height)
                        self._fps = fps
                        self._cond.notify_all()

                    elapsed = time.monotonic() - loop_start
                    remaining = min_frame_interval - elapsed
                    if remaining > 0.001:
                        self._stop_event.wait(remaining)
            finally:
                cap.release()
                with self._cond:
                    self._online = False
                    self._fps = 0.0


class CameraManager:
    """Auto-discovers, configures, and coordinates multiple USB cameras."""

    def __init__(
        self,
        config_store: ConfigStore,
        storage: StorageManager,
    ) -> None:
        self.config_store = config_store
        self.settings = config_store.settings
        self.storage = storage
        self._lock = threading.RLock()
        self._streams: dict[str, CameraStream] = {}
        self._retention_stop = threading.Event()
        self._retention_thread: threading.Thread | None = None

    def _on_segment_complete(self, _path: Any) -> None:
        try:
            self.storage.enforce_retention(
                max_storage_gb=self.settings.max_storage_gb,
                max_retention_days=self.settings.max_retention_days,
            )
        except Exception:
            logger.exception("Retention check failed after segment completion")

    def start(self) -> None:
        self.storage.cleanup_stale_parts()
        self.storage.enforce_retention(
            max_storage_gb=self.settings.max_storage_gb,
            max_retention_days=self.settings.max_retention_days,
        )

        # Boot previously configured cameras first
        for cam_cfg in self.config_store.list_cameras():
            self._register_stream(cam_cfg)

        # Probe for any newly connected USB webcams
        self.scan_cameras()

        # Background periodic retention sweep (every 10 min)
        self._retention_stop.clear()
        self._retention_thread = threading.Thread(
            target=self._retention_loop,
            name="storage-retention",
            daemon=True,
        )
        self._retention_thread.start()

    def stop(self) -> None:
        self._retention_stop.set()
        if self._retention_thread is not None:
            self._retention_thread.join(timeout=3.0)
            self._retention_thread = None

        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            stream.stop()

    def _retention_loop(self) -> None:
        while not self._retention_stop.wait(600.0):
            self.storage.enforce_retention(
                max_storage_gb=self.settings.max_storage_gb,
                max_retention_days=self.settings.max_retention_days,
            )

    def _register_stream(self, cam_cfg: CameraConfig) -> CameraStream:
        with self._lock:
            existing = self._streams.get(cam_cfg.id)
            if existing is not None:
                return existing
            stream = CameraStream(
                cam_config=cam_cfg,
                settings=self.settings,
                storage=self.storage,
                on_segment_complete=self._on_segment_complete,
            )
            self._streams[cam_cfg.id] = stream
            if cam_cfg.enabled:
                stream.start()
            return stream

    def scan_cameras(self) -> list[dict[str, Any]]:
        """Probe USB webcam indices and register any newly detected cameras."""
        friendly_names = _query_windows_camera_names()
        with self._lock:
            active_indices = {s.config.index for s in self._streams.values()}

        discovered_new: list[str] = []
        consecutive_misses = 0
        max_probe = max(1, self.settings.max_probe_cameras)

        for idx in range(max_probe):
            if idx in active_indices:
                consecutive_misses = 0
                continue
            if _probe_camera_index(idx):
                consecutive_misses = 0
                default_name = (
                    friendly_names[idx]
                    if idx < len(friendly_names)
                    else f"Camera {idx + 1}"
                )
                cam_cfg = self.config_store.ensure_camera(
                    idx, default_name=default_name
                )
                self._register_stream(cam_cfg)
                discovered_new.append(cam_cfg.id)
                logger.info("Discovered new USB camera %s (%s)", cam_cfg.id, cam_cfg.name)
            else:
                consecutive_misses += 1
                # After checking index 0..2 with consecutive misses, stop early.
                if idx >= 2 and consecutive_misses >= 2:
                    break

        if discovered_new:
            logger.info("Camera scan added: %s", ", ".join(discovered_new))
        return self.list_camera_statuses()

    def get_camera(self, cam_id: str) -> CameraStream | None:
        with self._lock:
            return self._streams.get(cam_id)

    def get_first_camera(self) -> CameraStream | None:
        with self._lock:
            if not self._streams:
                return None
            first_id = sorted(self._streams.keys(), key=lambda k: self._streams[k].config.index)[0]
            return self._streams[first_id]

    def list_camera_statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            ordered = sorted(self._streams.values(), key=lambda s: s.config.index)
        return [stream.get_status() for stream in ordered]

    def update_camera(
        self,
        cam_id: str,
        *,
        name: str | None = None,
        recording: bool | None = None,
        show_timestamp: bool | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            stream = self._streams.get(cam_id)
            if stream is None:
                return None
            updated_cfg = self.config_store.update_camera(
                cam_id,
                name=name,
                recording=recording,
                show_timestamp=show_timestamp,
                enabled=enabled,
            )
            if updated_cfg is None:
                return None
            stream.config = updated_cfg
            if enabled is not None:
                stream.set_enabled(enabled)
            elif recording is not None:
                stream.set_recording(recording)
            return stream.get_status()
