"""Centralized configuration for the home surveillance server."""

from dataclasses import dataclass
import os


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
class Settings:
    camera_index: int = _env_int("SURVEILLANCE_CAMERA_INDEX", 0)
    camera_name: str = os.getenv("SURVEILLANCE_CAMERA_NAME", "Home Cam 1")
    frame_width: int = _env_int("SURVEILLANCE_WIDTH", 1280)
    frame_height: int = _env_int("SURVEILLANCE_HEIGHT", 720)
    target_fps: int = _env_int("SURVEILLANCE_FPS", 30)
    jpeg_quality: int = _env_int("SURVEILLANCE_JPEG_QUALITY", 80)
    show_timestamp: bool = _env_bool("SURVEILLANCE_SHOW_TIMESTAMP", True)
    host: str = os.getenv("SURVEILLANCE_HOST", "127.0.0.1")
    port: int = _env_int("SURVEILLANCE_PORT", 8000)
    reconnect_delay: float = _env_float("SURVEILLANCE_RECONNECT_DELAY", 2.0)


def load_settings() -> Settings:
    return Settings()
