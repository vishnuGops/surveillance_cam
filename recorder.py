"""Continuous H.264 5-minute loop recorder using PyAV.

Runs an isolated encoder thread per camera so disk I/O and video compression
never stall the live MJPEG feed. Uses millisecond wall-clock PTS timestamps so
variable USB webcam framerates always play back at real-time speed in browsers.
"""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction
import json
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable

import av
import cv2
import numpy as np

from storage import StorageManager

logger = logging.getLogger("surveillance.recorder")


class LoopRecorder:
    """Continuously encodes incoming BGR frames into rotating H.264 MP4 segments."""

    def __init__(
        self,
        camera_id: str,
        get_camera_name: Callable[[], str],
        get_segment_duration: Callable[[], int],
        storage: StorageManager,
        on_segment_complete: Callable[[Path], None] | None = None,
    ) -> None:
        self.camera_id = camera_id
        self._get_camera_name = get_camera_name
        self._get_segment_duration = get_segment_duration
        self.storage = storage
        self._on_segment_complete = on_segment_complete

        self._queue: queue.Queue[tuple[np.ndarray, float] | None] = queue.Queue(
            maxsize=60
        )
        self._lock = threading.Lock()
        self._enabled = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Active segment state
        self._container: av.container.OutputContainer | None = None
        self._stream: Any = None
        self._seg_paths: tuple[Path, Path, Path, Path] | None = None
        self._seg_started_dt: datetime | None = None
        self._seg_started_mono: float = 0.0
        self._seg_width: int = 0
        self._seg_height: int = 0
        self._seg_frames: int = 0
        self._last_pts: int = -1
        self._thumb_saved: bool = False

        # Telemetry
        self._segments_completed: int = 0
        self._last_error: str | None = None

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def start(self, enabled: bool = True) -> None:
        with self._lock:
            self._enabled = enabled
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"recorder-{self.camera_id}",
                daemon=True,
            )
            self._thread.start()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled
        if not enabled:
            # Wake encoder thread so it immediately finalizes any active segment.
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=8.0)
            self._thread = None

    def submit_frame(self, frame: np.ndarray, timestamp: float) -> None:
        """Non-blocking frame submission called from the camera capture thread."""
        if not self.enabled or self._stop_event.is_set():
            return
        try:
            self._queue.put_nowait((frame.copy(), timestamp))
        except queue.Full:
            # Drop frame rather than blocking live camera feed.
            pass

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            active = self._container is not None and self._enabled
            elapsed = (
                max(0.0, time.monotonic() - self._seg_started_mono)
                if active
                else 0.0
            )
            return {
                "enabled": self._enabled,
                "active": active,
                "segment_duration_seconds": self._get_segment_duration(),
                "segment_elapsed_seconds": round(elapsed, 1),
                "segment_started_at": (
                    self._seg_started_dt.isoformat(timespec="seconds")
                    if active and self._seg_started_dt
                    else None
                ),
                "segments_completed": self._segments_completed,
                "error": self._last_error,
            }

    def _open_segment(self, width: int, height: int, now_mono: float) -> None:
        even_w = width & ~1
        even_h = height & ~1
        started_dt = datetime.now()
        paths = self.storage.allocate_segment_paths(self.camera_id, started_dt)
        part_mp4 = paths[0]

        container = av.open(
            str(part_mp4),
            mode="w",
            format="mp4",
            options={"movflags": "faststart"},
        )
        stream = container.add_stream("libx264", rate=30)
        stream.width = even_w
        stream.height = even_h
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        stream.options = {
            "preset": "ultrafast",
            "tune": "zerolatency",
            "crf": "26",
            "g": "60",
        }

        with self._lock:
            self._container = container
            self._stream = stream
            self._seg_paths = paths
            self._seg_started_dt = started_dt
            self._seg_started_mono = now_mono
            self._seg_width = even_w
            self._seg_height = even_h
            self._seg_frames = 0
            self._last_pts = -1
            self._thumb_saved = False
            self._last_error = None

        logger.info(
            "[%s] Started recording segment %s (%dx%d)",
            self.camera_id,
            paths[1].name,
            even_w,
            even_h,
        )

    def _write_thumbnail(self, frame: np.ndarray, thumb_path: Path) -> None:
        try:
            h, w = frame.shape[:2]
            target_w = 480
            if w > target_w:
                scale = target_w / float(w)
                thumb = cv2.resize(
                    frame,
                    (target_w, max(2, int(h * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                thumb = frame
            ok, buf = cv2.imencode(
                ".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 78]
            )
            if ok:
                thumb_path.write_bytes(buf.tobytes())
        except Exception:
            logger.exception("[%s] Failed writing thumbnail", self.camera_id)

    def _close_segment(self, *, discard: bool = False) -> None:
        if self._container is None or self._seg_paths is None:
            return

        part_mp4, final_mp4, thumb_jpg, meta_json = self._seg_paths
        started_dt = self._seg_started_dt or datetime.now()
        ended_dt = datetime.now()
        duration = max(0.0, time.monotonic() - self._seg_started_mono)
        frames_written = self._seg_frames
        width = self._seg_width
        height = self._seg_height

        container = self._container
        stream = self._stream

        with self._lock:
            self._container = None
            self._stream = None
            self._seg_paths = None
            self._seg_started_dt = None
            self._seg_started_mono = 0.0
            self._seg_frames = 0
            self._last_pts = -1
            self._thumb_saved = False

        try:
            if not discard and stream is not None and frames_written > 0:
                for packet in stream.encode():
                    container.mux(packet)
            container.close()
        except Exception:
            logger.exception("[%s] Error finalizing segment", self.camera_id)
            try:
                container.close()
            except Exception:
                pass
            part_mp4.unlink(missing_ok=True)
            thumb_jpg.unlink(missing_ok=True)
            return

        if discard or frames_written < 2 or not part_mp4.exists() or part_mp4.stat().st_size < 1024:
            part_mp4.unlink(missing_ok=True)
            thumb_jpg.unlink(missing_ok=True)
            return

        try:
            part_mp4.replace(final_mp4)
            meta = {
                "camera_id": self.camera_id,
                "camera_name": self._get_camera_name(),
                "started_at": started_dt.isoformat(timespec="seconds"),
                "ended_at": ended_dt.isoformat(timespec="seconds"),
                "duration_seconds": round(duration, 1),
                "width": width,
                "height": height,
                "frames": frames_written,
                "locked": False,
            }
            meta_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            with self._lock:
                self._segments_completed += 1
            logger.info(
                "[%s] Saved loop %s (%.1fs, %.2f MB)",
                self.camera_id,
                final_mp4.name,
                duration,
                final_mp4.stat().st_size / (1024 * 1024),
            )
            if self._on_segment_complete is not None:
                self._on_segment_complete(final_mp4)
        except Exception:
            logger.exception("[%s] Failed finalizing metadata", self.camera_id)

    def _encode_frame(self, frame: np.ndarray, now_mono: float) -> None:
        h, w = frame.shape[:2]
        even_w, even_h = w & ~1, h & ~1
        if even_w < 2 or even_h < 2:
            return
        if even_w != w or even_h != h:
            frame = frame[:even_h, :even_w]

        seg_limit = max(10, self._get_segment_duration())
        need_rotate = (
            self._container is not None
            and (
                (now_mono - self._seg_started_mono) >= seg_limit
                or even_w != self._seg_width
                or even_h != self._seg_height
            )
        )
        if need_rotate:
            self._close_segment()

        if self._container is None:
            try:
                self._open_segment(even_w, even_h, now_mono)
            except Exception as exc:
                with self._lock:
                    self._last_error = f"Recorder open failed: {exc}"
                logger.exception("[%s] Failed to open new segment", self.camera_id)
                return

        if self._seg_paths is not None and (
            not self._thumb_saved
            and (self._seg_frames == 0 or (now_mono - self._seg_started_mono) >= 1.0)
        ):
            # Capture a clean thumbnail on first frame, then refresh once after 1s
            # once webcam auto-exposure has settled.
            self._write_thumbnail(frame, self._seg_paths[2])
            if (now_mono - self._seg_started_mono) >= 1.0:
                self._thumb_saved = True

        pts = int((now_mono - self._seg_started_mono) * 1000.0)
        if pts <= self._last_pts:
            pts = self._last_pts + 1
        self._last_pts = pts

        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = Fraction(1, 1000)

        for packet in self._stream.encode(video_frame):
            self._container.mux(packet)
        self._seg_frames += 1

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    if not self.enabled and self._container is not None:
                        self._close_segment()
                    elif (
                        self._container is not None
                        and (time.monotonic() - self._seg_started_mono)
                        >= max(10, self._get_segment_duration())
                    ):
                        self._close_segment()
                    continue

                if item is None:
                    if not self.enabled and self._container is not None:
                        self._close_segment()
                    continue

                if not self.enabled:
                    if self._container is not None:
                        self._close_segment()
                    continue

                frame, ts = item
                try:
                    self._encode_frame(frame, ts)
                except Exception as exc:
                    with self._lock:
                        self._last_error = f"Encode error: {exc}"
                    logger.exception("[%s] Encode error", self.camera_id)
                    self._close_segment(discard=True)
                    self._stop_event.wait(0.5)
        finally:
            self._close_segment()
