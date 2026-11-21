"""Video event check: one clip in, a list of events out (prompt event_check_v2).

Used by scripts/compare_models.py now, and meant to become the agent's ask_video tool later
(task C3). Every call is logged with tokens and cost through agentlab.usage.log_call.

Safeguard from step 3 (run 0): a model can invent a scene when the video never arrived.
For Gemini we read the VIDEO token count the API reports; if it is far below what the clip
length needs, the result is marked video_missing and its events are not trusted.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from pathlib import Path

from agentlab.usage import ROOT, log_call

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
EVENT_TYPES = ["person_down", "blocked_exit", "unattended_object", "after_hours_person", "after_hours_vehicle"]
# Gemini bills video at about 70 tokens per frame at the default resolution and 1 frame per
# second (seen in AI Studio: 4,971 tokens for 70 s). Below this per-second floor we assume
# the video did not arrive.
MIN_VIDEO_TOKENS_PER_S = 30


def load_prompt(version: str = "v2") -> dict[str, str]:
    """Split prompts/event_check_<version>.md into its === SECTION === parts."""
    text = (PROMPT_DIR / f"event_check_{version}.md").read_text(encoding="utf-8")
    parts = re.split(r"^=== ([A-Z_]+) ===\s*$", text, flags=re.M)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    sections["schema"] = json.loads((PROMPT_DIR / f"event_check_{version}.schema.json").read_text())
    return sections


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def parse_result(text: str, duration: float) -> dict:
    """Parse the model's JSON, keep known event types, cap times to the clip, keep at most 5."""
    data = json.loads(text)
    events = []
    for e in data.get("events", [])[:5]:
        if e.get("event_type") not in EVENT_TYPES:
            continue
        start = max(0.0, min(float(e.get("start_s", 0)), duration))
        end = max(start, min(float(e.get("end_s", duration)), duration))
        events.append({"event_type": e["event_type"], "start_s": round(start, 1), "end_s": round(end, 1),
                       "real": bool(e.get("real")), "reason": str(e.get("reason", ""))[:300]})
    return {"scene": str(data.get("scene", ""))[:120], "video_visible": bool(data.get("video_visible", True)),
            "events": events}


# --- Gemini (whole video) -------------------------------------------------------------------
_UPLOADS = ROOT / "runs" / "gemini_files.json"


def gemini_upload(client, path: Path):
    """Upload a clip once to the Files API and reuse it (files stay for 48 h); wait until ACTIVE."""
    cache = json.loads(_UPLOADS.read_text()) if _UPLOADS.exists() else {}
    stat = path.stat()
    key = f"{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    entry = cache.get(key)
    if entry and time.time() - entry["uploaded"] < 46 * 3600:
        try:
            f = client.files.get(name=entry["name"])
            if str(getattr(f.state, "name", f.state)) == "ACTIVE":
                return f
        except Exception:  # noqa: BLE001 - expired or deleted: upload again
            pass
    f = client.files.upload(file=str(path))
    for _ in range(120):
        state = str(getattr(f.state, "name", f.state))
        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise RuntimeError(f"Files API could not process {path.name}")
        time.sleep(2)
        f = client.files.get(name=f.name)
    cache[key] = {"name": f.name, "uri": f.uri, "uploaded": time.time()}
    _UPLOADS.parent.mkdir(parents=True, exist_ok=True)
    _UPLOADS.write_text(json.dumps(cache, indent=1))
    return f


def gemini_check(client, model: str, clip: Path, duration: float, *, thinking: str | None = None,
                 media_high: bool = False, prompt: dict | None = None, tag: str = "") -> dict:
    from google.genai import types

    prompt = prompt or load_prompt()
    f = gemini_upload(client, clip)
    config = types.GenerateContentConfig(
        system_instruction=prompt["SYSTEM"],
        response_mime_type="application/json",
        response_json_schema=prompt["schema"],
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel[thinking]) if thinking else None,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH if media_high else None,
    )
    contents = [types.Content(role="user", parts=[
        types.Part(file_data=types.FileData(file_uri=f.uri, mime_type=f.mime_type)),
        types.Part(text=prompt["USER"].format(duration=duration)),
    ])]
    t0 = time.perf_counter()
    resp = client.models.generate_content(model=model, contents=contents, config=config)
    secs = time.perf_counter() - t0

    u = resp.usage_metadata
    thoughts = u.thoughts_token_count or 0
    out_tokens = (u.candidates_token_count or 0) + thoughts
    video_tokens = sum(d.token_count or 0 for d in (u.prompt_tokens_details or [])
                       if str(getattr(d.modality, "value", d.modality)).upper().endswith("VIDEO"))
    row = log_call(provider="google", model=model, input_tokens=u.prompt_token_count or 0,
                   output_tokens=out_tokens, thinking_tokens=thoughts, seconds=secs, tag=tag,
                   extra={"video_tokens": video_tokens})
    result = parse_result(resp.text, duration)
    result.update(raw=resp.text, usage=row, seconds=round(secs, 2), video_tokens=video_tokens,
                  video_missing=video_tokens < MIN_VIDEO_TOKENS_PER_S * duration)
    return result


# --- Claude (still frames) ------------------------------------------------------------------
FRAMES_DIR = ROOT / "runs" / "frames"


def extract_frames(clip: Path, duration: float, n: int = 8, width: int = 1024) -> list[tuple[float, Path]]:
    """n frames evenly spread over the clip (middle of each slice), cached under runs/frames/.

    The cache key includes the clip's size and modification time: clip names repeat between
    site builds, and a rebuilt clip must not reuse the old frames."""
    stat = clip.stat()
    out_dir = FRAMES_DIR / f"{clip.stem}_{n}x{width}_{stat.st_size}_{int(stat.st_mtime)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(n):
        t = round((i + 0.5) * duration / n, 2)
        p = out_dir / f"f{i:02d}_{t:.2f}.jpg"
        if not p.exists():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", str(clip), "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-q:v", "3", str(p)], check=True)
        frames.append((t, p))
    return frames


def claude_check(client, model: str, clip: Path, duration: float, *, n_frames: int = 8,
                 prompt: dict | None = None, tag: str = "", focus: str = "") -> dict:
    """Send n_frames stills to Claude. A non-empty focus adds the operator's question as a last line."""
    prompt = prompt or load_prompt()
    content: list[dict] = []
    for t, p in extract_frames(clip, duration, n_frames):
        content.append({"type": "text", "text": f"Frame at {t:.1f} s:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(p.read_bytes()).decode()}})
    text = prompt["FRAMES_NOTE"].format(n=n_frames) + "\n" + prompt["USER"].format(duration=duration)
    if focus.strip():
        text += f"\nFocus from the operator: {focus.strip()}"
    content.append({"type": "text", "text": text})
    t0 = time.perf_counter()
    resp = client.messages.create(model=model, max_tokens=4000, system=prompt["SYSTEM"],
                                  messages=[{"role": "user", "content": content}],
                                  output_config={"format": {"type": "json_schema", "schema": prompt["schema"]}})
    secs = time.perf_counter() - t0
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    row = log_call(provider="anthropic", model=model, input_tokens=resp.usage.input_tokens,
                   output_tokens=resp.usage.output_tokens, seconds=secs, tag=tag)
    result = parse_result(text, duration)
    result.update(raw=text, usage=row, seconds=round(secs, 2), video_tokens=None, video_missing=False)
    return result
