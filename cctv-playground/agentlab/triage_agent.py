"""The step 5 triage agent (task D2): checks each detector alert the way an operator would.

Drop-in replacement for fakecctv.triage_stub.triage: an AgentTriage instance is called as
triage(candidate, tools, open_alerts) and returns {verdict, priority, reason, evidence, linked_to}.

- The brain is Claude Haiku 5.5 in Pydantic AI (v2), with a typed output (TriageVerdict).
- It touches the site only through AgentTools: now, list_cameras, get_clip, get_frame,
  access_log, roster, procedures, ask_video and second_look.
- Hard rules are applied in code after its verdict (apply_rules): person-down and fire always
  go to a person at high priority, links must point at an open alert on a neighbouring camera,
  evidence comes from the trace, and any failure sends the alert to a person.
- Each alert can leave a run file with the task, the messages, the trace, the verdict and the
  cost (tokens of the brain plus every video check).

No sampling settings (temperature, top_p, top_k) are set anywhere: claude-haiku-5-5 rejects
non-default values.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import pydantic_ai
from pydantic import BaseModel, Field
from pydantic_ai import (
    Agent, ModelMessagesTypeAdapter, ModelResponse, RunContext, UsageLimits, capture_run_messages,
)

from agentlab.usage import log_call
from agentlab.video_check import VideoChecker
from fakecctv.tools import AgentTools
from fakecctv.triage_stub import NEVER_DISMISS

pydantic_ai.BANNER_ENABLED = False  # keep evaluate.py's table output clean

BRAIN_MODEL = "anthropic:claude-haiku-5-5"
MAX_SECOND_LOOKS = 2
KEYS = ("verdict", "priority", "reason", "evidence", "linked_to")

SAFETY_NOTE = " [Rule: person-down and fire alerts always go to a person, priority high.]"
BAD_LINK_NOTE = " [Rule: link target is not an open alert on a neighbouring camera; sent to a person.]"

INSTRUCTIONS = """\
You are the triage step in the control room of an industrial or logistics site. The site is
closed, except for the people and zones the roster lists. A detector has raised an alert on one camera. Check it the way an experienced operator
would, then decide whether the guard on duty needs to see it.

The usual route:
1. Cut a clip with get_clip from 20 s before the alert was first seen up to now.
2. Call ask_video on that clip's path, with a question about the alert's event type.
3. Check access_log for the doors of the alert's camera over the 10 minutes before first seen
   (up to now), and roster at the first-seen time. Read procedures when the case is unclear.
4. Check whether an open alert on a neighbouring camera (listed in the task) covers the same event.
5. Give your verdict.
You may leave this route when the evidence calls for it, for example to cut a neighbouring
camera's clip or to ask a narrower question.

Using the tools:
- Times are site clock times such as 02:10:05. Never ask for footage or log entries after the
  site time now: nothing later has been recorded. If a tool returns an error, read it, correct
  the request (for example an earlier end time) and carry on.
- ask_video gives event times in seconds from the start of the clip, not site times. Add them
  to the clip's start time to get site times.
- second_look has a stronger video model look again at 15 s either side of a site time. Use it
  only when the evidence conflicts, for example the video shows no one but nobody badged in.
  At most 2 second looks per alert, and none when ask_video already answered with the stronger
  model (its "model" field is claude-sonnet-5-5).

Your verdict:
- dismiss, priority low: only when the video shows a look-alike, or the access log or roster
  explains the activity (a granted badge at a door of this camera in the previous 10 minutes,
  or a roster entry for this zone at that time).
- linked: only to an open alert on a neighbouring camera, listed in the task, that shows the
  same event within 5 minutes. Put that alert's id in linked_to and use its priority.
- escalate: everything else, and whenever you are unsure. Priority high for a person-down, a
  fire, or a person or vehicle that nothing explains; medium for a blocked exit, an unattended
  object or an unclear case.
- person_down and fire alerts are always escalated with priority high.
- reason: one to three sentences saying what was seen, on which camera, when (site time), and
  which context you checked (access log, roster, neighbouring alerts).
- Never identify people or describe their face, age, gender or ethnicity; say "a person".
"""


class TriageVerdict(BaseModel):
    verdict: Literal["escalate", "dismiss", "linked"]
    priority: Literal["high", "medium", "low"]
    reason: str = Field(min_length=10, description="What was seen, where, when, and which context was checked.")
    linked_to: str | None = Field(None, description="Id of the open alert this one is linked to; only for 'linked'.")


@dataclass
class TriageDeps:
    tools: AgentTools
    second_looks: int = 0
    # Re-entrant: a wrapper may call into code that takes it again in the same thread.
    lock: threading.RLock = field(default_factory=threading.RLock)


def _doc(method: Callable) -> Callable:
    """Give a tool wrapper the docstring of the AgentTools method it wraps (the tool description)."""
    def deco(fn: Callable) -> Callable:
        fn.__doc__ = method.__doc__
        return fn
    return deco


def build_agent(model: str = BRAIN_MODEL) -> Agent[TriageDeps, TriageVerdict]:
    # defer_model_check: the model (and its API key) is resolved at the first run, so tests can
    # build the agent and override the model without a key.
    agent = Agent(model, deps_type=TriageDeps, output_type=TriageVerdict, instructions=INSTRUCTIONS,
                  retries=2, defer_model_check=True)

    # Every wrapper holds deps.lock and is marked sequential: Pydantic AI runs sync tools in
    # worker threads, and the trace, the recorder and the video checker are not thread-safe.
    tool = agent.tool(sequential=True)

    @tool
    @_doc(AgentTools.now)
    def now(ctx: RunContext[TriageDeps]) -> dict:
        with ctx.deps.lock:
            return ctx.deps.tools.now()

    @tool
    @_doc(AgentTools.list_cameras)
    def list_cameras(ctx: RunContext[TriageDeps]) -> list[dict]:
        with ctx.deps.lock:
            return ctx.deps.tools.list_cameras()

    @tool
    @_doc(AgentTools.get_clip)
    def get_clip(ctx: RunContext[TriageDeps], camera_id: str, start: str, end: str) -> dict:
        with ctx.deps.lock:
            return ctx.deps.tools.get_clip(camera_id, start, end)

    @tool
    @_doc(AgentTools.get_frame)
    def get_frame(ctx: RunContext[TriageDeps], camera_id: str, at: str) -> dict:
        with ctx.deps.lock:
            return ctx.deps.tools.get_frame(camera_id, at)

    @tool
    @_doc(AgentTools.access_log)
    def access_log(ctx: RunContext[TriageDeps], start: str, end: str, door: str | None = None) -> dict:
        with ctx.deps.lock:
            return ctx.deps.tools.access_log(start, end, door)

    @tool
    @_doc(AgentTools.roster)
    def roster(ctx: RunContext[TriageDeps], at: str) -> dict:
        with ctx.deps.lock:
            return ctx.deps.tools.roster(at)

    @tool
    @_doc(AgentTools.procedures)
    def procedures(ctx: RunContext[TriageDeps]) -> dict:
        with ctx.deps.lock:
            return ctx.deps.tools.procedures()

    @tool
    @_doc(AgentTools.ask_video)
    def ask_video(ctx: RunContext[TriageDeps], clip_path: str, question: str) -> dict:
        with ctx.deps.lock:
            return ctx.deps.tools.ask_video(clip_path, question)

    @tool
    @_doc(AgentTools.second_look)
    def second_look(ctx: RunContext[TriageDeps], camera_id: str, around: str, question: str) -> dict:
        deps = ctx.deps
        with deps.lock:
            refusal = None
            if deps.second_looks >= MAX_SECOND_LOOKS:
                refusal = f"Second-look limit ({MAX_SECOND_LOOKS}) reached for this alert."
            elif getattr(deps.tools.video_checker, "ask_escalated", False):
                refusal = ("ask_video already used the stronger model for this alert, so a second look "
                           "is not available. Decide from what you have.")
            if refusal:
                deps.tools.trace.append({
                    "site_time": deps.tools.recorder.clock.now().strftime("%H:%M:%S"), "tool": "second_look",
                    "args": {"camera_id": camera_id, "around": str(around), "question": question},
                    "ok": False, "result": refusal})
                return {"error": refusal}
            result = deps.tools.second_look(camera_id, around, question)
            if "error" not in result:
                deps.second_looks += 1
            return result

    return agent


def _hms(iso: str) -> str:
    return iso[11:19] if len(iso) >= 19 else iso


def task_message(candidate: dict, now: str, camera, open_alerts: list[dict]) -> str:
    """The task for one alert, built in code. Never includes labels or ground truth."""
    neighbors = list(camera.neighbors)
    lines = [
        "A detector raised this alert. Check it and give your verdict.",
        f"- Alert id: {candidate['candidate_id']}",
        f"- Camera: {candidate['camera_id']}, zone: {candidate['zone']}",
        f"- Event type: {candidate['kind']}",
        f"- First seen: {_hms(candidate['first_seen'])}",
        f"- Detected at: {_hms(candidate['detected_at'])}",
        f"- Site time now: {now}",
        f"- Doors on this camera: {', '.join(camera.doors) or 'none'}",
        f"- Neighbouring cameras: {', '.join(neighbors) or 'none'}",
        "",
    ]
    near = [a for a in open_alerts if a["candidate"]["camera_id"] in neighbors]
    if near:
        lines.append("Open alerts on neighbouring cameras:")
        lines += [f"- {a['id']}: {a['candidate']['camera_id']}, {a['candidate']['kind']}, "
                  f"first seen {_hms(a['candidate']['first_seen'])}, priority {a['priority']}" for a in near]
    else:
        lines.append("No open alerts on neighbouring cameras.")
    return "\n".join(lines)


def evidence_from_trace(trace: list[dict]) -> list[str]:
    """Clips and frames the tools actually produced, in order, never paths the model typed."""
    out: list[str] = []
    for step in trace:
        if not step.get("ok") or not isinstance(step.get("result"), dict):
            continue
        key = {"get_clip": "path", "get_frame": "path", "second_look": "clip_path"}.get(step["tool"])
        path = step["result"].get(key) if key else None
        if path and path not in out:
            out.append(path)
    return out


def apply_rules(candidate: dict, out: TriageVerdict | None, failure: str | None, open_alerts: list[dict],
                neighbors: list[str], trace: list[dict]) -> tuple[dict, list[str]]:
    """The agent's verdict after the hard rules. Returns (verdict dict, names of the rules that fired)."""
    overrides: list[str] = []
    if failure or out is None:
        verdict, priority, linked_to = "escalate", "medium", None
        reason = f"Agent could not finish: {failure or 'no verdict'}. Passed to a person."
        overrides.append("failure")
    else:
        verdict, priority, reason, linked_to = out.verdict, out.priority, out.reason, out.linked_to

    if candidate["kind"] in NEVER_DISMISS and not (verdict == "escalate" and priority == "high"):
        verdict, priority = "escalate", "high"
        reason += SAFETY_NOTE
        overrides.append("safety rule")

    if verdict == "linked":
        valid = {a["id"] for a in open_alerts if a["candidate"]["camera_id"] in neighbors}
        if linked_to not in valid:
            verdict = "escalate"
            reason += BAD_LINK_NOTE
            overrides.append("bad link")

    if verdict != "linked":
        linked_to = None
    final = {"verdict": verdict, "priority": priority, "reason": reason,
             "evidence": evidence_from_trace(trace), "linked_to": linked_to}
    return final, overrides


class AgentTriage:
    """triage(candidate, tools, open_alerts) -> verdict dict, with per-alert stats and run files."""

    def __init__(self, model: str = BRAIN_MODEL, *, run_dir: Path | None = None, request_limit: int = 12,
                 checker_factory: Callable[[str, str], object] | None = None):
        self.model = model
        self.model_id = model.split(":", 1)[1] if ":" in model else model
        self.agent = build_agent(model)
        self.run_dir = Path(run_dir) if run_dir else None
        self.request_limit = request_limit
        self.checker_factory = checker_factory or self._default_checker
        self._client = None
        self.stats: dict[str, dict] = {}
        self.last_messages: list = []

    def _default_checker(self, kind: str, tag: str) -> VideoChecker:
        if self._client is None:  # created on first use, so building AgentTriage needs no key
            import anthropic
            self._client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip() or None)
        return VideoChecker(self._client, kind, tag=tag)

    def __call__(self, candidate: dict, tools: AgentTools, open_alerts: list[dict]) -> dict:
        t0 = time.perf_counter()
        cid = candidate["candidate_id"]
        checker = self.checker_factory(candidate["kind"], f"triage:{cid}")
        tools.video_checker = checker
        camera = tools.site.camera(candidate["camera_id"])
        now = tools.recorder.clock.now().strftime("%H:%M:%S")
        task = task_message(candidate, now, camera, open_alerts)
        deps = TriageDeps(tools)

        out, failure = None, None
        with capture_run_messages() as messages:
            try:
                result = self.agent.run_sync(task, deps=deps,
                                             usage_limits=UsageLimits(request_limit=self.request_limit))
                out = result.output
            except Exception as err:  # noqa: BLE001 - any failure sends the alert to a person
                failure = f"{type(err).__name__}: {err}"[:300]
        self.last_messages = list(messages)

        # Count from the messages, not result.usage, so a failed run is counted too.
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        in_tok = sum(m.usage.input_tokens or 0 for m in responses)
        out_tok = sum(m.usage.output_tokens or 0 for m in responses)
        seconds = time.perf_counter() - t0
        row = log_call(provider="anthropic", model=self.model_id, input_tokens=in_tok, output_tokens=out_tok,
                       seconds=seconds, tag=f"triage:{cid}:agent", extra={"requests": len(responses)})

        final, overrides = apply_rules(candidate, out, failure, open_alerts, list(camera.neighbors), tools.trace)
        self.stats[cid] = {
            "requests": len(responses),
            "tool_calls": len(tools.trace),
            "tool_errors": sum(1 for s in tools.trace if not s["ok"]),
            "second_looks": deps.second_looks,
            "video_calls": getattr(checker, "calls", 0),
            "overrides": overrides,
            "cost_usd": round((row["cost_usd"] or 0.0) + getattr(checker, "cost_usd", 0.0), 6),
            "seconds": round(seconds, 2),
        }
        if self.run_dir:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "candidate": candidate, "task": task,
                "output": out.model_dump() if out else None, "failure": failure,
                "final": final, "overrides": overrides, "trace": tools.trace,
                "messages": ModelMessagesTypeAdapter.dump_python(self.last_messages, mode="json"),
                "stats": self.stats[cid],
            }
            (self.run_dir / f"{cid}.json").write_text(json.dumps(record, indent=1, default=str))
        return final
