# build.ps1 - Build ytdlp-tray.exe with PyInstaller via uv
# Run from the project root:  .\build.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host '=== ytdlp-tray build ===' -ForegroundColor Cyan

# 1. Sync dependencies
Write-Host '[1/2] Syncing uv environment...' -ForegroundColor Yellow
uv sync

# 2. Install PyInstaller and build
Write-Host '[2/2] Installing PyInstaller and building...' -ForegroundColor Yellow
uv add --dev pyinstaller

uv run pyinstaller `
    --onefile `
    --windowed `
    --name 'ytdlp-tray' `
    --icon 'assets/icon.ico' `
    --add-data 'assets/icon.ico;assets' `
    --hidden-import 'pystray._win32' `
    --hidden-import 'PIL._tkinter_finder' `
    'src/ytdlp_tray/main.py'

Write-Host '=== Build complete ===' -ForegroundColor Green
Write-Host 'Executable: dist\ytdlp-tray.exe' -ForegroundColor Green
Write-Host ''
Write-Host 'Place yt-dlp.exe, ffmpeg.exe and ffprobe.exe in the same folder as ytdlp-tray.exe'
Write-Host 'Log file will appear as ytdlp-tray.log next to the exe'