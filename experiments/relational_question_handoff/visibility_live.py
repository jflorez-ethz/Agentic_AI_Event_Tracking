"""Run the two frozen Verification assignments in isolation. Fresh outputs only."""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from random import SystemRandom
import time
from unittest.mock import patch

from PIL import Image
from pydantic import TypeAdapter

from evaluate import ARCHIVE, ROOT, QUESTIONS
from handoff import QuestionTask
from security_augmented.agents import AgentModels, AgentRun, GeminiDecider
from security_augmented.contracts import VideoError
from security_augmented.gemini import GeminiAdapter
from security_augmented.graph_workflow import run_graph
from security_augmented.video import _decode, ingest
from security_augmented.workflow import Analysis, InspectionPlan, _observe_video

MODEL = "gemini-3.6-flash"
PACKET = Path(__file__).with_name("visibility-review")
DIGEST = {"generic": "c600a2fd6a3cab9e11d84905f6c8c8f2eb002325a798d9ad09fdabdf2a850363",
          "specific": "bd6a42b2eb761e51fdd7a242dcf608e3ff6ef8a7a043dedc964b557770eaf2e0"}


def write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def captures():
    pair = {}
    for arm, digest in DIGEST.items():
        raw = (PACKET / f"{arm}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Frozen assignment changed")
        pair[arm] = json.loads(raw)
    check = deepcopy(pair["specific"])
    part = check["contents"][0]["parts"][0]
    context = json.loads(part["text"])
    if context["relational_task"].pop("visual_question") != QUESTIONS["visibility"]:
        raise ValueError("Unexpected experimental question")
    part["text"] = json.dumps(context, ensure_ascii=False)
    if check != pair["generic"]:
        raise ValueError("Unmatched Verification requests")
    return pair


class AssignedRun(AgentRun):
    """Enter the normal graph at the saved handoff without invoking other role models."""
    def investigate(self, initial):
        self.initial = {f.observation.id: f for f in initial}
        return ()

    def report(self, events):
        return ""


def run_arm(output, expected, archive, video, *, authorized=False, transport=None):
    if transport is None and not authorized:
        raise ValueError("Paid requests and both external transfers require authorization")
    ctx = json.loads(expected["contents"][0]["parts"][0]["text"])
    data = {"status": "started", "model": MODEL, "physical_requests": [], "decisions": [], "inspections": []}
    path = output / "result.json"
    output.mkdir(mode=0o700)
    write(path, data)
    role = None
    counts = Counter()
    # Four Verification iterations. A media inspection requires a remaining iteration.
    limits = {"verification": 4, "perception": 3}

    def before(request):
        if (role not in limits or counts[role] >= limits[role] or
                request.url.path != f"/v1beta/models/{MODEL}:generateContent"):
            raise VideoError("Physical request blocked")
        body = json.loads(request.content)
        if not counts and (role != "verification" or body != expected):
            raise VideoError("First SDK request differs from frozen assignment")
        counts[role] += 1
        row = {"role": role, "number": sum(counts.values()), "bytes": len(request.content),
               "body_sha256": hashlib.sha256(request.content).hexdigest()}
        if role == "verification":
            row["request"] = body
        data["physical_requests"].append(row)
        write(path, data)

    def after(response):
        response.read()
        row = data["physical_requests"][-1]
        row["http_status"] = response.status_code
        if response.is_success:
            row["response"] = response.json()
        write(path, data)

    options = {"event_hooks": {"request": [before], "response": [after]}, "follow_redirects": False}
    env = {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}
    if transport is not None:
        options["transport"] = transport
        env["GEMINI_API_KEY"] = "offline"
    started = time.monotonic()
    with patch.dict(os.environ, env):
        adapter = GeminiAdapter.from_env(authorized=True, model=MODEL, single_request=True, client_args=options)
        with adapter.client:
            model = GeminiDecider(adapter, AgentModels(**{k: MODEL for k in
                                 ("investigation", "verification", "reporting", "video")}))

            def decide(name, context):
                nonlocal role
                if name != "verification":
                    raise VideoError("Only Verification decisions are enabled")
                role = name
                record = {"context": context}
                data["decisions"].append(record)
                try:
                    record["decision"] = model(name, context)
                    return record["decision"]
                finally:
                    role = None
                    record["diagnostics"] = model.calls[-1]
                    write(path, data)

            def inspect(interval, modality, **opts):
                nonlocal role
                if modality != "frames" or not opts.get("relational"):
                    raise VideoError("Expected a targeted relational frame inspection")
                role = "perception"
                try:
                    entry = _observe_video(video, adapter, interval, modality, "targeted", InspectionPlan(),
                                           model_guided=True, **opts)
                    data["inspections"].append({"options": opts, "entry": asdict(entry)})
                    write(path, data)
                    return (entry,)
                finally:
                    role = None

            run = AssignedRun(video, decide, inspect, archive.budget, [], autonomous_relations=True,
                              relational_selection=True, relational_tasks=True, sampled_indices={
                                  f.display_index for e in archive.evidence if e.status == "success"
                                  for f in e.inspection.frames})
            task_data = ctx["relational_task"]
            members = {f.observation.id: f for f in archive.observations if f.observation.id in task_data["observation_ids"]}
            run.dispositions = {i: {"status": status} for i, status in ctx["dispositions"].items()}
            task, = run._relation_delegations([{"observation_ids": task_data["observation_ids"]}],
                                               members, run.dispositions, movement_count=3)
            if "visual_question" in task_data:
                task = QuestionTask(task.id, task.observation_ids, task.video_id, task.interval,
                                    task.objective, visual_question=task_data["visual_question"])
            if json.loads(json.dumps(asdict(task))) != task_data:
                raise ValueError("Task provenance differs from saved assignment")
            run.relational_tasks = (task,)
            run.remaining = ctx["remaining_model_calls"] + 1  # production reserves Reporting
            events, _ = run_graph(run, tuple(members.values()))
    data.update(outcome=run.relational_outcomes[task.id], trace=[asdict(t) for t in run.trace],
                events=[asdict(e) for e in events], elapsed_ms=round(1000*(time.monotonic()-started)),
                request_counts=dict(counts), usage={}, monetary_charge=None)
    for name in counts:
        total = Counter()
        for row in data["physical_requests"]:
            if row["role"] == name:
                total.update({k:v for k,v in row.get("response", {}).get("usageMetadata", {}).items() if type(v) is int})
        data["usage"][name] = dict(total)
    data["model_config"] = {"verification": {"model": MODEL, "thinking_level": "HIGH", "max_output_tokens": 8192},
                            "perception": {"model": MODEL, "thinking_level": "HIGH", "max_output_tokens": 8192}}
    failures = [t.action for t in run.trace if t.action in ("model_failure","tool_failure","rejected")]
    data["status"] = "execution_failure" if failures else "finished"
    original = {f.id: f for item in members.values() for f in item.citation.frames
                if task.interval.start_us <= f.source_time_us < task.interval.end_us}
    selected = {i:asdict(f) for i,f in original.items()}
    for inspection in data["inspections"]:
        entry = inspection["entry"]
        if entry["status"] == "success":
            selected.update({f["id"]:f for f in entry["inspection"]["frames"]})
    data["evidence_ledger"] = [{"frame":f,"original_citation":i in original}
                               for i,f in sorted(selected.items(), key=lambda item:item[1]["source_time_us"])]
    write(path, data)
    return data


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--output", required=True, type=Path)
    for flag in ("authorize-paid-calls", "authorize-footage-transfer", "authorize-observation-text-transfer"):
        p.add_argument("--"+flag, required=True, action="store_true")
    args = p.parse_args(argv)
    pair = captures()
    archive = TypeAdapter(Analysis).validate_python(json.loads(ARCHIVE.read_text())["analysis"])
    video = ingest(ROOT / "data/raw/Meet_WalkSplit_pts.mp4")
    if video.id != archive.video.id:
        raise ValueError("Source changed")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    order = list(pair)
    rng = SystemRandom()
    rng.shuffle(order)
    labels = ["X","Y"]
    rng.shuffle(labels)
    write(args.output/"private-key.json", {"execution_order":order,"blind_labels":dict(zip(order,labels))})
    failed = False
    for arm, label in zip(order,labels):
        data = run_arm(args.output/arm, pair[arm], archive, video, authorized=True)
        failed |= data["status"] != "finished"
        folder = args.output/"assessor"/label
        folder.mkdir(parents=True)
        frames = [r["frame"] for r in data["evidence_ledger"]]
        for frame,rgb in zip(frames,_decode(video,tuple(f["display_index"] for f in frames)),strict=True):
            if hashlib.sha256(rgb).hexdigest() != frame["rgb24_sha256"]:
                raise ValueError("Assessor frame hash mismatch")
            Image.frombytes("RGB",(video.width,video.height),rgb).save(folder/f'{frame["source_time_us"]:08d}.png')
        write(folder/"frames.json", frames)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
