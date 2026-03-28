# ytdlp-tray

A Windows system-tray app that exposes a local HTTP API so the companion
Tampermonkey userscript can trigger **yt-dlp** downloads directly from
YouTube (videos and Shorts).

> **Browser support:** tested with **Firefox only**. Chrome prevents cookie
> extraction by third-party tools, so `--cookies-from-browser chrome` will
> not work with Chrome out of the box.

---

## Prerequisites

| Tool | Where to get | Notes |
|------|-------------|-------|
| **Firefox** | [firefox.com](https://www.mozilla.org/firefox/) | Should be used to navigate Youtube and trigger downloads |
| **Tampermonkey** | [tampermonkey.net](https://www.tampermonkey.net/) | Browser extension for the download button |
| **yt-dlp.exe** | [github.com/yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp/releases) | Place in project root or next to `ytdlp-tray.exe` |
| **ffmpeg.exe** | [ffmpeg.org](https://ffmpeg.org/download.html) | Required for merging video and audio streams |
| **ffprobe.exe** | bundled with ffmpeg | Required by yt-dlp for format detection |
| **deno** | `winget install DenoLand.Deno` | Used by yt-dlp to solve YouTube JS challenges |
| **uv** | `winget install astral-sh.uv` | (Optional) Python package manager, only if you want to run source files |

### Binary placement

All binaries must live in the **same directory** — either the project root
(when running with `uv`) or next to `ytdlp-tray.exe` (when using the
packaged build):

```
ytdlp-tray.exe   (or project root when using uv)
yt-dlp.exe
ffmpeg.exe
ffprobe.exe
```

Deno is installed system-wide and must be available on `PATH`.

---

## Quick start (dev / no build)

```powershell
# Clone
git clone https://github.com/mkostechuk/ytdlp-tray.git
cd ytdlp-tray

# Place yt-dlp.exe, ffmpeg.exe, ffprobe.exe in the project root

# Install Python deps
uv sync

# Run (shows tray icon, starts server on port 9876)
uv run ytdlp-tray
```

---

## Build single `.exe`

```powershell
PowerShell -ExecutionPolicy Bypass -File .\build.ps1
```

Output: `dist\ytdlp-tray.exe`

Copy `ytdlp-tray.exe` together with `yt-dlp.exe`, `ffmpeg.exe`, and
`ffprobe.exe` into any folder. The log file (`ytdlp-tray.log`) and
`config.yaml` (if used) are also read from that same folder.

To launch on Windows startup, create a shortcut to `ytdlp-tray.exe` and
place it in:
```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

---

## Tampermonkey userscript

1. Open Tampermonkey → **Create new script**
2. Paste the contents of `youtube_downloader.user.js`
3. Save — a download button appears on every YouTube video and Short

The button changes state as the download progresses:

| State | Appearance |
|-------|-----------|
| Idle | ⬇ blue |
| Downloading | `47%` pale yellow |
| Done | ✔ green (stays until you navigate away) |
| Error | ✘ dark red |

---

## Configuration

### config.yaml (optional)

Create `config.yaml` next to `ytdlp-tray.exe`.

#### 1. Download path

```yaml
download_path: 'D:\Downloads'
```
Resolution order for download directory:
1. `download_path` key from the config
2. Windows shell folder from registry via PowerShell
3. `~/Downloads` as last resort

#### 2. yt-dlp extra options

You can add some extra options for the yt-dlp call.

_These options are passed to yt-dlp as-is and you need to refer to its documentation to see the complete list of options._

```yaml
ytdlp_options:
  - '-S "res:1080"'
  - '-f "bestvideo*+bestaudio/best"'
```
 For example if you want to limit the resolution of the downloaded videos to 1080p, you can use the 2 options above.


---

## Logging

Every event is timestamped and appended to `ytdlp-tray.log` in the same
directory as the executable:

```
2024-11-01 14:23:01  INFO     ytdlp-tray starting up
2024-11-01 14:23:01  INFO     Flask server starting on http://127.0.0.1:9876
2024-11-01 14:23:01  INFO     Download directory: D:\Downloads
2024-11-01 14:23:45  INFO     Download queued: https://www.youtube.com/watch?v=dQw4w9WgXcQ
2024-11-01 14:23:45  INFO     Spawning: yt-dlp.exe --cookies-from-browser firefox ...
2024-11-01 14:23:46  INFO     yt-dlp: [youtube] Extracting URL: ...
2024-11-01 14:23:48  INFO     yt-dlp: [download]   0.0% of 243.18MiB at 2.50MiB/s ETA 01:33
2024-11-01 14:25:12  INFO     yt-dlp finished OK for https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

---

## Tray menu

Right-click the tray icon:

```
yt-dlp Tray  (port 9876)   ← greyed out label
─────────────────────────
Quit
```

---

## API reference

### `POST /download`
```json
{ "url": "https://www.youtube.com/watch?v=..." }
```
Returns `202 Accepted` immediately; download runs in the background.

### `GET /status?url=<url>`
```json
{ "status": "downloading", "percent": 47.3 }
```
Possible status values: `idle`, `downloading`, `done`, `error`.

### `GET /ping`
```json
{ "status": "ok" }
```