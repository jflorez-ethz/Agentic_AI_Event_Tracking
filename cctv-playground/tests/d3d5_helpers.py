"""Shared by the D3/D5 tests: a scripted agent run kept in a run folder. No API calls.

Import `no_env` into each test module: it is autouse, so a test that reaches load_dotenv fails
instead of opening the real .env.
"""
from __future__ import annotations

from pathlib import Path

import dotenv
import pytest
from pydantic_ai import models

from test_triage_agent import FakeChecker, returns, scripted

from agentlab.triage_agent import AgentTriage

models.ALLOW_MODEL_REQUESTS = False

DISMISS = {"verdict": "dismiss", "priority": "low",
           "reason": "A granted badge at Door 1 explains the person in the yard."}
ESCALATE = {"verdict": "escalate", "priority": "high",
            "reason": "A person walks onto the dock at 02:00:12 with no badge or roster entry."}
PLAN = {"CAM-A-1": DISMISS, "CAM-B-1": ESCALATE}  # A-001 closed by the agent, A-002 waits for a person


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not load .env")
    monkeypatch.setattr(dotenv, "load_dotenv", refuse)


class ScriptedRun:
    """An AgentTriage with a scripted brain: get_clip, ask_video, the context tools, then the verdict."""

    def __init__(self, run_dir: Path, plan: dict | None = None, events: list[dict] | None = None):
        self.plan = plan or PLAN
        self.inner = AgentTriage(run_dir=run_dir, checker_factory=lambda kind, tag: FakeChecker(events=events))
        self.run_dir, self.stats, self.model_id = self.inner.run_dir, self.inner.stats, self.inner.model_id
        self.calls = 0

    def __call__(self, candidate, tools, open_alerts):
        self.calls += 1
        now = f"{tools.recorder.clock.now():%H:%M:%S}"

        def ask(messages, info):
            clip = [p for p in returns(messages) if p.tool_name == "get_clip"][-1].content["path"]
            return "ask_video", {"clip_path": clip, "question": "what happens?"}

        brain = scripted(("get_clip", {"camera_id": candidate["camera_id"], "start": "02:00:00", "end": now}),
                         ask,
                         ("access_log", {"start": "02:00:00", "end": now}),
                         ("roster", {"at": now}),
                         ("OUTPUT", self.plan[candidate["candidate_id"]]))
        with self.inner.agent.override(model=brain):
            return self.inner(candidate, tools, open_alerts)


def kept_run(site_dir: Path, run_dir: Path, plan: dict | None = None, events: list[dict] | None = None) -> Path:
    import evaluate
    evaluate.run(str(site_dir / "site" / "index.json"), 2,
                 triage_fn=ScriptedRun(run_dir, plan, events), keep_run=True)
    return run_dir
