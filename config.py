"""Centralized, persistent configuration for the multi-camera home NVR."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any

logger = logging.getLogger("surveillance.config")

DEFAULT_DATA_DIR = Path(os.getenv("SURVEILLANCE_DATA_DIR", r"C:\SurveillanceData"))


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class CameraConfig:
    id: str
    index: int
    name: str
    enabled: bool = True
    recording: bool = True
    show_timestamp: bool = True
    width: int = 1280
    height: int = 720
    fps: int = 30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CameraConfig":
        return cls(
            id=str(data["id"]),
            index=int(data["index"]),
            name=str(data.get("name") or f"Camera {data['index']}"),
            enabled=bool(data.get("enabled", True)),
            recording=bool(data.get("recording", True)),
            show_timestamp=bool(data.get("show_timestamp", True)),
            width=int(data.get("width", 1280)),
            height=int(data.get("height", 720)),
            fps=int(data.get("fps", 30)),
        )


@dataclass
class AppSettings:
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    host: str = field(default_factory=lambda: os.getenv("SURVEILLANCE_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("SURVEILLANCE_PORT", 8000))
    segment_duration_seconds: int = field(
        default_factory=lambda: _env_int("SURVEILLANCE_SEGMENT_SECONDS", 300)
    )
    max_storage_gb: float = field(
        default_factory=lambda: _env_float("SURVEILLANCE_MAX_STORAGE_GB", 50.0)
    )
    max_retention_days: int = field(
        default_factory=lambda: _env_int("SURVEILLANCE_MAX_RETENTION_DAYS", 7)
    )
    auto_record_new_cameras: bool = field(
        default_factory=lambda: _env_bool("SURVEILLANCE_AUTO_RECORD", True)
    )
    default_width: int = field(
        default_factory=lambda: _env_int("SURVEILLANCE_WIDTH", 1280)
    )
    default_height: int = field(
        default_factory=lambda: _env_int("SURVEILLANCE_HEIGHT", 720)
    )
    default_fps: int = field(default_factory=lambda: _env_int("SURVEILLANCE_FPS", 30))
    jpeg_quality: int = field(
        default_factory=lambda: _env_int("SURVEILLANCE_JPEG_QUALITY", 80)
    )
    max_probe_cameras: int = field(
        default_factory=lambda: _env_int("SURVEILLANCE_MAX_CAMERAS", 8)
    )
    reconnect_delay: float = field(
        default_factory=lambda: _env_float("SURVEILLANCE_RECONNECT_DELAY", 2.0)
    )


class ConfigStore:
    """Thread-safe persistent JSON store under `<data_dir>/config.json`."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self.config_path = self.settings.data_dir / "config.json"
        self.cameras: dict[str, CameraConfig] = {}

        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            self._save_unlocked()
            return
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read %s; using defaults", self.config_path)
            return

        if "segment_duration_seconds" in raw:
            self.settings.segment_duration_seconds = max(
                10, int(raw["segment_duration_seconds"])
            )
        if "max_storage_gb" in raw:
            self.settings.max_storage_gb = max(0.0, float(raw["max_storage_gb"]))
        if "max_retention_days" in raw:
            self.settings.max_retention_days = max(0, int(raw["max_retention_days"]))
        if "auto_record_new_cameras" in raw:
            self.settings.auto_record_new_cameras = bool(raw["auto_record_new_cameras"])

        for cam_id, cam_data in raw.get("cameras", {}).items():
            try:
                cam_data = dict(cam_data)
                cam_data.setdefault("id", cam_id)
                self.cameras[cam_id] = CameraConfig.from_dict(cam_data)
            except Exception:
                logger.warning("Skipping invalid camera config for %s", cam_id)

    def _save_unlocked(self) -> None:
        payload = {
            "segment_duration_seconds": self.settings.segment_duration_seconds,
            "max_storage_gb": self.settings.max_storage_gb,
            "max_retention_days": self.settings.max_retention_days,
            "auto_record_new_cameras": self.settings.auto_record_new_cameras,
            "cameras": {
                cam_id: cam.to_dict() for cam_id, cam in sorted(self.cameras.items())
            },
        }
        tmp_path = self.config_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(self.config_path)

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def ensure_camera(
        self, index: int, default_name: str | None = None
    ) -> CameraConfig:
        cam_id = f"cam-{index}"
        with self._lock:
            existing = self.cameras.get(cam_id)
            if existing is not None:
                return existing
            cam = CameraConfig(
                id=cam_id,
                index=index,
                name=default_name or f"Camera {index + 1}",
                enabled=True,
                recording=self.settings.auto_record_new_cameras,
                show_timestamp=True,
                width=self.settings.default_width,
                height=self.settings.default_height,
                fps=self.settings.default_fps,
            )
            self.cameras[cam_id] = cam
            self._save_unlocked()
            return cam

    def get_camera(self, cam_id: str) -> CameraConfig | None:
        with self._lock:
            return self.cameras.get(cam_id)

    def list_cameras(self) -> list[CameraConfig]:
        with self._lock:
            return sorted(self.cameras.values(), key=lambda c: c.index)

    def update_camera(
        self,
        cam_id: str,
        *,
        name: str | None = None,
        recording: bool | None = None,
        show_timestamp: bool | None = None,
        enabled: bool | None = None,
    ) -> CameraConfig | None:
        with self._lock:
            cam = self.cameras.get(cam_id)
            if cam is None:
                return None
            if name is not None:
                cleaned = name.strip()
                if cleaned:
                    cam.name = cleaned[:60]
            if recording is not None:
                cam.recording = recording
            if show_timestamp is not None:
                cam.show_timestamp = show_timestamp
            if enabled is not None:
                cam.enabled = enabled
            self._save_unlocked()
            return cam

    def update_retention(
        self,
        *,
        max_storage_gb: float | None = None,
        max_retention_days: int | None = None,
        segment_duration_seconds: int | None = None,
        auto_record_new_cameras: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if max_storage_gb is not None:
                self.settings.max_storage_gb = max(0.0, round(float(max_storage_gb), 2))
            if max_retention_days is not None:
                self.settings.max_retention_days = max(0, int(max_retention_days))
            if segment_duration_seconds is not None:
                self.settings.segment_duration_seconds = max(
                    10, min(3600, int(segment_duration_seconds))
                )
            if auto_record_new_cameras is not None:
                self.settings.auto_record_new_cameras = bool(auto_record_new_cameras)
            self._save_unlocked()
            return self.get_storage_settings()

    def get_storage_settings(self) -> dict[str, Any]:
        with self._lock:
            return {
                "data_dir": str(self.settings.data_dir),
                "max_storage_gb": self.settings.max_storage_gb,
                "max_retention_days": self.settings.max_retention_days,
                "segment_duration_seconds": self.settings.segment_duration_seconds,
                "auto_record_new_cameras": self.settings.auto_record_new_cameras,
            }
