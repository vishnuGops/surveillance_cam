"""EYEz 24/7 Windows Watchdog & System Tray Launcher.

Runs the FastAPI/OpenCV/PyAV surveillance server silently in the background
inside the interactive user session (avoiding Windows Session 0 USB webcam
blocks) with:
- Single-instance Windows Named Mutex protection
- Automatic crash & hang recovery with progressive backoff
- Windows sleep prevention while keeping monitor power-saving intact
- Rotating file logging under C:\\SurveillanceData\\logs\\eyez.log
- Matte-black & orange EYEz System Tray icon with quick actions
"""

from __future__ import annotations

import argparse
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from PIL import Image, ImageDraw
import pystray

from config import DEFAULT_DATA_DIR

APP_DIR = Path(__file__).resolve().parent
MUTEX_NAME = "Local\\EYEzSurveillanceServiceMutex"

# Windows SetThreadExecutionState flags
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class SingleInstanceLock:
    """OS-backed single-instance lock using a Windows Named Mutex."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            return True
        # ERROR_ALREADY_EXISTS == 183
        if kernel32.GetLastError() == 183:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if sys.platform == "win32" and self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


def set_prevent_sleep(enabled: bool) -> None:
    """Keep Windows awake for 24/7 recording while still allowing monitor sleep."""
    if sys.platform != "win32":
        return
    try:
        flags = (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) if enabled else ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def setup_logging(data_dir: Path) -> tuple[logging.Logger, Path]:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "eyez.log"

    logger = logging.getLogger("eyez.watchdog")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)

    return logger, log_file


def build_tray_icon_image(online: bool = True) -> Image.Image:
    """Render a crisp 64x64 matte-black & tactical-orange EYEz icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Matte black base square with crisp orange top border
    draw.rounded_rectangle([2, 2, 61, 61], radius=10, fill=(10, 10, 13, 255), outline=(42, 42, 52, 255), width=2)
    accent = (255, 106, 0, 255) if online else (239, 68, 68, 255)

    # Outer tactical hexagonal eye aperture
    eye_poly = [(9, 32), (20, 18), (44, 18), (55, 32), (44, 46), (20, 46)]
    draw.polygon(eye_poly, outline=(235, 235, 240, 255), fill=(5, 5, 6, 255))
    draw.line(eye_poly + [eye_poly[0]], fill=(235, 235, 240, 255), width=3)

    # Inner diamond iris & glowing pupil
    diamond = [(32, 21), (42, 32), (32, 43), (22, 32)]
    draw.line(diamond + [diamond[0]], fill=accent, width=3)
    draw.ellipse([27, 27, 37, 37], fill=accent)

    # Corner targeting ticks
    draw.line([(32, 6), (32, 13)], fill=accent, width=2)
    draw.line([(32, 51), (32, 58)], fill=accent, width=2)
    return img


def ensure_ico_asset() -> Path | None:
    """Export assets/eyez.ico for Windows shortcuts and future installer packaging."""
    try:
        assets_dir = APP_DIR / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        ico_path = assets_dir / "eyez.ico"
        if not ico_path.exists():
            img = build_tray_icon_image(online=True)
            img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        return ico_path
    except Exception:
        return None


def resolve_python_executable() -> str:
    """Prefer the venv python.exe for spawning app.py (clean stdout/stderr piping)."""
    venv_python = APP_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        sibling = exe.with_name("python.exe")
        if sibling.exists():
            return str(sibling)
    return str(exe)


class EYEzSupervisor:
    """Supervises app.py 24/7 with auto-restart, health checks, and System Tray UI."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        data_dir: Path,
        logger: logging.Logger,
    ) -> None:
        self.host = host
        self.port = port
        self.data_dir = data_dir
        self.logger = logger
        self.url = f"http://{host}:{port}"

        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._proc_lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._tray: pystray.Icon | None = None
        self._watchdog_thread: threading.Thread | None = None

    def _spawn_server(self) -> subprocess.Popen[str]:
        python_exe = resolve_python_executable()
        cmd = [
            python_exe,
            str(APP_DIR / "app.py"),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--data-dir",
            str(self.data_dir),
        ]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )

        self.logger.info("Starting EYEz server: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            cwd=str(APP_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        threading.Thread(
            target=self._pump_output,
            args=(proc,),
            name="eyez-log-pump",
            daemon=True,
        ).start()
        return proc

    def _pump_output(self, proc: subprocess.Popen[str]) -> None:
        if proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                text = line.rstrip()
                if text:
                    self.logger.info("[server] %s", text)
        except Exception:
            pass

    def _terminate_server(self) -> None:
        with self._proc_lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self.logger.info("Stopping EYEz server (pid=%s)...", proc.pid)
        try:
            if sys.platform == "win32":
                # CTRL_BREAK_EVENT triggers Uvicorn's graceful shutdown so active MP4 loops flush cleanly.
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=8.0)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=4.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=3.0)
                except Exception:
                    pass
        self.logger.info("EYEz server stopped (exit=%s)", proc.poll())

    def _check_health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/status", timeout=4) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _update_tray_state(self, online: bool, note: str) -> None:
        tray = self._tray
        if tray is None:
            return
        try:
            tray.title = f"EYEz — {note}"
            tray.icon = build_tray_icon_image(online=online)
        except Exception:
            pass

    def _watchdog_loop(self) -> None:
        backoff = 3.0
        while not self._stop_event.is_set():
            self._restart_event.clear()
            started_at = time.monotonic()
            proc = self._spawn_server()
            with self._proc_lock:
                self._proc = proc

            self._update_tray_state(True, f"Running ({self.url})")
            failed_health = 0
            last_health_check = started_at

            while not self._stop_event.is_set() and not self._restart_event.is_set():
                code = proc.poll()
                if code is not None:
                    self.logger.warning("EYEz server exited unexpectedly (code=%s)", code)
                    break

                now = time.monotonic()
                if now - started_at > 60.0:
                    backoff = 3.0

                # Health check every 30s after 20s startup grace window
                if (now - started_at) >= 20.0 and (now - last_health_check) >= 30.0:
                    last_health_check = now
                    if self._check_health():
                        failed_health = 0
                    else:
                        failed_health += 1
                        self.logger.warning(
                            "EYEz health check failed (%d/3)", failed_health
                        )
                        if failed_health >= 3:
                            self.logger.error(
                                "EYEz server unresponsive for 3 checks; restarting..."
                            )
                            break

                self._stop_event.wait(0.5)

            self._terminate_server()
            with self._proc_lock:
                self._proc = None

            if self._stop_event.is_set():
                break

            if self._restart_event.is_set():
                self.logger.info("Manual server restart requested")
                self._update_tray_state(False, "Restarting...")
                self._stop_event.wait(1.0)
                continue

            self._update_tray_state(False, f"Reconnecting in {int(backoff)}s...")
            self.logger.info("Restarting EYEz server in %.1fs...", backoff)
            self._stop_event.wait(backoff)
            backoff = min(15.0, backoff * 1.6)

    # ---------------- TRAY ACTIONS ----------------
    def open_dashboard(self, _icon=None, _item=None) -> None:
        webbrowser.open(self.url)

    def open_recordings(self, _icon=None, _item=None) -> None:
        rec_dir = self.data_dir / "recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(rec_dir))

    def open_logs(self, _icon=None, _item=None) -> None:
        log_dir = self.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(log_dir))

    def request_restart(self, _icon=None, _item=None) -> None:
        self._restart_event.set()

    def request_quit(self, _icon=None, _item=None) -> None:
        self.logger.info("Quit requested from System Tray")
        self._stop_event.set()
        if self._tray is not None:
            self._tray.stop()

    def run(self, *, headless: bool = False) -> None:
        set_prevent_sleep(True)
        ensure_ico_asset()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="eyez-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

        try:
            if headless:
                while not self._stop_event.is_set():
                    self._stop_event.wait(1.0)
            else:
                menu = pystray.Menu(
                    pystray.MenuItem("Open EYEz Dashboard", self.open_dashboard, default=True),
                    pystray.MenuItem("Open Recordings Folder", self.open_recordings),
                    pystray.MenuItem("Open Logs Folder", self.open_logs),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Restart Server", self.request_restart),
                    pystray.MenuItem("Quit EYEz", self.request_quit),
                )
                self._tray = pystray.Icon(
                    "EYEz",
                    build_tray_icon_image(online=True),
                    f"EYEz — Starting ({self.url})",
                    menu,
                )
                self._tray.run()
        finally:
            self._stop_event.set()
            if self._watchdog_thread is not None:
                self._watchdog_thread.join(timeout=12.0)
            set_prevent_sleep(False)
            self.logger.info("EYEz supervisor exited cleanly")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EYEz 24/7 Watchdog & Windows System Tray Launcher."
    )
    parser.add_argument("--host", default=os.getenv("SURVEILLANCE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SURVEILLANCE_PORT", "8000")))
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run watchdog without System Tray icon (useful for testing).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    logger, _log_file = setup_logging(data_dir)

    lock = SingleInstanceLock(MUTEX_NAME)
    if not lock.acquire():
        # Another EYEz instance is already running — exit silently (normal for 1-min watchdog ping).
        return 0

    supervisor = EYEzSupervisor(
        host=args.host,
        port=args.port,
        data_dir=data_dir,
        logger=logger,
    )

    def _handle_signal(_signum, _frame):
        supervisor.request_quit()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            pass

    try:
        logger.info("EYEz 24/7 supervisor starting (url=http://%s:%d, data=%s)", args.host, args.port, data_dir)
        supervisor.run(headless=args.headless)
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
