"""Background webcam capture and JPEG encoding manager.

Maintains a single capture thread so multiple browser viewers can watch the
same USB webcam simultaneously without competing for hardware access.
Provides a `frame_hooks` extension point for future features such as motion
detection, object detection, or video recording.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
import logging
import sys
import threading
import time
from typing import Any, Callable

import cv2

from config import Settings

logger = logging.getLogger("surveillance.camera")

FrameHook = Callable[[Any, float], Any]


class CameraStream:
    """Thread-safe USB webcam capture stream with automatic reconnection."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.show_timestamp: bool = settings.show_timestamp
        self.frame_hooks: list[FrameHook] = []

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

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="camera-capture",
            daemon=True,
        )
        self._thread.start()
        logger.info("Camera capture thread started (index=%d)", self.settings.camera_index)

    def stop(self) -> None:
        self._stop_event.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Camera capture thread stopped")

    def add_frame_hook(self, hook: FrameHook) -> None:
        """Register a callback `(frame, timestamp) -> frame | None` for future plugins."""
        self.frame_hooks.append(hook)

    def get_latest_jpeg(self) -> bytes | None:
        with self._cond:
            return self._latest_jpeg

    def wait_for_frame(
        self, last_frame_id: int, timeout: float = 2.0
    ) -> tuple[int, bytes | None]:
        """Block until a frame newer than `last_frame_id` is available or timeout expires."""
        with self._cond:
            if not self._stop_event.is_set() and self._frame_id == last_frame_id:
                self._cond.wait(timeout=timeout)
            return self._frame_id, self._latest_jpeg

    def get_status(self) -> dict[str, Any]:
        with self._cond:
            return {
                "online": self._online,
                "camera_name": self.settings.camera_name,
                "camera_index": self.settings.camera_index,
                "resolution": {
                    "width": self._resolution[0],
                    "height": self._resolution[1],
                },
                "fps": round(self._fps, 1),
                "target_fps": self.settings.target_fps,
                "jpeg_quality": self.settings.jpeg_quality,
                "show_timestamp": self.show_timestamp,
                "uptime_seconds": round(time.monotonic() - self._started_at, 1),
                "error": self._error,
            }

    def _open_capture(self) -> cv2.VideoCapture | None:
        """Open the webcam, preferring DirectShow on Windows for fast startup."""
        backends: list[tuple[str, int]] = []
        if sys.platform == "win32":
            backends.append(("CAP_DSHOW", cv2.CAP_DSHOW))
            backends.append(("CAP_MSMF", cv2.CAP_MSMF))
        backends.append(("CAP_ANY", cv2.CAP_ANY))

        for name, backend in backends:
            cap = cv2.VideoCapture(self.settings.camera_index, backend)
            if cap.isOpened():
                # Request MJPG first so USB 2.0 FHD webcams can sustain 30 FPS.
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.settings.frame_width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.settings.frame_height)
                cap.set(cv2.CAP_PROP_FPS, self.settings.target_fps)

                ok, _ = cap.read()
                if ok:
                    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    logger.info(
                        "Opened camera %d via %s (%dx%d)",
                        self.settings.camera_index,
                        name,
                        actual_w,
                        actual_h,
                    )
                    return cap
                cap.release()
            else:
                cap.release()

        return None

    def _draw_overlay(self, frame: Any) -> None:
        now_text = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        label = f"{self.settings.camera_name}  |  {now_text}"

        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.55
        thickness = 1
        (text_w, text_h), baseline = cv2.getTextSize(label, font, scale, thickness)

        pad_x, pad_y = 10, 8
        x1, y1 = 12, 12
        x2, y2 = x1 + text_w + pad_x * 2, y1 + text_h + baseline + pad_y * 2

        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (10, 12, 16), -1)
        cv2.addWeighted(overlay, 0.58, frame, 0.42, 0, frame)

        text_org = (x1 + pad_x, y1 + pad_y + text_h)
        cv2.putText(
            frame,
            label,
            text_org,
            font,
            scale,
            (240, 244, 248),
            thickness,
            cv2.LINE_AA,
        )

    def _capture_loop(self) -> None:
        encode_params = [
            int(cv2.IMWRITE_JPEG_QUALITY),
            max(10, min(100, self.settings.jpeg_quality)),
        ]
        min_frame_interval = (
            1.0 / self.settings.target_fps if self.settings.target_fps > 0 else 0.0
        )
        frame_times: deque[float] = deque(maxlen=30)

        while not self._stop_event.is_set():
            cap = self._open_capture()
            if cap is None:
                with self._cond:
                    self._online = False
                    self._fps = 0.0
                    self._error = (
                        f"Unable to open camera index {self.settings.camera_index}. "
                        "Make sure it is connected and not used exclusively by another app."
                    )
                logger.warning(self._error)
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
                            logger.warning("Camera read failed repeatedly; reconnecting...")
                            with self._cond:
                                self._online = False
                                self._fps = 0.0
                                self._error = "Lost connection to webcam; reconnecting..."
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
                            logger.exception("Frame hook failed")

                    if self.show_timestamp:
                        self._draw_overlay(frame)

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
