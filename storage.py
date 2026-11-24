"""Structured disk storage, metadata indexing, and rolling retention for recordings."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import re
import shutil
import threading
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("surveillance.storage")

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class StorageManager:
    """Manages structured recordings and snapshots under `C:\\SurveillanceData`."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        self.recordings_dir = self.data_dir / "recordings"
        self.snapshots_dir = self.data_dir / "snapshots"
        self._lock = threading.RLock()

        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_stale_parts(self) -> int:
        """Remove unfinished `.part.mp4` files left behind by an unclean shutdown."""
        removed = 0
        with self._lock:
            for part_file in self.recordings_dir.rglob("*.part.mp4"):
                try:
                    part_file.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    logger.warning("Could not remove stale partial file %s", part_file)
            self._prune_empty_dirs_unlocked()
        if removed:
            logger.info("Cleaned up %d stale partial recording file(s)", removed)
        return removed

    def allocate_segment_paths(
        self, camera_id: str, started_at: datetime
    ) -> tuple[Path, Path, Path, Path]:
        """Return `(part_mp4, final_mp4, thumb_jpg, meta_json)` for a new loop."""
        date_str = started_at.strftime("%Y-%m-%d")
        stem = started_at.strftime("%H-%M-%S")
        day_dir = self.recordings_dir / camera_id / date_str
        day_dir.mkdir(parents=True, exist_ok=True)

        part_mp4 = day_dir / f"{stem}.part.mp4"
        final_mp4 = day_dir / f"{stem}.mp4"
        thumb_jpg = day_dir / f"{stem}.jpg"
        meta_json = day_dir / f"{stem}.meta.json"
        return part_mp4, final_mp4, thumb_jpg, meta_json

    def save_snapshot(self, camera_id: str, jpeg_bytes: bytes) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.snapshots_dir / f"{camera_id}_{stamp}.jpg"
        dest.write_bytes(jpeg_bytes)
        return dest

    def _validate_clip_id(self, clip_id: str) -> tuple[str, str, str]:
        parts = clip_id.strip("/").split("/")
        if len(parts) != 3 or not all(_SAFE_SEGMENT_RE.match(p) for p in parts):
            raise ValueError("Invalid recording clip identifier")
        cam_id, date_str, stem = parts
        if stem.endswith(".mp4"):
            stem = stem[:-4]
        return cam_id, date_str, stem

    def resolve_clip_paths(self, clip_id: str) -> tuple[Path, Path, Path]:
        cam_id, date_str, stem = self._validate_clip_id(clip_id)
        base = (self.recordings_dir / cam_id / date_str).resolve()
        if self.recordings_dir not in base.parents:
            raise ValueError("Invalid recording path")
        return (
            base / f"{stem}.mp4",
            base / f"{stem}.jpg",
            base / f"{stem}.meta.json",
        )

    def _read_clip_record(self, mp4_path: Path) -> dict[str, Any] | None:
        if not mp4_path.exists() or mp4_path.name.endswith(".part.mp4"):
            return None
        try:
            rel = mp4_path.relative_to(self.recordings_dir)
        except ValueError:
            return None
        if len(rel.parts) != 3:
            return None

        cam_id, date_str, filename = rel.parts
        stem = mp4_path.stem
        meta_path = mp4_path.with_suffix(".meta.json")
        thumb_path = mp4_path.with_suffix(".jpg")

        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

        stat = mp4_path.stat()
        started_at = meta.get("started_at")
        if not started_at:
            try:
                dt = datetime.strptime(f"{date_str} {stem}", "%Y-%m-%d %H-%M-%S")
                started_at = dt.isoformat(timespec="seconds")
            except ValueError:
                started_at = datetime.fromtimestamp(stat.st_mtime).isoformat(
                    timespec="seconds"
                )

        clip_id = f"{cam_id}/{date_str}/{stem}"
        encoded_id = quote(clip_id, safe="/")
        return {
            "id": clip_id,
            "camera_id": cam_id,
            "camera_name": meta.get("camera_name") or cam_id,
            "date": date_str,
            "filename": filename,
            "started_at": started_at,
            "ended_at": meta.get("ended_at"),
            "duration_seconds": round(float(meta.get("duration_seconds", 0.0)), 1),
            "size_bytes": stat.st_size,
            "width": int(meta.get("width", 0)),
            "height": int(meta.get("height", 0)),
            "locked": bool(meta.get("locked", False)),
            "has_thumbnail": thumb_path.exists(),
            "video_url": f"/api/recordings/media/{encoded_id}",
            "thumbnail_url": (
                f"/api/recordings/thumb/{encoded_id}" if thumb_path.exists() else None
            ),
            "download_url": f"/api/recordings/media/{encoded_id}?download=1",
        }

    def list_recordings(
        self,
        *,
        camera_id: str | None = None,
        date: str | None = None,
        starred_only: bool = False,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self._lock:
            if not self.recordings_dir.exists():
                return records
            for mp4_path in self.recordings_dir.rglob("*.mp4"):
                if mp4_path.name.endswith(".part.mp4"):
                    continue
                rec = self._read_clip_record(mp4_path)
                if rec is None:
                    continue
                if camera_id and rec["camera_id"] != camera_id:
                    continue
                if date and rec["date"] != date:
                    continue
                if starred_only and not rec["locked"]:
                    continue
                records.append(rec)

        records.sort(key=lambda r: (r["started_at"], r["id"]), reverse=True)
        return records

    def list_available_dates(self, camera_id: str | None = None) -> list[str]:
        dates: set[str] = set()
        for rec in self.list_recordings(camera_id=camera_id):
            dates.add(rec["date"])
        return sorted(dates, reverse=True)

    def set_clip_lock(self, clip_id: str, locked: bool) -> dict[str, Any]:
        with self._lock:
            mp4_path, _thumb_path, meta_path = self.resolve_clip_paths(clip_id)
            if not mp4_path.exists():
                raise FileNotFoundError(clip_id)

            meta: dict[str, Any] = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}

            meta["locked"] = bool(locked)
            tmp = meta_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            tmp.replace(meta_path)

            updated = self._read_clip_record(mp4_path)
            if updated is None:
                raise FileNotFoundError(clip_id)
            return updated

    def delete_clip(self, clip_id: str, *, force: bool = False) -> bool:
        with self._lock:
            mp4_path, thumb_path, meta_path = self.resolve_clip_paths(clip_id)
            if not mp4_path.exists():
                return False
            rec = self._read_clip_record(mp4_path)
            if rec and rec["locked"] and not force:
                raise PermissionError(
                    "Clip is starred/locked. Unstar it before deleting."
                )

            for path in (mp4_path, thumb_path, meta_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Failed deleting %s", path)

            self._prune_empty_dirs_unlocked()
            return True

    def _prune_empty_dirs_unlocked(self) -> None:
        if not self.recordings_dir.exists():
            return
        # Walk bottom-up so empty date folders and empty camera folders are cleaned.
        dirs = sorted(
            [p for p in self.recordings_dir.rglob("*") if p.is_dir()],
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for directory in dirs:
            try:
                if not any(directory.iterdir()):
                    directory.rmdir()
            except OSError:
                pass

    def enforce_retention(
        self, *, max_storage_gb: float, max_retention_days: int
    ) -> dict[str, int]:
        """Delete oldest unlocked clips exceeding retention age or storage budget."""
        deleted_count = 0
        reclaimed_bytes = 0

        with self._lock:
            clips = self.list_recordings()
            if not clips:
                return {"deleted_count": 0, "reclaimed_bytes": 0}

            # Process oldest first
            clips_oldest = list(reversed(clips))
            total_bytes = sum(c["size_bytes"] for c in clips_oldest)
            remaining: list[dict[str, Any]] = []

            cutoff: datetime | None = None
            if max_retention_days > 0:
                cutoff = datetime.now() - timedelta(days=max_retention_days)

            # Pass 1: age-based cleanup (unlocked clips only)
            for clip in clips_oldest:
                if cutoff is not None and not clip["locked"]:
                    try:
                        clip_dt = datetime.fromisoformat(clip["started_at"])
                    except ValueError:
                        clip_dt = None
                    if clip_dt is not None and clip_dt < cutoff:
                        if self.delete_clip(clip["id"], force=False):
                            deleted_count += 1
                            reclaimed_bytes += clip["size_bytes"]
                            total_bytes -= clip["size_bytes"]
                            continue
                remaining.append(clip)

            # Pass 2: storage-cap cleanup (unlocked clips only)
            max_bytes = int(max_storage_gb * (1024**3)) if max_storage_gb > 0 else 0
            if max_bytes > 0 and total_bytes > max_bytes:
                for clip in remaining:
                    if total_bytes <= max_bytes:
                        break
                    if clip["locked"]:
                        continue
                    if self.delete_clip(clip["id"], force=False):
                        deleted_count += 1
                        reclaimed_bytes += clip["size_bytes"]
                        total_bytes -= clip["size_bytes"]

            self._prune_empty_dirs_unlocked()

        if deleted_count:
            logger.info(
                "Retention pruned %d clip(s), reclaimed %.1f MB",
                deleted_count,
                reclaimed_bytes / (1024 * 1024),
            )
        return {
            "deleted_count": deleted_count,
            "reclaimed_bytes": reclaimed_bytes,
        }

    def get_storage_stats(
        self, *, max_storage_gb: float, max_retention_days: int
    ) -> dict[str, Any]:
        with self._lock:
            clips = self.list_recordings()
            recordings_bytes = sum(c["size_bytes"] for c in clips)
            locked_count = sum(1 for c in clips if c["locked"])

            try:
                usage = shutil.disk_usage(self.data_dir)
                disk_total = usage.total
                disk_used = usage.used
                disk_free = usage.free
            except OSError:
                disk_total = disk_used = disk_free = 0

            return {
                "data_dir": str(self.data_dir),
                "recordings_dir": str(self.recordings_dir),
                "snapshots_dir": str(self.snapshots_dir),
                "recordings_bytes": recordings_bytes,
                "recordings_count": len(clips),
                "locked_count": locked_count,
                "max_storage_gb": max_storage_gb,
                "max_retention_days": max_retention_days,
                "disk_total_bytes": disk_total,
                "disk_used_bytes": disk_used,
                "disk_free_bytes": disk_free,
            }
