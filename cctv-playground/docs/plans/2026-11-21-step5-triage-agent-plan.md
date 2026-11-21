# Step 5: Triage Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rule-based `fakecctv/triage_stub.triage` with a Pydantic AI agent. The brain is Claude Haiku 5.5. It checks each detector alert using the kit's tools plus a working `ask_video`, and returns the stub's verdict format. Run it through `evaluate.py`, first on the placeholder site and then on a site built from our real clips.

**Architecture:**
- `agentlab/video_check.py` turns a clip into an event list. Haiku looks at 16 frames, and a rule passes some clips to Sonnet.
- `fakecctv/tools.py` calls that checker from `ask_video` and from a new `second_look`.
- `agentlab/triage_agent.py` holds the agent, the hard rules applied after its verdict, and the per-alert run file.
- `evaluate.py` gets a `--triage stub|agent` switch and cost columns.

**Tech Stack:** Python ≥3.10, pydantic-ai-slim[anthropic] 2.x, anthropic SDK, ffmpeg, pytest.

**Spec:** `docs/design/2026-11-21-step5-triage-agent-design.md` (approved 21 Nov, with run 2 after run 1).

**Where work happens (decided 21 Nov):**
- Claude Code builds the plan on the Mac. It checks the plan in plan mode first, then builds.
- Claude in the project chat reviews each batch by reading the git history and running the tests in its own copy.
- The user runs the paid runs (run 1, run 2) and reports the output.
- Step 0: put the kit under git (baseline commit) so each task is one reviewable commit. Commit messages: `step5 task N: <what>`.
- Session 1 covers Tasks 1 to 5, Step 4. Task 6 waits for run 1's results.

## Global Constraints
- Brain: `anthropic:claude-haiku-5-5`. In Pydantic AI v2, model strings need the provider prefix.
- Video models: default `claude-haiku-5-5`, strong `claude-sonnet-5-5`. 16 frames, 1024 px wide, prompt `event_check_v2`.
- Dependency: `pydantic-ai-slim[anthropic]>=2.71,<3`. In v2, `result.usage` is a property, not a method.
- Verdict dict keys are exactly `verdict, priority, reason, evidence, linked_to`:
  - `verdict` ∈ {escalate, dismiss, linked};
  - `priority` ∈ {high, medium, low}.
- `NEVER_DISMISS = {"person_down", "fire"}`, imported from `fakecctv.triage_stub`.
- Budget per alert:
  - `request_limit=12`;
  - at most 2 second looks;
  - a second look covers 15 s either side of the given time, ending no later than now.
- The usual first clip runs from first seen −20 s to now.
- The detector waits 30 s before raising `unattended_object` and 10 s (the default) for every other type.
- Tests never call a real model: set `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` in the agent test module.
- Every model call is logged through `agentlab.usage.log_call`.
- Stop and estimate the cost before any run that may cost more than $1.

## Review Focus
1. **The agent passes a clip path that does not exist.** `ask_video` returns `{"error": ...}` and the run continues. Test in Task 3.
2. **The agent writes a time the site cannot parse,** for example "ten past two". The tool returns an error and the trace shows `ok: False`. Test in Task 3.
3. **The Anthropic API fails inside a video check** (overloaded, rate limit). The checker raises `ValueError("video model unavailable: ...")`, so the agent sees an error and can decide from the context. Test in Task 2.
4. **The agent asks a frame check for a very long clip.** 16 frames over 10 minutes are useless, so the checker refuses clips over 120 s with a message asking for a shorter window. Test in Task 2.
5. **A rebuilt site reuses stale cached frames.** Clip names repeat between builds. The frame cache key gains the clip's size and modification time. Test in Task 1.

---

### Task 1: Dependency, focus line and frame cache key

**Files:**
- Modify: `requirements-agent.txt`
- Modify: `agentlab/event_check.py`. `extract_frames` around line 130; `claude_check` around line 145.
- Test: `tests/test_agentlab.py`

**Interfaces:**
- Produces:
  - `claude_check(client, model, clip, duration, *, n_frames=8, prompt=None, tag="", focus="") -> dict`. A non-empty `focus` appends the line `"\nFocus from the operator: {focus}"` after the USER text.
  - `extract_frames` caches under `FRAMES_DIR / f"{clip.stem}_{n}x{width}_{size}_{int(mtime)}"`.

- [ ] **Step 1: Write the failing tests**
  - `test_claude_check_adds_focus_line`: using the fake `create` pattern from `test_claude_check_sends_frames_with_times`, the last text block contains `"Focus from the operator: is anyone lying down?"`.
  - `test_claude_check_without_focus_has_no_focus_line`: the last text block does not contain "Focus from the operator".
  - `test_frame_cache_changes_when_clip_changes`: extract frames from `_clip(tmp_path, 4)`. Overwrite the file with `_clip` of 6 s, extract again. The two frame folders differ.
- [ ] **Step 2:** Run `pytest tests/test_agentlab.py -q`. Expected: the 3 new tests FAIL.
- [ ] **Step 3:** Implement both changes in `agentlab/event_check.py`. Add `pydantic-ai-slim[anthropic]>=2.71,<3` to `requirements-agent.txt`. Then `pip install -r requirements-agent.txt`.
- [ ] **Step 4:** Run `python -c "import pydantic_ai, sys; print(pydantic_ai.__version__)"`. Expected: a version starting with `2.`. Then run `pytest -q`. Expected: all pass (18 + 3).

### Task 2: Video checker with the escalation rule

**Files:**
- Create: `agentlab/video_check.py`
- Test: `tests/test_video_check.py`

**Interfaces:**
- Consumes: `claude_check(..., focus=...)` and `probe_duration(path)` from `agentlab/event_check.py`.
- Produces:
  - `escalation_reason(alert_kind: str, events: list[dict]) -> str | None`. Checks in this order:
    1. `"unattended object alert"` if `alert_kind == "unattended_object"`;
    2. `"answer mentions an unattended object"` if any event has `event_type == "unattended_object"`;
    3. `f"no {alert_kind} event in the answer"` if no event has `event_type == alert_kind` (real or look-alike);
    4. otherwise `None`.
  - `class VideoChecker`:
    - `__init__(self, client, alert_kind: str, *, tag: str = "", default_model="claude-haiku-5-5", strong_model="claude-sonnet-5-5", n_frames=16, max_clip_s=120.0)`;
    - attributes `calls: int` and `cost_usd: float`.
  - `VideoChecker.check(self, clip_path: str, question: str = "", *, strong: bool = False) -> dict`. Returns `{"scene", "video_visible", "events", "times", "model", "escalated", "why"}`:
    - `times` is `"seconds from the start of the clip"`;
    - `model` is the id that produced `events`;
    - `escalated` and `why` record the reason, or `"second look"` when `strong=True`.
  - Errors are raised as `ValueError`:
    - missing file: `"No clip at {path}."`;
    - clip too long: `"Clip is {d:.0f} s; frame checks need 120 s or less. Ask for a shorter window."`;
    - any exception from the client: `"video model unavailable: {type}: {msg}"`.

- [ ] **Step 1: Write the failing tests.** Use a fake client whose `messages.create` returns a canned JSON answer per model and counts calls. Reuse `isolate`, `_clip` and the response shape from `tests/test_agentlab.py`.
  - `test_escalation_reason_rules`: the four cases above, with the exact strings.
  - `test_keeps_haiku_answer_when_it_covers_the_alert`: kind `person_down`; Haiku returns a person_down event. Expect `calls == 1`, `model == "claude-haiku-5-5"` and `escalated is False`.
  - `test_escalates_to_sonnet_when_nothing_of_the_kind`: Haiku returns `events: []`. Expect `calls == 2`, `model == "claude-sonnet-5-5"` and `why == "no person_down event in the answer"`.
  - `test_unattended_object_always_escalates`: expect `calls == 2`.
  - `test_strong_goes_straight_to_sonnet`: expect `calls == 1`, model sonnet and `why == "second look"`.
  - `test_cost_accumulates_from_usage_rows`: `cost_usd > 0` after one check.
  - `test_missing_clip_and_long_clip_raise_value_error`: a 130 s clip from `_clip`, and a path that does not exist.
  - `test_client_failure_becomes_value_error`: the client raises `RuntimeError("overloaded")`; the message starts with `"video model unavailable"`.
- [ ] **Step 2:** Run `pytest tests/test_video_check.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `agentlab/video_check.py`. Tag each call `f"{tag}:{model}"`. Add `usage["cost_usd"]` from each `claude_check` result to `cost_usd`.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.

### Task 3: `ask_video` and `second_look` in AgentTools

**Files:**
- Modify: `fakecctv/tools.py`
- Create: `tests/conftest.py`. Move the `site_dir` fixture there from `tests/test_kit.py`, unchanged.
- Modify: `tests/test_kit.py` (remove the moved fixture).
- Test: `tests/test_tools_video.py`

**Interfaces:**
- Consumes: any object with `check(clip_path, question="", *, strong=False) -> dict` (Task 2's `VideoChecker`).
- Produces:
  - `AgentTools.__init__(self, recorder, context, video_checker=None)` and the attribute `self.video_checker`, which the triage agent sets per alert.
  - `ask_video(clip_path, question)`:
    - with no checker: raises today's `ValueError`, "not connected yet (task C3)";
    - otherwise: `self.video_checker.check(clip_path, question)`.
  - `second_look(camera_id: str, around: str, question: str) -> dict`:
    - takes the window from `around`−15 s to min(`around`+15 s, now);
    - if that window is empty, raises `NotYetAvailable(f"Nothing has been recorded around {around} yet (now {now:%H:%M:%S}).")`;
    - cuts the clip through the recorder and calls `check(path, question, strong=True)`;
    - returns `{**result, "camera_id", "start", "end", "clip_path"}`, with times as `%H:%M:%S`;
    - with no checker: raises `ValueError("second_look is not connected (no video checker).")`.
  - Both calls go through `_call`, so they appear in the trace.

- [ ] **Step 1: Write the failing tests.** Use a `FakeChecker` that records `(clip_path, question, strong)` and returns `{"events": [], "model": "fake"}`. The clock is at site start +10 s, as in `test_tools_report_errors_and_keep_a_trace`.
  - `test_ask_video_without_checker_is_an_error`
  - `test_ask_video_calls_the_checker`
  - `test_ask_video_missing_clip_is_an_error_in_the_trace`: `FakeChecker` raises `ValueError` for a missing path; the trace shows `ok` False.
  - `test_unparseable_time_is_an_error`: `get_clip("CAM-A", "ten past two", "02:00:05")` returns an error.
  - `test_second_look_clamps_to_now`: `second_look("CAM-A", "02:00:09", "q")`. Expect `end == "02:00:10"` and the checker called with `strong=True`.
  - `test_second_look_in_the_future_is_refused`: `around="02:00:28"` returns `{"error": ...}`.
- [ ] **Step 2:** Run `pytest tests/test_tools_video.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement the changes in `fakecctv/tools.py` and move the fixture.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass, including the existing kit tests.

### Task 4: The triage agent and its rules

**Files:**
- Create: `agentlab/triage_agent.py`
- Test: `tests/test_triage_agent.py`

**Interfaces:**
- Consumes: `AgentTools` (Task 3), `VideoChecker` (Task 2), `log_call` and `cost_usd` from `agentlab/usage.py`, and `NEVER_DISMISS` from `fakecctv.triage_stub`.
- Produces:
  - `class TriageVerdict(BaseModel)`:
    - `verdict: Literal["escalate","dismiss","linked"]`;
    - `priority: Literal["high","medium","low"]`;
    - `reason: str` (min_length 10);
    - `linked_to: str | None = None`.
  - `@dataclass TriageDeps`: `tools: AgentTools`, `second_looks: int = 0` and a `threading.Lock`.
  - `INSTRUCTIONS: str`. It must state:
    - the usual route (design step 2);
    - times never after now; on a tool error, read it and adjust the request;
    - `ask_video` times are seconds from the clip start;
    - dismiss only when the video shows a look-alike, or the access log or roster explains the activity;
    - escalate when unsure;
    - person-down and fire always escalate high;
    - link only to an open alert on a neighbouring camera that shows the same event within 5 minutes;
    - the reason says what was seen, where, when, and which context was checked;
    - never identify people;
    - at most 2 second looks, and none after `ask_video` already used Sonnet.
  - `build_agent(model: str = "anthropic:claude-haiku-5-5") -> Agent[TriageDeps, TriageVerdict]`:
    - built with `deps_type=TriageDeps`, `output_type=TriageVerdict`, `instructions=INSTRUCTIONS` and `retries=2`;
    - tools are thin `@agent.tool` wrappers (RunContext first) around now, list_cameras, get_clip, get_frame, access_log, roster, procedures, ask_video and second_look;
    - each wrapper's docstring is copied from the matching `AgentTools` method;
    - the `second_look` wrapper returns `{"error": "Second-look limit (2) reached for this alert."}` on a third call, without calling the tools.
  - `task_message(candidate: dict, now: str, camera, open_alerts: list[dict]) -> str`:
    - includes candidate id, camera, zone, kind, first seen, detected at, now, the camera's doors and neighbours (`"none"` if empty), and one line per open alert on a neighbouring camera (`id, camera, kind, first seen, priority`), or `"No open alerts on neighbouring cameras."`;
    - never includes labels or `real`.
  - `evidence_from_trace(trace: list[dict]) -> list[str]`: unique paths, in order, from entries with `ok` True. It takes `result["path"]` for get_clip and get_frame, and `result["clip_path"]` for second_look.
  - `apply_rules(candidate: dict, out: TriageVerdict | None, failure: str | None, open_alerts: list[dict], neighbors: list[str], trace: list[dict]) -> tuple[dict, list[str]]`. Rules, in order:
    1. `failure` → escalate, medium, reason `f"Agent could not finish: {failure}. Passed to a person."`; rule name `"failure"`.
    2. kind in NEVER_DISMISS and not (escalate and high) → escalate, high; the agent's reason plus `" [Rule: person-down and fire alerts always go to a person, priority high.]"`; rule name `"safety rule"`.
    3. `linked` whose `linked_to` is not the id of an open alert on a camera in `neighbors` → escalate, keeping the priority; reason plus `" [Rule: link target is not an open alert on a neighbouring camera; sent to a person.]"`; rule name `"bad link"`.
    4. `linked_to` is `None` unless the verdict is `linked`.

    `evidence` comes from `evidence_from_trace`. The returned dict has exactly the five keys.
  - `class AgentTriage`:
    - `__init__(self, model="anthropic:claude-haiku-5-5", *, run_dir: Path | None = None, request_limit: int = 12, checker_factory: Callable[[str, str], object] | None = None)`. The default factory builds `VideoChecker(anthropic.Anthropic(), kind, tag=tag)`, creating the client once.
    - attributes `agent` and `stats: dict[str, dict]`.
    - `__call__(self, candidate, tools, open_alerts) -> dict`:
      1. set `tools.video_checker = factory(kind, f"triage:{candidate_id}")`;
      2. build `task_message`, with the camera from `tools.site.camera(...)` (not a tool call);
      3. inside `capture_run_messages()`, `agent.run_sync(task, deps=TriageDeps(tools), usage_limits=UsageLimits(request_limit=...))`. Any exception becomes `failure = f"{type(e).__name__}: {e}"[:300]`;
      4. sum `input_tokens` and `output_tokens` over the `ModelResponse` messages, so the count works on failure too;
      5. `log_call(provider="anthropic", model=<id without "anthropic:">, ..., tag=f"triage:{cid}:agent")`;
      6. `apply_rules`;
      7. store `stats[cid] = {"requests", "tool_calls", "tool_errors", "second_looks", "video_calls", "overrides", "cost_usd", "seconds"}`. `cost_usd` is the brain's cost plus `checker.cost_usd`;
      8. if `run_dir`, write `run_dir / f"{cid}.json"` with candidate, task, raw output (`model_dump()` or None), failure, final, overrides, trace, messages (`ModelMessagesTypeAdapter.dump_python(messages, mode="json")`) and stats;
      9. return the final dict.

- [ ] **Step 1: Write the failing tests.** Set `models.ALLOW_MODEL_REQUESTS = False`. The agent tests use real `AgentTools` on the `site_dir` fixture with the clock at site start +14 s, a `FakeChecker` factory, and `agent.override(model=FunctionModel(script))`.
  - `test_apply_rules_safety_override`: kind person_down, the agent says dismiss low. Expect escalate high, the rule text in the reason, and overrides `["safety rule"]`.
  - `test_apply_rules_bad_link_and_good_link`: `linked_to="A-009"` with no such alert gives escalate. `linked_to` of an open alert on a neighbour is kept.
  - `test_apply_rules_failure`: escalate medium, the reason starts with `"Agent could not finish"`, and the dict keys equal the five keys.
  - `test_evidence_from_trace_only_successful_paths`
  - `test_task_message_without_doors_or_neighbours`: contains `"none"`, `"No open alerts on neighbouring cameras."` and the now time, and does not contain `"real"`.
  - `test_agent_recovers_from_future_clip`. The script:
    1. `get_clip("CAM-B","02:00:00","02:00:25")` (refused);
    2. `get_clip("CAM-B","02:00:00","02:00:14")`;
    3. `ask_video(<path from the previous ToolReturnPart>, "what happens")`;
    4. the final output tool (name taken from `info.output_tools[0].name`) with escalate high.

    Expect the trace `ok` list to be `[False, True, True]`, `evidence == [clip path]`, `stats[cid]["tool_errors"] == 1`, and the verdict keys to be exactly the five.
  - `test_budget_hit_goes_to_a_person`: the script calls `now` forever and `request_limit=3`. Expect escalate medium and overrides `["failure"]`.
  - `test_second_look_limit`: the script calls `second_look` 3 times, then gives the output. Expect the third tool return to contain "limit" and the `FakeChecker` strong calls to equal 2.
  - `test_run_file_written`: `run_dir` holds `<cid>.json` with keys `final`, `trace`, `messages` and `stats`.
- [ ] **Step 2:** Run `pytest tests/test_triage_agent.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `agentlab/triage_agent.py`. Check names against the installed v2 docs: `UsageLimits`, `capture_run_messages`, `ModelMessagesTypeAdapter`, `FunctionModel`, `AgentInfo`.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.

### Task 5: `evaluate.py` switch, then run 1 (placeholder site)

**Files:**
- Modify: `evaluate.py`
- Test: `tests/test_triage_agent.py` (one more test)

**Interfaces:**
- Consumes: `AgentTriage` (Task 4).
- Produces:
  - `run(index, delay_s=10.0, triage_fn=None) -> dict`. `triage_fn=None` uses the stub, so the existing stub test still passes. Rows gain `cost_usd, requests, tool_calls, tool_errors, overrides` when `triage_fn` has `stats`. The summary gains `total_cost_usd` and `mean_cost_per_alert_usd`.
  - CLI options:
    - `--triage {stub,agent}` (default stub);
    - `--model` (default `anthropic:claude-haiku-5-5`).

    With `agent`, it loads `.env` with `load_dotenv(override=True)` and exits with `"Set ANTHROPIC_API_KEY in .env first."` if the key is missing. It writes run files to `runs/triage/<YYYYmmdd-HHMM>/`, prints the extra columns and prints that folder.

- [ ] **Step 1: Write the failing test** `test_evaluate_with_scripted_agent`. `AgentTriage` with a `FunctionModel` that gives the output "dismiss, low" at once, plus `FakeChecker`. `evaluate.run(index, 2, triage_fn=agent)` returns rows with `cost_usd`, and the summary has `total_cost_usd`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement the changes in `evaluate.py`.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.
- [ ] **Step 5: Run 1, done by the user** (estimate: under $0.30, 6 alerts):
  1. `python evaluate.py` (stub, free, as the baseline);
  2. `python evaluate.py --triage agent`.

  The user reports both tables and the run folder.
- [ ] **Step 6: Check run 1.** Read the run files. Expected:
  - every alert has tool calls in its trace;
  - every verdict has the five keys;
  - no `failure` override;
  - the total cost is printed.

  Any tool error must be followed by a corrected call. Summarise the run for the user and wait before Task 6.

### Task 6: Real-clip site and per-kind detector delay, then run 2

**Files:**
- Modify: `fakecctv/detector.py` (`poll` uses `delay_for`), `evaluate.py` (jump to `label.start + detector.delay_for(label.type)`). `run_replay.py` needs no change.
- Create: `scripts/make_real_site.py`, which writes `site.real.yaml`, `context/real/{access_log.csv, roster.csv, procedures.md}` and the two sequence clips.
- Test: `tests/test_real_site.py`, and a detector test in `tests/test_kit.py`

**Interfaces:**
- Produces:
  - `KIND_DELAYS = {"unattended_object": 30.0}`;
  - `OracleDetector(site, delay_s=10.0, already_fired=None, kind_delays=None)`, where `None` means `KIND_DELAYS`;
  - `OracleDetector.delay_for(kind) -> timedelta`;
  - `sequence_offsets(durations: list[float], gap_s: float = 10.0) -> list[float]`;
  - `make_sequence(paths: list[Path], out: Path, gap_s: float = 10.0) -> list[float]`. It re-encodes each clip followed by its last frame held for `gap_s` (ffmpeg `tpad=stop_mode=clone:stop_duration=10`), joins them and returns the offsets;
  - `site_config(caucafall_offsets: list[float], g421_offsets: list[float]) -> dict`.
- Values from the design and `labels.csv`. Site "Demo site (real clips)", start `2018-03-11T13:50:00`, `duration_s: 840`, fps 10, size [640, 360]. Labels are in seconds of the source file, copied from `labels.csv`; the `none` row is not used.

| Camera | Zone | Source | Placement | Doors / neighbours | Labels |
|---|---|---|---|---|---|
| CAM-01 | Drop-off loop | G336 mp4 | `align: meva_filename` | doors [Main gate]; neighbours [CAM-02] | 65–83 vehicle real; 161–201.9 vehicle real; 259–275 vehicle **real: false**, "weekend guard arriving; badge at Main gate 13:54:22" |
| CAM-02 | Car park | G328 mp4 | align | neighbours [CAM-01, CAM-03] | 88–115 vehicle real (same pickup as CAM-01); 144.4–150.8 vehicle real; 187.4–203.8 person real |
| CAM-03 | Hall | G330 mp4 | align | doors [Hall door]; neighbours [CAM-02] | 0–300 person **real: false**, "cleaning contractor on the roster for the hall" |
| CAM-04 | Warehouse aisle | CAUCAFall sequence: FallForward, Kneel, FallBackwards, Pickupobject, FallSitting, SitDown | at 13:56:00 | none | the 6 CAUCAFall rows, shifted by their offsets |
| CAM-05 | Waiting area | G331_160-230 | at 13:58:30 | none | 27–70 unattended_object real |
| CAM-06 | Lobby | G421 sequence: 8-70, then 36-100 | at 14:00:00 | none | the 2 look-alike rows, shifted |
| CAM-07 | Stairwell door | G326_60-110 | at 14:02:00 | doors [Stairwell door] | 25.4–31.7 person real |

- Context files:
  - `access_log.csv`: `13:41:05,Hall door,B-1107,Clean & Co staff,granted` and `13:54:22,Main gate,B-0412,Weekend guard,granted`.
  - `roster.csv`: `13:00,15:00,Clean & Co (2 staff),Cleaning contractor,Hall,Enter through the hall door` and `13:54,18:00,Weekend guard,Security,Drop-off loop; Main gate,Arrives by car at the start of the shift`.
  - `procedures.md`: the kit's procedures with rule 1 changed to "The site is closed all day on Sundays. A person or vehicle anywhere on site is expected only if the roster lists them for that zone, or a valid badge was used at a door in that zone in the previous 10 minutes." The other rules are unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_detector_waits_longer_for_unattended_objects`: on a two-label index, an unattended_object fires at start +30 s and a person at start +10 s;
  - `test_sequence_offsets`: `[6.5, 11.0, 7.0]` with gap 10 gives `[0.0, 16.5, 37.5]`;
  - `test_site_config_has_7_cameras_and_17_labels`: with fake offsets, the two `real: false` context look-alikes are on CAM-01 and CAM-03, and no label has type `none`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement the detector change, the `evaluate.py` jump using `delay_for`, and `scripts/make_real_site.py`. Its `main()` builds the sequences under `clips/sequences/` and writes the YAML and the context files.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.
- [ ] **Step 5: Build and run 2, done by the user** (estimate: under $1, 17 alerts):
  1. `python scripts/make_real_site.py`
  2. `python scripts/build_site.py site.real.yaml --out site_real`
  3. `python evaluate.py --index site_real/index.json` (stub baseline, free)
  4. `python evaluate.py --triage agent --index site_real/index.json`
- [ ] **Step 6: Check run 2 and log it in the project doc.** Report:
  - alerts reaching a person;
  - real events kept;
  - context look-alikes dismissed (CAM-01 grey car, CAM-03 hall);
  - the CAM-02 pickup linked to CAM-01;
  - the bag escalated;
  - cost per alert;
  - median time to alert.

  Note that the 3 fall look-alikes always reach a person under the safety rule, so they count against KPI 1 by design.
