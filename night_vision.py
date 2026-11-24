"""Real-time low-light software night vision pipeline for USB webcams.

Designed to stay fast (~5-7ms per 720p frame) so 30 FPS capture and H.264
recording remain smooth while substantially improving dim-room visibility:
- Auto mode measures raw frame luminance with hysteresis + hold duration so
  brief light flashes never cause rapid mode flickering.
- Enhancement combines a precomputed shadow-lift gamma LUT, luminance-only
  CLAHE local contrast (YCrCb), and motion-aware temporal denoising that
  smooths static grain while keeping moving subjects sharp.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import cv2
import numpy as np

VALID_NIGHT_MODES = {"auto", "on", "off"}


class NightVisionProcessor:
    """Per-camera software night vision processor with auto low-light hysteresis."""

    def __init__(
        self,
        mode: str = "auto",
        *,
        enter_luma: float = 68.0,
        exit_luma: float = 88.0,
        hold_seconds: float = 1.5,
        gamma: float = 0.56,
    ) -> None:
        self._lock = threading.Lock()
        self._mode = mode if mode in VALID_NIGHT_MODES else "auto"
        self._enter_luma = enter_luma
        self._exit_luma = exit_luma
        self._hold_seconds = hold_seconds

        self._active = self._mode == "on"
        self._last_luma: float = 128.0
        self._pending_state: bool | None = None
        self._pending_since: float = 0.0

        # Precompute shadow-lift gamma LUT (fast O(1) lookup via cv2.LUT)
        inv_gamma = float(gamma)
        lut = np.array(
            [min(255, int(((i / 255.0) ** inv_gamma) * 255.0 + 0.5)) for i in range(256)],
            dtype=np.uint8,
        )
        self._gamma_lut = lut
        self._clahe = cv2.createCLAHE(clipLimit=2.6, tileGridSize=(8, 8))

        # Temporal denoising state (single-channel Y luminance buffer for SIMD speed)
        self._prev_y: np.ndarray | None = None

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def set_mode(self, mode: str) -> str:
        cleaned = mode.strip().lower()
        if cleaned not in VALID_NIGHT_MODES:
            raise ValueError(f"Invalid night_mode '{mode}' (expected auto, on, or off)")
        with self._lock:
            self._mode = cleaned
            self._pending_state = None
            if cleaned == "on":
                self._active = True
            elif cleaned == "off":
                self._active = False
                self._prev_y = None
            # In "auto", keep current active state until next frame evaluation.
            return self._mode

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": self._mode,
                "active": self._active,
                "luma": round(self._last_luma, 1),
                "enter_luma": self._enter_luma,
                "exit_luma": self._exit_luma,
            }

    def _measure_luma(self, frame: np.ndarray) -> float:
        # Subsample aggressively for <0.1ms luma computation
        small = cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA)
        # Fast BT.601 luma approximation from BGR
        b = small[:, :, 0].astype(np.float32)
        g = small[:, :, 1].astype(np.float32)
        r = small[:, :, 2].astype(np.float32)
        return float(np.mean(0.114 * b + 0.587 * g + 0.299 * r))

    def _update_auto_state(self, luma: float, now: float) -> bool:
        with self._lock:
            self._last_luma = luma
            if self._mode == "on":
                self._active = True
                return True
            if self._mode == "off":
                self._active = False
                return False

            # Auto mode with hysteresis + hold time
            desired = self._active
            if not self._active and luma < self._enter_luma:
                desired = True
            elif self._active and luma > self._exit_luma:
                desired = False

            if desired == self._active:
                self._pending_state = None
            else:
                if self._pending_state != desired:
                    self._pending_state = desired
                    self._pending_since = now
                elif (now - self._pending_since) >= self._hold_seconds:
                    self._active = desired
                    self._pending_state = None
                    if not self._active:
                        self._prev_y = None

            return self._active

    def process(self, frame: np.ndarray, now: float | None = None) -> tuple[np.ndarray, bool]:
        """Evaluate low-light state and enhance `frame` when night mode is active."""
        ts = now if now is not None else time.monotonic()
        luma = self._measure_luma(frame)
        is_active = self._update_auto_state(luma, ts)

        if not is_active:
            return frame, False

        # Single-pass YCrCb enhancement: fast OpenCV SIMD temporal denoise + LUT + CLAHE
        ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        y_chan = ycrcb[:, :, 0]
        y_clean = self._temporal_denoise_y(y_chan)
        y_lifted = cv2.LUT(y_clean, self._gamma_lut)
        ycrcb[:, :, 0] = self._clahe.apply(y_lifted)
        enhanced = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
        return enhanced, True

    def _temporal_denoise_y(self, y_chan: np.ndarray) -> np.ndarray:
        prev = self._prev_y
        if prev is None or prev.shape != y_chan.shape:
            self._prev_y = y_chan.copy()
            return y_chan

        # Pure OpenCV SIMD ops on 1-channel luma: blend static noise, keep motion sharp
        diff = cv2.absdiff(y_chan, prev)
        _, motion_mask = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)
        blended = cv2.addWeighted(y_chan, 0.42, prev, 0.58, 0)
        cv2.copyTo(y_chan, motion_mask, blended)
        self._prev_y = blended.copy()
        return blended
