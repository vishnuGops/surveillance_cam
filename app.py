"""FastAPI localhost server for multi-camera home surveillance & 5-min loop NVR."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from camera import CameraManager, CameraStream
from config import AppSettings, ConfigStore
from storage import StorageManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("surveillance.app")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class CameraUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    recording: bool | None = None
    night_mode: str | None = Field(default=None, pattern="^(auto|on|off)$")
    enabled: bool | None = None


class LockPayload(BaseModel):
    locked: bool


class StorageSettingsPayload(BaseModel):
    max_storage_gb: float | None = Field(default=None, ge=0.0, le=10000.0)
    max_retention_days: int | None = Field(default=None, ge=0, le=3650)
    segment_duration_seconds: int | None = Field(default=None, ge=10, le=3600)
    auto_record_new_cameras: bool | None = None


def _build_mjpeg_response(
    camera: CameraStream, request: Request
) -> StreamingResponse:
    async def frame_generator() -> AsyncGenerator[bytes, None]:
        camera.add_viewer()
        last_frame_id = -1
        try:
            while True:
                if await request.is_disconnected():
                    break
                frame_id, jpeg = await asyncio.to_thread(
                    camera.wait_for_frame, last_frame_id, 2.0
                )
                if jpeg is None or frame_id == last_frame_id:
                    continue
                last_frame_id = frame_id
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                    + jpeg
                    + b"\r\n"
                )
        except asyncio.CancelledError:
            pass
        finally:
            camera.remove_viewer()

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


def create_app(settings: AppSettings | None = None) -> FastAPI:
    cfg = settings or AppSettings()
    config_store = ConfigStore(cfg)
    storage = StorageManager(cfg.data_dir)
    manager = CameraManager(config_store=config_store, storage=storage)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await asyncio.to_thread(manager.start)
        try:
            yield
        finally:
            await asyncio.to_thread(manager.stop)

    app = FastAPI(
        title="EYEz Surveillance NVR",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.config_store = config_store
    app.state.storage = storage
    app.state.manager = manager

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    # ------------------------------------------------------------------
    # Multi-camera endpoints
    # ------------------------------------------------------------------
    @app.get("/api/cameras")
    async def list_cameras() -> dict:
        cameras = manager.list_camera_statuses()
        stats = storage.get_storage_stats(
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        return {
            "cameras": cameras,
            "storage": stats,
            "settings": config_store.get_storage_settings(),
        }

    @app.post("/api/cameras/scan")
    async def scan_cameras() -> dict:
        cameras = await asyncio.to_thread(manager.scan_cameras)
        return {"cameras": cameras}

    @app.patch("/api/cameras/{cam_id}")
    async def update_camera(cam_id: str, payload: CameraUpdatePayload) -> dict:
        updated = await asyncio.to_thread(
            manager.update_camera,
            cam_id,
            name=payload.name,
            recording=payload.recording,
            night_mode=payload.night_mode,
            enabled=payload.enabled,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Camera '{cam_id}' not found")
        return {"camera": updated}

    @app.get("/api/cameras/{cam_id}/stream")
    async def camera_stream(cam_id: str, request: Request) -> StreamingResponse:
        camera = manager.get_camera(cam_id)
        if camera is None:
            raise HTTPException(status_code=404, detail=f"Camera '{cam_id}' not found")
        return _build_mjpeg_response(camera, request)

    @app.get("/api/cameras/{cam_id}/snapshot")
    async def camera_snapshot(
        cam_id: str, save: bool = Query(default=False)
    ) -> Response:
        camera = manager.get_camera(cam_id)
        if camera is None:
            raise HTTPException(status_code=404, detail=f"Camera '{cam_id}' not found")
        jpeg = camera.get_latest_jpeg()
        if jpeg is None:
            raise HTTPException(status_code=503, detail="Camera frame not ready yet")
        if save:
            await asyncio.to_thread(storage.save_snapshot, cam_id, jpeg)
        filename = f"{cam_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    # ------------------------------------------------------------------
    # Recordings & playback endpoints
    # ------------------------------------------------------------------
    @app.get("/api/recordings")
    async def list_recordings(
        camera_id: str | None = Query(default=None),
        date: str | None = Query(default=None),
        starred_only: bool = Query(default=False),
    ) -> dict:
        recordings = await asyncio.to_thread(
            storage.list_recordings,
            camera_id=camera_id or None,
            date=date or None,
            starred_only=starred_only,
        )
        dates = await asyncio.to_thread(
            storage.list_available_dates, camera_id=camera_id or None
        )
        stats = await asyncio.to_thread(
            storage.get_storage_stats,
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        return {
            "recordings": recordings,
            "dates": dates,
            "storage": stats,
        }

    @app.get("/api/recordings/media/{clip_id:path}")
    async def serve_recording_media(
        clip_id: str, download: bool = Query(default=False)
    ) -> FileResponse:
        try:
            mp4_path, _thumb, _meta = storage.resolve_clip_paths(clip_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not mp4_path.exists():
            raise HTTPException(status_code=404, detail="Recording not found")

        download_name = f"{clip_id.replace('/', '_')}.mp4"
        if download:
            return FileResponse(
                path=mp4_path,
                media_type="video/mp4",
                filename=download_name,
            )
        return FileResponse(
            path=mp4_path,
            media_type="video/mp4",
        )

    @app.get("/api/recordings/thumb/{clip_id:path}")
    async def serve_recording_thumb(clip_id: str) -> FileResponse:
        try:
            _mp4, thumb_path, _meta = storage.resolve_clip_paths(clip_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not thumb_path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return FileResponse(
            path=thumb_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.patch("/api/recordings/lock/{clip_id:path}")
    async def toggle_recording_lock(clip_id: str, payload: LockPayload) -> dict:
        try:
            updated = await asyncio.to_thread(
                storage.set_clip_lock, clip_id, payload.locked
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Recording not found") from exc
        return {"recording": updated}

    @app.delete("/api/recordings/item/{clip_id:path}")
    async def delete_recording(clip_id: str) -> dict:
        try:
            deleted = await asyncio.to_thread(storage.delete_clip, clip_id, force=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Recording not found")
        return {"deleted": True, "id": clip_id}

    # ------------------------------------------------------------------
    # Storage & retention endpoints
    # ------------------------------------------------------------------
    @app.get("/api/storage")
    async def get_storage() -> dict:
        stats = await asyncio.to_thread(
            storage.get_storage_stats,
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        return {
            "storage": stats,
            "settings": config_store.get_storage_settings(),
        }

    @app.patch("/api/storage/settings")
    async def update_storage_settings(payload: StorageSettingsPayload) -> dict:
        updated = config_store.update_retention(
            max_storage_gb=payload.max_storage_gb,
            max_retention_days=payload.max_retention_days,
            segment_duration_seconds=payload.segment_duration_seconds,
            auto_record_new_cameras=payload.auto_record_new_cameras,
        )
        cleanup = await asyncio.to_thread(
            storage.enforce_retention,
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        stats = await asyncio.to_thread(
            storage.get_storage_stats,
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        return {
            "settings": updated,
            "storage": stats,
            "cleanup": cleanup,
        }

    @app.post("/api/storage/cleanup")
    async def run_cleanup() -> dict:
        cleanup = await asyncio.to_thread(
            storage.enforce_retention,
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        stats = await asyncio.to_thread(
            storage.get_storage_stats,
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        return {"cleanup": cleanup, "storage": stats}

    # ------------------------------------------------------------------
    # Legacy v1 convenience aliases (first camera)
    # ------------------------------------------------------------------
    @app.get("/video_feed")
    async def legacy_video_feed(request: Request) -> StreamingResponse:
        camera = manager.get_first_camera()
        if camera is None:
            raise HTTPException(status_code=503, detail="No cameras detected")
        return _build_mjpeg_response(camera, request)

    @app.get("/snapshot")
    async def legacy_snapshot() -> Response:
        camera = manager.get_first_camera()
        if camera is None:
            raise HTTPException(status_code=503, detail="No cameras detected")
        jpeg = camera.get_latest_jpeg()
        if jpeg is None:
            raise HTTPException(status_code=503, detail="Camera frame not ready yet")
        return Response(content=jpeg, media_type="image/jpeg")

    @app.get("/api/status")
    async def legacy_status() -> dict:
        cameras = manager.list_camera_statuses()
        stats = storage.get_storage_stats(
            max_storage_gb=cfg.max_storage_gb,
            max_retention_days=cfg.max_retention_days,
        )
        return {
            "cameras_total": len(cameras),
            "cameras_online": sum(1 for c in cameras if c["online"]),
            "cameras_recording": sum(1 for c in cameras if c["recording"]["active"]),
            "storage": stats,
        }

    return app


def parse_args() -> argparse.Namespace:
    defaults = AppSettings()
    parser = argparse.ArgumentParser(
        description="Lightweight multi-camera localhost home surveillance NVR."
    )
    parser.add_argument("--host", default=defaults.host, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=defaults.port, help="Bind port (default: 8000)")
    parser.add_argument(
        "--data-dir",
        default=str(defaults.data_dir),
        help=r"Storage root directory (default: C:\SurveillanceData)",
    )
    parser.add_argument(
        "--segment-seconds",
        type=int,
        default=defaults.segment_duration_seconds,
        help="Loop recording length in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--max-storage-gb",
        type=float,
        default=defaults.max_storage_gb,
        help="Rolling storage limit in GB (0 disables; default: 50)",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=defaults.max_retention_days,
        help="Rolling retention age in days (0 disables; default: 7)",
    )
    parser.add_argument("--width", type=int, default=defaults.default_width, help="Default capture width")
    parser.add_argument("--height", type=int, default=defaults.default_height, help="Default capture height")
    parser.add_argument("--fps", type=int, default=defaults.default_fps, help="Default target FPS")
    parser.add_argument("--quality", type=int, default=defaults.jpeg_quality, help="MJPEG quality (10-100)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    runtime_settings = AppSettings(
        data_dir=Path(args.data_dir),
        host=args.host,
        port=args.port,
        segment_duration_seconds=args.segment_seconds,
        max_storage_gb=args.max_storage_gb,
        max_retention_days=args.max_days,
        default_width=args.width,
        default_height=args.height,
        default_fps=args.fps,
        jpeg_quality=args.quality,
    )
    runtime_app = create_app(runtime_settings)
    print(
        f"EYEz Surveillance NVR running at http://{runtime_settings.host}:{runtime_settings.port} "
        f"(storage: {runtime_settings.data_dir})"
    )
    uvicorn.run(
        runtime_app,
        host=runtime_settings.host,
        port=runtime_settings.port,
        log_level="info",
    )
