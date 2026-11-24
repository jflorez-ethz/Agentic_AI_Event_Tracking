"""Plain-language HTML report for a security guard, built from a saved analysis.json.

No model call is made. Thumbnails come from the cited source frames, decoded locally from the
recorded source video after checking its SHA-256. report.md is not modified.

    .venv/bin/python -m security_augmented.guard_report experiments/<run>/run
"""
import base64
import html
import json
import re
import sys
from pathlib import Path

from pydantic import TypeAdapter

from .contracts import VideoError
from .video import _decode, _run, ingest
from .workflow import PRIORITY_LABELS, ROUTINE_LABELS, Analysis

TITLES = {
    "person_fell": "Person down", "object_placed": "Object left", "object_removed": "Object taken",
    "person_enters_area": "Person entered an area", "object_appeared": "Object appeared",
    "object_disappeared": "Object disappeared", "person_moved": "Person walking",
    "person_appeared": "Person came into view",
}
QUESTIONS = {
    "person_fell": "Is a person lying on the floor?",
    "object_placed": "Was an object put down and left there?",
    "object_removed": "Was an object taken away?",
    "person_enters_area": "Did someone enter the monitored area?",
    "object_appeared": "Did an object really appear (and was it not already there)?",
    "object_disappeared": "Did an object really disappear?",
}
WHY = {
    "not_checked": "Not checked: there was no verification slot left for it.",
    "missing_corroboration": "Checked, but the images looked at were not enough to confirm it.",
    "inspection_rejected": "The automatic check could not get more images.",
    "inspection_rejected/no_new_frames": "The automatic check could not get more images: it had already seen them all.",
    "invalid_verdict": "The automatic check gave an invalid answer.",
    "unfinished": "The automatic check stopped before reaching a conclusion.",
    "contradicted": "The automatic check thinks the images do not show it. Please confirm: this is never dismissed.",
}
# Order used to choose the headline among confirmed security events.
SEVERITY = ("person_fell", "object_placed", "object_removed", "person_enters_area",
            "object_appeared", "object_disappeared")
_TECHNICAL = re.compile(r"\b(?:frame|observation|inspection|video|alert|relational-task)-[0-9a-f]{16,}\b|\b[0-9a-f]{40,}\b")
_LABEL = re.compile(r"\b(?:(in|at|by|from|until|during|between) )?(?:frames?\s+)?F(\d+)(?:\s*(?:-|–|to|through|and)\s*F?(\d+))?\b")


def mmss(us):
    seconds = max(0, us) // 1_000_000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def span(start_us, end_us):
    first, last = mmss(start_us), mmss(max(start_us, end_us - 1))
    return first if first == last else f"{first}–{last}"


def _sentence(text, inspection):
    """First sentence of a Perception description, with frame labels turned into clock times."""
    if not text:
        return ""
    frames = inspection.frames if inspection is not None else ()

    def clock(match):
        word, *numbers = match.groups()
        times = [frames[int(n) - 1].source_time_us for n in numbers if n and 0 < int(n) <= len(frames)]
        if not times:
            return ""
        keep = word if word in ("from", "until", "during", "between") else "at"
        return f" {keep} {span(min(times), max(times) + 1)}"

    text = _TECHNICAL.sub("", _LABEL.sub(clock, text))
    text = re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\(\s*\)", "", " ".join(text.split())))
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return first[:300]


class _Thumbnails:
    """Cited frames as small JPEG data URIs; unavailable if the source video is missing or differs."""

    def __init__(self, analysis):
        self.video, self.problem = None, None
        try:
            video = ingest(Path(analysis.video.source_path))
            if video.sha256 != analysis.video.sha256:
                self.problem = "the video file differs from the one analysed"
            else:
                self.video = video
        except (OSError, VideoError):
            self.problem = "the video file is not available"

    def triplet(self, frames):
        """Before, during and after: first, middle and last of the cited frames."""
        ordered = sorted({f.display_index: f for f in frames}.values(), key=lambda f: (f.source_time_us, f.display_index))
        if not ordered:
            return []
        picks = [("Before", ordered[0]), ("During", ordered[len(ordered) // 2]), ("After", ordered[-1])]
        if self.video is None:
            return [(label, mmss(frame.source_time_us), None) for label, frame in picks]
        indices = tuple(sorted({frame.display_index for _, frame in picks}))
        pixels = dict(zip(indices, _decode(self.video, indices), strict=True))
        return [(label, mmss(frame.source_time_us), self._jpeg(pixels[frame.display_index])) for label, frame in picks]

    def _jpeg(self, rgb):
        data = _run("ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                    f"{self.video.width}x{self.video.height}", "-i", "pipe:0", "-frames:v", "1",
                    "-vf", "scale=240:-2", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "4", "pipe:1",
                    input_bytes=rgb).stdout
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()


class _Frame:
    def __init__(self, display_index, source_time_us):
        self.display_index, self.source_time_us = display_index, source_time_us


def _images(triplet, problem):
    if not triplet:
        return ""
    cells = []
    for label, when, uri in triplet:
        image = (f'<img src="{uri}" alt="{label} {when}">' if uri
                 else '<div class="noimg">image unavailable</div>')
        cells.append(f'<figure>{image}<figcaption>{label} · {when}</figcaption></figure>')
    note = f'<p class="note">Images unavailable: {html.escape(problem)}.</p>' if problem else ""
    return f'<div class="strip">{"".join(cells)}</div>{note}'


def render(result):
    """HTML text for a saved CLI result (the dict written to analysis.json)."""
    analysis = TypeAdapter(Analysis).validate_python(result["analysis"])
    video = analysis.video
    inspections = {e.inspection.id: e.inspection for e in analysis.evidence if e.inspection is not None}
    descriptions = {f.observation.id: (f.observation.description, f.observation.inspection_id)
                    for e in analysis.evidence for f in e.findings}
    thumbs = _Thumbnails(analysis)

    def sentence(observation_id):
        text, inspection_id = descriptions.get(observation_id, ("", None))
        return _sentence(text, inspections.get(inspection_id))

    events = sorted(analysis.timeline, key=lambda e: e.interval.start_us)
    security = [e for e in events if e.category in PRIORITY_LABELS]
    routine = [e for e in events if e.category in ROUTINE_LABELS]
    queue = analysis.review
    if queue is None:  # runs saved before the review queue existed: derive it locally, as the CLI would
        from .review import review

        queue = review((*analysis.timeline, *analysis.unresolved), analysis.trace, analysis.evidence)
    alerts = queue["alerts"]

    # Header facts.
    duration = video.duration_us
    scanned = min(duration, analysis.coverage.initial_scan_end_us) if analysis.coverage else duration
    portion = "the whole video" if scanned >= duration else f"{span(0, scanned)} of {mmss(duration)}"
    model_ms = sum(c.get("elapsed_ms") or 0 for c in result.get("role_calls", [])) + sum(
        (e.inference.elapsed_ms or 0) for e in analysis.evidence if e.inference is not None)
    model_time = f"{model_ms // 60000} min {model_ms // 1000 % 60:02d} s" if model_ms else "not recorded"

    if security:
        top = min(security, key=lambda e: (SEVERITY.index(e.category), e.interval.start_us))
        headline = f"{TITLES[top.category]} at {mmss(top.interval.start_us)}"
        tone = "confirmed"
    elif alerts:
        headline = f"{len(alerts)} possible security event{'s' if len(alerts) > 1 else ''} need{'' if len(alerts) > 1 else 's'} review"
        tone = "review"
    else:
        headline = "No security event found in the analysed part of the video"
        tone = "clear"

    parts = [f'<p class="headline {tone}">{html.escape(headline)}</p>']

    parts.append("<h2>Needs operator review</h2>")
    if not alerts:
        parts.append('<p class="empty">Nothing to review.</p>')
    for alert in alerts:
        frames = [_Frame(f["display_index"], f["source_time_us"]) for f in alert["frames"]]
        why = WHY.get(alert["reason_code"], WHY.get(alert["reason_code"].split("/")[0], "Not confirmed."))
        what = sentence(alert["observation_id"])
        parts.append(
            f'<section class="card review"><h3>{span(alert["interval"]["start_us"], alert["interval"]["end_us"])} · '
            f'{html.escape(TITLES[alert["category"]])}</h3>'
            f'<p class="question">{html.escape(QUESTIONS[alert["category"]])}</p>'
            + (f"<p>{html.escape(what)}</p>" if what else "")
            + f'<p class="why">{html.escape(why)}</p>{_images(thumbs.triplet(frames), thumbs.problem)}</section>')

    parts.append("<h2>Confirmed security events</h2>")
    if not security:
        parts.append('<p class="empty">None.</p>')
    for event in security:
        frames = [f for c in event.citations for f in c.frames]
        parts.append(
            f'<section class="card confirmed"><h3>{mmss(event.interval.start_us)} · {html.escape(TITLES[event.category])}</h3>'
            f"<p>{html.escape(sentence(event.observation_ids[0]))}</p>{_images(thumbs.triplet(frames), thumbs.problem)}</section>")

    parts.append("<h2>Normal activity</h2>")
    if not routine:
        parts.append('<p class="empty">None confirmed.</p>')
    else:
        rows = "".join(f'<li><span class="when">{span(e.interval.start_us, e.interval.end_us)}</span> '
                       f'{html.escape(TITLES[e.category])}: {html.escape(sentence(e.observation_ids[0]))}</li>'
                       for e in routine)
        parts.append(f'<ul class="activity">{rows}</ul>')

    unchecked = sum(1 for e in analysis.unresolved if e.reason.endswith("during triage."))
    limits = []
    if scanned < duration:
        limits.append(f"{span(scanned, duration)} ({(duration - scanned) // 1_000_000} s) was not analysed")
    if unchecked:
        limits.append(f"{unchecked} observation{'s were' if unchecked > 1 else ' was'} not checked")
    parts.append("<h2>Limits</h2><p>" + (html.escape("; ".join(limits).capitalize() + ".") if limits else
                 "The whole video was analysed and every observation was checked.") +
                 " Anything not seen in the analysed images may still have happened.</p>")

    body = "\n".join(parts)
    name = html.escape(Path(video.source_path).name)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Security report: {name}</title>
<style>
:root {{ --bg:#ffffff; --fg:#1d1d1f; --muted:#5f6368; --line:#e3e3e8; --card:#f7f7f9;
        --review:#b45309; --review-bg:#fff4e5; --ok:#15803d; --ok-bg:#ecfdf3; --alert:#b91c1c; --alert-bg:#fdecec; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16171a; --fg:#ececef; --muted:#a1a1aa; --line:#2d2f34; --card:#1f2024;
        --review:#fbbf24; --review-bg:#2b2112; --ok:#4ade80; --ok-bg:#132619; --alert:#f87171; --alert-bg:#2a1515; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
main {{ max-width:880px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }} h2 {{ font-size:1.15rem; margin:32px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
h3 {{ font-size:1.05rem; margin:0 0 6px; }}
.facts {{ color:var(--muted); margin:0; }}
.headline {{ font-size:1.25rem; font-weight:600; padding:14px 16px; border-radius:10px; margin:20px 0 0; }}
.headline.confirmed {{ background:var(--alert-bg); color:var(--alert); }} .headline.review {{ background:var(--review-bg); color:var(--review); }}
.headline.clear {{ background:var(--ok-bg); color:var(--ok); }}
.card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--line); border-radius:10px; padding:14px 16px; margin:12px 0; }}
.card.review {{ border-left-color:var(--review); }} .card.confirmed {{ border-left-color:var(--alert); }}
.question {{ font-weight:600; }} .why {{ color:var(--muted); }}
.strip {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:10px; }}
figure {{ margin:0; flex:1 1 200px; max-width:240px; }} figure img, .noimg {{ width:100%; border-radius:6px; display:block; }}
.noimg {{ aspect-ratio:4/3; display:flex; align-items:center; justify-content:center; background:var(--line); color:var(--muted); font-size:.85rem; }}
figcaption {{ font-size:.85rem; color:var(--muted); margin-top:4px; }}
.activity {{ padding-left:20px; }} .activity li {{ margin:4px 0; }} .when {{ font-variant-numeric:tabular-nums; font-weight:600; }}
.empty, .note {{ color:var(--muted); }} footer {{ margin-top:36px; color:var(--muted); font-size:.9rem; }}
a {{ color:inherit; }}
</style></head>
<body><main>
<h1>{name}</h1>
<p class="facts">Duration {mmss(duration)} · Analysed: {html.escape(portion)} · Model processing time: {model_time}</p>
{body}
<footer>Details, evidence and the full audit trail: <a href="report.md">technical report (report.md)</a>.</footer>
</main></body></html>
"""


def write(run_dir, result=None):
    """Write report.html next to analysis.json in a run directory."""
    run_dir = Path(run_dir)
    if result is None:
        result = json.loads((run_dir / "analysis.json").read_text())
    path = run_dir / "report.html"
    path.write_text(render(result), encoding="utf-8")
    return path


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m security_augmented.guard_report RUN_DIR [RUN_DIR ...]", file=sys.stderr)
        return 2
    for run_dir in args:
        print(write(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
