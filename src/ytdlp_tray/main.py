"""
ytdlp_tray/main.py
──────────────────
System-tray application that:
  • Shows a tray icon with a "Quit" menu option
  • Runs a Flask API on localhost:9876
  • Accepts POST /download {"url": "..."}
  • Spawns yt-dlp in a background thread
  • Logs everything with timestamps to ytdlp-tray.log (next to the .exe)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from threading import Event
import time
from pathlib import Path
from typing import Any

import yaml

from flask import Flask, jsonify, request
from flask_cors import CORS
import pystray
from PIL import Image


# ── Paths ────────────────────────────────────────────────────────────────────


def _base_dir() -> Path:
    """Return the directory that contains the running executable (or script)."""
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent  # repo root when running with uv


BASE_DIR = _base_dir()
LOG_FILE = BASE_DIR / "ytdlp-tray.log"


def _resolve_download_dir() -> Path:
    """Resolve download directory:
    1. config.yaml next to the exe/script with a download_path key
    2. Windows shell folder from registry via PowerShell
    3. ~/Downloads as last resort
    """
    # 1. config.yaml
    config_path = BASE_DIR / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            if "download_path" in cfg:
                return Path(cfg["download_path"])
        except Exception as exc:
            # Logged after logger is set up — store for deferred logging
            _config_warning = str(exc)

    # 2. Windows registry via PowerShell
    ps_cmd = (
        r'(Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion'
        r'\Explorer\Shell Folders" '
        r'-Name "{374DE290-123F-4565-9164-39C4925E467B}")'
        r'."{374DE290-123F-4565-9164-39C4925E467B}"'
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=5,
        )
        path_str = result.stdout.strip()
        if path_str:
            return Path(path_str)
    except Exception:
        pass

    # 3. Fallback
    return Path.home() / "Downloads"


DOWNLOAD_DIR = _resolve_download_dir()
YTDLP_PATH = str(BASE_DIR / "yt-dlp.exe")

PORT = 9876

# ── Download state (for polling) ─────────────────────────────────────────────
# Keyed by URL, value: {"status": "idle|downloading|done|error", "percent": 0}
_download_state: dict[str, Any] = {}
_state_lock = threading.Lock()

YOUTUBE_PREFIXES = (
    "https://www.youtube.com/watch",
    "https://www.youtube.com/shorts/",
    "https://youtube.com/watch",
    "https://youtube.com/shorts/",
    "https://youtu.be/",
    "https://m.youtube.com/watch",
    "https://m.youtube.com/shorts/",
)


# ── Logging ──────────────────────────────────────────────────────────────────


def _setup_logging() -> logging.Logger:
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("ytdlp-tray")
    logger.setLevel(logging.DEBUG)

    # File handler — always on
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler — only when not frozen (dev mode)
    if not getattr(sys, "frozen", False):
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger


log = _setup_logging()


# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(
    app,
    origins=[
        "https://www.youtube.com",
        "https://youtube.com",
        "https://m.youtube.com",
    ],
)

# Silence Flask's own request logger — we do our own
logging.getLogger("werkzeug").setLevel(logging.ERROR)


@app.post("/download")
def download():
    data = request.get_json(silent=True)
    if not data or "url" not in data:
        log.warning("Bad request — missing 'url'")
        return jsonify({"error": "Missing 'url' in request body"}), 400

    url: str = data["url"].strip()

    if not any(url.startswith(p) for p in YOUTUBE_PREFIXES):
        log.warning("Rejected non-YouTube URL: %s", url)
        return jsonify({"error": "URL is not a recognised YouTube URL"}), 400

    log.info("Download queued: %s", url)
    with _state_lock:
        _download_state[url] = {"status": "downloading", "percent": 0}
    threading.Thread(target=_run_ytdlp, args=(url,), daemon=True).start()
    return jsonify({"status": "started", "url": url}), 202


@app.get("/ping")
def ping():
    return jsonify({"status": "ok"}), 200


@app.get("/status")
def status():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing url param"}), 400
    with _state_lock:
        state = _download_state.get(url, {"status": "idle", "percent": 0})
    return jsonify(state), 200


# ── yt-dlp runner ─────────────────────────────────────────────────────────────


def _run_ytdlp(url: str) -> None:
    output_template = str(DOWNLOAD_DIR / "%(title)s.%(ext)s")
    cmd = [
        YTDLP_PATH,
        "--cookies-from-browser",
        "firefox",
        "--newline",  # force one progress line per line (no \r)
        "--encoding",
        "utf-8",  # force UTF-8 output (fixes Cyrillic/CJK on Windows)
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        url,
    ]
    log.info("Spawning: %s", " ".join(cmd))
    try:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"  # in case yt-dlp is a Python script
        env["PYTHONIOENCODING"] = "utf-8"

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge stderr into stdout
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        last_progress_log = 0.0
        last_progress_line = ""

        for line in process.stdout or []:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("[download]") and "%" in line:
                last_progress_line = line
                # Parse percent for polling
                try:
                    pct = float(line.split("%")[0].split()[-1])
                    with _state_lock:
                        if url in _download_state:
                            _download_state[url]["percent"] = pct
                except (ValueError, IndexError):
                    pass
                now = time.monotonic()
                if "100%" in line or (now - last_progress_log) >= 5:
                    log.info("yt-dlp: %s", line)
                    last_progress_log = now
                    last_progress_line = ""
            else:
                # Flush any pending progress line before a non-progress line
                if last_progress_line:
                    log.info("yt-dlp: %s", last_progress_line)
                    last_progress_line = ""
                    last_progress_log = time.monotonic()
                log.info("yt-dlp: %s", line)

        # Log the final progress line if it wasn't logged yet
        if last_progress_line:
            log.info("yt-dlp: %s", last_progress_line)

        process.wait()
        if process.returncode == 0:
            log.info("yt-dlp finished OK for %s", url)
            with _state_lock:
                _download_state[url] = {"status": "done", "percent": 100}
        else:
            log.error("yt-dlp FAILED (code %d) for %s", process.returncode, url)
            with _state_lock:
                _download_state[url] = {"status": "error", "percent": 0}
    except FileNotFoundError:
        log.error(
            "yt-dlp not found at '%s'.",
            YTDLP_PATH,
        )
    except Exception:
        log.exception("Unexpected error while running yt-dlp for %s", url)


# ── Tray icon ─────────────────────────────────────────────────────────────────


def _load_icon() -> Image.Image:
    """Load assets/icon.ico — present in repo and bundled by PyInstaller."""
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent.parent))
    return Image.open(bundle_dir / "assets" / "icon.ico").convert("RGBA")


def _build_tray(stop_event: Event):
    def on_quit(icon, _item):
        log.info("Quit requested from tray menu.")
        stop_event.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("yt-dlp Tray  (port %d)" % PORT, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon(
        name="ytdlp-tray",
        icon=_load_icon(),
        title="yt-dlp Tray",
        menu=menu,
    )
    return icon


# ── Flask runner (background thread) ─────────────────────────────────────────


def _run_flask(stop_event: Event) -> None:
    import werkzeug.serving

    log.info("Flask server starting on http://127.0.0.1:%d", PORT)
    log.info("Download directory: %s", DOWNLOAD_DIR)
    log.info("Log file: %s", LOG_FILE)

    # Use werkzeug's make_server so we can shut it down cleanly
    server = werkzeug.serving.make_server("127.0.0.1", PORT, app)
    server.timeout = 1

    while not stop_event.is_set():
        server.handle_request()

    log.info("Flask server stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    log.info("=" * 60)
    log.info("ytdlp-tray starting up")
    log.info("=" * 60)

    stop_event = threading.Event()

    flask_thread = threading.Thread(target=_run_flask, args=(stop_event,), daemon=True, name="flask")
    flask_thread.start()

    tray = _build_tray(stop_event)

    try:
        tray.run()  # blocks until icon.stop() is called
    except Exception:
        log.exception("Tray icon error")
    finally:
        stop_event.set()
        log.info("ytdlp-tray shut down.")


if __name__ == "__main__":
    main()
