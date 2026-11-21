"""Small ffmpeg helpers."""
from __future__ import annotations

import functools
import json
import platform
import shutil
import subprocess
from pathlib import Path

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
]


@functools.lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    """True if this ffmpeg build has the filter. Homebrew's slim `ffmpeg` (since Jan 2026) has no
    drawtext because it is built without freetype; `brew install ffmpeg-full` has it."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(len(parts) > 1 and parts[1] == name for parts in (line.split() for line in out.stdout.splitlines()))


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found. Install ffmpeg first (brew install ffmpeg, apt install ffmpeg, or winget install ffmpeg).")


def run(cmd: list[str]) -> None:
    """Run ffmpeg and raise with its own error message if it fails."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{result.stderr[-2000:]}")


def probe(path: str | Path) -> dict:
    """Duration in seconds, fps, width and height of the first video stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    num, den = stream.get("r_frame_rate", "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    return {
        "duration": float(data["format"]["duration"]),
        "fps": fps,
        "width": int(stream["width"]),
        "height": int(stream["height"]),
    }


def find_font() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def font_option(font: str | None) -> str:
    """fontfile=... for drawtext, with the colon in Windows drive letters escaped."""
    if not font:
        return ""  # ffmpeg falls back to fontconfig's default font
    path = font.replace("\\", "/")
    if platform.system() == "Windows" or (len(path) > 1 and path[1] == ":"):
        path = path.replace(":", "\\:")
    return f"fontfile='{path}':"
