"""The frame check behind the agent's ask_video and second_look tools (step 5, task C3).

One clip in, an event list out: 16 still frames, prompt event_check_v2, the operator's
question as a "focus" line. Claude Haiku 5.5 looks first. A rule in code, not the agent,
sends the same clip to Sonnet 5.5 when Haiku's answer cannot be trusted on its own:

1. the alert is an unattended object (Haiku was weak on these in experiment 2);
2. Haiku's answer mentions an unattended object;
3. Haiku's answer has no event of the alert's type, real or look-alike.

One checker is built per alert, so the rule knows the alert's type. Every call is logged
through agentlab.usage (inside claude_check), and the checker keeps a running cost.
"""
from __future__ import annotations

from pathlib import Path

from agentlab.event_check import claude_check, probe_duration

DEFAULT_MODEL = "claude-haiku-5-5"
STRONG_MODEL = "claude-sonnet-5-5"


def escalation_reason(alert_kind: str, events: list[dict]) -> str | None:
    """Why Haiku's answer goes to Sonnet, or None to keep it."""
    if alert_kind == "unattended_object":
        return "unattended object alert"
    if any(e.get("event_type") == "unattended_object" for e in events):
        return "answer mentions an unattended object"
    if not any(e.get("event_type") == alert_kind for e in events):
        return f"no {alert_kind} event in the answer"
    return None


class VideoChecker:
    def __init__(self, client, alert_kind: str, *, tag: str = "", default_model: str = DEFAULT_MODEL,
                 strong_model: str = STRONG_MODEL, n_frames: int = 16, max_clip_s: float = 120.0):
        self.client = client
        self.alert_kind = alert_kind
        self.tag = tag
        self.default_model = default_model
        self.strong_model = strong_model
        self.n_frames = n_frames
        self.max_clip_s = max_clip_s
        self.calls = 0
        self.cost_usd = 0.0
        self.ask_escalated = False  # an ask_video answer already came from the strong model

    def _run(self, model: str, clip: Path, duration: float, question: str) -> dict:
        try:
            res = claude_check(self.client, model, clip, duration, n_frames=self.n_frames,
                               tag=f"{self.tag}:{model}", focus=question)
        except Exception as err:  # noqa: BLE001 - the agent must see an error, not crash
            raise ValueError(f"video model unavailable: {type(err).__name__}: {err}"[:500]) from err
        self.calls += 1
        self.cost_usd += res.get("usage", {}).get("cost_usd") or 0.0
        return res

    def check(self, clip_path: str, question: str = "", *, strong: bool = False) -> dict:
        clip = Path(clip_path)
        if not clip.is_file():
            raise ValueError(f"No clip at {clip_path}.")
        try:
            duration = probe_duration(clip)
        except Exception as err:  # noqa: BLE001
            raise ValueError(f"Could not read the clip at {clip_path}: {type(err).__name__}.") from err
        if duration > self.max_clip_s:
            raise ValueError(f"Clip is {duration:.0f} s; frame checks need {self.max_clip_s:.0f} s or less. "
                             "Ask for a shorter window.")

        if strong:
            model, why = self.strong_model, "second look"
            res = self._run(model, clip, duration, question)
        else:
            model = self.default_model
            res = self._run(model, clip, duration, question)
            why = escalation_reason(self.alert_kind, res["events"])
            if why:
                model = self.strong_model
                res = self._run(model, clip, duration, question)
                self.ask_escalated = True
        return {
            "scene": res["scene"],
            "video_visible": res["video_visible"],
            "events": res["events"],
            "times": "seconds from the start of the clip",
            "model": model,
            "escalated": why is not None,
            "why": why,
        }
