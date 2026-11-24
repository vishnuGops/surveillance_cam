"""FastAPI localhost server for live home surveillance streaming."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from camera import CameraStream
from config import Settings, load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("surveillance.app")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class TimestampToggle(BaseModel):
    enabled: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    camera = CameraStream(cfg)
    active_viewers = 0

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        camera.start()
        try:
            yield
        finally:
            camera.stop()

    app = FastAPI(
        title="Home Surveillance Cam",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.camera = camera

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/video_feed")
    async def video_feed(request: Request) -> StreamingResponse:
        async def frame_generator() -> AsyncGenerator[bytes, None]:
            nonlocal active_viewers
            active_viewers += 1
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
                active_viewers = max(0, active_viewers - 1)

        return StreamingResponse(
            frame_generator(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @app.get("/snapshot")
    async def snapshot() -> Response:
        jpeg = camera.get_latest_jpeg()
        if jpeg is None:
            raise HTTPException(
                status_code=503, detail="Camera frame is not available yet."
            )
        filename = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/status")
    async def status() -> dict:
        data = camera.get_status()
        data["active_viewers"] = active_viewers
        return data

    @app.post("/api/timestamp")
    async def toggle_timestamp(payload: TimestampToggle) -> dict:
        camera.show_timestamp = payload.enabled
        return {"show_timestamp": camera.show_timestamp}

    return app


app = create_app()


def parse_args() -> argparse.Namespace:
    defaults = load_settings()
    parser = argparse.ArgumentParser(
        description="Lightweight localhost USB webcam surveillance server."
    )
    parser.add_argument("--host", default=defaults.host, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=defaults.port, help="Bind port (default: 8000)")
    parser.add_argument("--camera", type=int, default=defaults.camera_index, help="Camera index (default: 0)")
    parser.add_argument("--name", default=defaults.camera_name, help="Display name for the camera")
    parser.add_argument("--width", type=int, default=defaults.frame_width, help="Capture width")
    parser.add_argument("--height", type=int, default=defaults.frame_height, help="Capture height")
    parser.add_argument("--fps", type=int, default=defaults.target_fps, help="Target FPS")
    parser.add_argument("--quality", type=int, default=defaults.jpeg_quality, help="JPEG quality (10-100)")
    parser.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Disable timestamp overlay on the video feed",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    settings = Settings(
        camera_index=args.camera,
        camera_name=args.name,
        frame_width=args.width,
        frame_height=args.height,
        target_fps=args.fps,
        jpeg_quality=args.quality,
        show_timestamp=not args.no_timestamp,
        host=args.host,
        port=args.port,
    )
    runtime_app = create_app(settings)
    print(f"Surveillance feed running at http://{settings.host}:{settings.port}")
    uvicorn.run(runtime_app, host=settings.host, port=settings.port, log_level="info")
