# Step 5 build notes: where the code differs from the plan

21 Nov 2026. Changes made while building Tasks 1–5 of `2026-11-21-step5-triage-agent-plan.md`.
Each one follows the spec's intent where the plan conflicted with the code or the Pydantic AI v2
docs (pydantic.dev/docs/ai, checked against the installed pydantic-ai-slim 2.71.0).

## Environment
- pydantic-ai v2 needs Python 3.11+ (the plan said ≥3.10). The venv is Python 3.14.6.

## Task 1
- `test_claude_check_without_focus_has_no_focus_line` passed before the change (it checks for
  an absence), so Step 2 showed 2 failures, not 3.

## Task 2
- **Any error in a frame check becomes a `ValueError`**, not only client errors. `claude_check`
  also runs ffmpeg (`extract_frames`), whose `CalledProcessError` is not a `ValueError`;
  `AgentTools._call` would not catch it, the agent run would abort and the alert would fall
  back to escalate-medium. Now the agent sees `{"error": "video model unavailable: ..."}` and
  can decide from the context, as the spec intends. An unreadable clip (ffprobe fails) gives
  `"Could not read the clip at ..."`.
- **Bug found and fixed in `extract_frames`** (new test
  `test_extract_frames_past_the_last_frame_takes_the_last_one`). Frames are taken at the
  middle of n slices, so the last sample is at `duration * (n - 0.5) / n`. On a short or
  low-fps clip (16 frames, 4 s at 5 fps: sample 3.88 s, last frame 3.8 s) ffmpeg writes no
  image and fails. The agent can ask for short windows, so it would hit this. When the seek
  gives no frame, the last frame of the clip is used instead (`-sseof -1 -update 1`).
- **`VideoChecker.ask_escalated`** (new attribute): True once an ask_video answer came from
  Sonnet. Task 4 uses it to refuse second_look after that, as the spec says (see Task 4).
- `VideoChecker.calls` counts successful model calls; `cost_usd` adds each call's
  `usage["cost_usd"]`.

## Task 3
- **`tests/conftest.py` also holds an autouse fixture** (`keep_logs_out_of_runs`) that points
  `agentlab.usage.USAGE_LOG` and `agentlab.event_check.FRAMES_DIR` at `tmp_path` for every
  test. Without it the Task 4 and 5 tests (which log the brain's tokens through `log_call`)
  would append fake rows to the real `runs/usage.jsonl`, which `total_spend` reads. The
  `site_dir` fixture moved unchanged.
- **`second_look` reports the clip's real start.** The window start is clamped to the camera's
  first frame (`max(around - 15 s, cam.start)`), the same clamp the recorder applies, so the
  reported `start` matches the clip and the checker's "seconds from the start of the clip"
  can be mapped back to site time.
- The `ask_video` docstring no longer says "not wired yet" (the agent's tool description is
  copied from it), and `second_look` has its own docstring for the same reason.
- Extra test `test_second_look_without_checker_is_an_error`. `test_ask_video_without_checker_is_an_error`
  and `test_unparseable_time_is_an_error` passed before the change (existing behaviour, kept
  as guards).

## Task 4
Checked on the installed 2.71.0: `Agent(..., defer_model_check=..., retries=...)`,
`@agent.tool(sequential=...)`, `UsageLimits(request_limit=...)`, `capture_run_messages`,
`ModelMessagesTypeAdapter.dump_python(msgs, mode="json")`, `FunctionModel`/`AgentInfo`
(`function_tools`, `output_tools`, `allow_text_output`), `ModelResponse.usage.input_tokens` /
`output_tokens`. The default output tool is `final_result`; the tests still read it from
`info.output_tools[0].name`.

- **`build_agent` passes `defer_model_check=True`.** In v2 a model string is resolved at
  construction, and the Anthropic provider then needs `ANTHROPIC_API_KEY` (`UserError`
  otherwise). Deferring lets the tests build the agent and override the model with no key.
  The default video client is also created on first use, not in `AgentTriage.__init__`, and
  uses the stripped `ANTHROPIC_API_KEY`.
- **All tools run one at a time.** Pydantic AI runs sync tools in worker threads and may run
  several tool calls from one response concurrently; `AgentTools.trace`, the recorder's ffmpeg
  outputs and the video checker's counters are not thread-safe. Every wrapper is registered
  with `sequential=True` and holds `deps.lock`, which is a `threading.RLock` (re-entrant, so no
  wrapper can deadlock by taking it twice in the same thread).
- **No sampling settings.** No `model_settings` (temperature, top_p, top_k) are set anywhere;
  claude-haiku-5-5 rejects non-default values. Checked in pydantic-ai's Anthropic model: these
  are only sent when set. Guarded by `test_no_sampling_settings`.
- **Rules chain** (plan rule 1 then rule 2): after a failure (escalate medium), the safety rule
  still applies, so a failed person-down or fire check goes out at high priority with overrides
  `["failure", "safety rule"]`. The spec's "must never happen" list asks for this.
- **second_look is refused after ask_video used Sonnet**, in code, not only in the
  instructions (spec: "it is not used if ask_video already escalated to Sonnet"). The wrapper
  reads `video_checker.ask_escalated`. Refusals (limit or Sonnet) are added to the trace as
  `ok: False` so they show in the run file and in `tool_errors`. The second-look count only
  goes up when the look succeeds, so a refused future time does not use up the budget.
- `pydantic_ai.BANNER_ENABLED = False`: v2 prints a first-run banner to stdout, which would land
  in the middle of `evaluate.py`'s table.
- `AgentTriage.last_messages` keeps the last run's messages (the tests read tool returns from it).
  The brain's `log_call` row also stores `requests` as an extra field.
- Extra tests: `test_apply_rules_linked_to_cleared_unless_linked`,
  `test_task_message_lists_open_alerts_on_neighbours`, `test_no_sampling_settings`,
  `test_second_look_refused_after_ask_video_used_sonnet`.

## Task 5
- **The agent is imported only for `--triage agent`** (inside `make_agent`), so the stub path and
  its existing test never import pydantic-ai.
- **`.env` is loaded by path** (`load_dotenv(ROOT / ".env", override=True)`), so the command works
  from any folder. The key is stripped and written back to `os.environ`, because the Pydantic AI
  provider reads the variable as it is and `scripts/compare_models.py` already had to strip it.
- `--model` without a provider prefix exits with a message (v2 raises `UserError` for an
  unprefixed model name, which would otherwise turn every alert into a "could not finish").
- The table printing moved into `print_table(result, run_dir)`, so it can be checked offline; the
  stub table is unchanged. It was checked with a scripted brain and a fake video checker on the
  placeholder site (no model requests, cost log redirected).
- Totals come from the rows (`total_cost_usd`, `mean_cost_per_alert_usd` over alerts with a
  cost), not from `AgentTriage.stats`, which keeps entries across runs.
- Not changed: run files list evidence paths in `evaluate.py`'s temporary work folder
  (`fakecctv-eval-*` under the system temp directory), as the stub's evidence always did.

Stopped after Task 5 Step 4. Task 5 Step 5 (run 1) is for the user; Task 6 is not started.

---

# Session 2 (21 Nov 2026): review fixes and Task 6

## Fix: time to alert includes the agent's seconds (KPI 3)
- `evaluate.run` jumps the in-memory replay clock to each detection time, and the clock stands
  still while the agent works. So with a triage function that has `stats`, each row's
  `time_to_alert_s` is now `(created - label start) + stats[cid]["seconds"]`, and the row gets a
  separate `triage_s` (the agent's own seconds). `median_time_to_alert_s` uses the corrected value.
  The stub path is unchanged (no `triage_s`, same table).
- The agent table has an `agent s` column after `cost $`.
- Test: `test_time_to_alert_counts_the_agents_seconds` (a stub wrapper whose stats say 42 s; no
  timing noise).

## Fix: run folders named to the second
- Run folders are now `runs/triage/<YYYYmmdd-HHMMSS>` (were `<YYYYmmdd-HHMM>`), so two runs started
  in the same minute no longer write into one folder. The name comes from a new helper
  `evaluate.run_dir_for(now)`, so the test checks it without going through `make_agent` (which
  loads `.env`). Run 1's folder `20261121-1535` keeps its old name.
- Test: `test_run_folders_are_named_to_the_second`.

## Task 6
Built as planned, with these changes (agreed in plan mode, 21 Nov):

- **Detector order.** `OracleDetector` has `KIND_DELAYS = {"unattended_object": 30.0}`,
  `kind_delays=None` (→ `KIND_DELAYS`) and `delay_for(kind)`; `self.delay` stays as the default
  delay, so `run_replay.py` works unchanged. `poll` now returns candidates in detection order
  (detected_at, then start), not start order.
- **`evaluate.run` replays in detection order** and jumps to `label.start + delay_for(type)`.
  `ReplayClock.jump` can go backwards, and an unattended object that starts first fires last;
  in start order a person label due earlier would be triaged and timestamped at the object's
  later time (too-long time to alert, footage past its real detection time). The real site's
  timings do not hit this, but it would be a silent KPI error. Test:
  `test_evaluate_creates_each_alert_at_its_detection_time` (hand-written index, no footage).
- **Sequences get a 30 s lead-in as well as the 10 s tail.** Each clip in a sequence is its
  first frame held 30 s, the clip, then its last frame held 10 s. The CAUCAFall clips are
  5.9–11 s long; with only the tail, the agent's usual first clip (first seen −20 s) for the
  Kneel, Pickup and SitDown look-alikes would have contained the previous real fall and its
  lying-still hold. The tail stays: each fall alert fires 1–7 s after its clip ends, so the
  fallen person is still on screen at "now". Signatures:
  `sequence_offsets(durations, gap_s=10.0, lead_s=0.0)`, `make_sequence(paths, out, gap_s=10.0,
  lead_s=0.0)`; `main()` passes `lead_s=30`. The plan's test values still hold at `lead_s=0`.
  **An offset is where that clip's own first frame lands** (segment start + lead-in), and the
  labels are shifted by it. Result: CAUCAFall clips start at [30, 79.5, 130.45, 176.7, 222.55,
  271.65] s, G421 at [30, 132] s; CAM-04 is on site 13:56:00–14:00:51, CAM-06 14:00:00–14:03:26.
- **`make_sequence` normalises in one ffmpeg call**: every part is scaled/padded to the first
  clip's size, set to its frame rate, padded with `tpad` (`start_mode=clone` and
  `stop_mode=clone`), then joined with the `concat` filter; no audio. It probes the output and
  stops if the length differs from the expected total by more than 1.5 frames, since the label
  offsets assume it. Test: `test_make_sequence_matches_its_offsets` (two lavfi clips of
  different sizes).
- **Labels are read from `labels.csv`** (by file, `none` rows skipped) instead of retyped; the
  two context look-alikes (G336 at 259 s, G330 at 0 s) are set to `real: false` with the plan's
  notes through `CONTEXT_LOOKALIKES`. A used file with no labels stops the script.
- **Procedures rule 2** reads "Unexpected activity while the site is closed" (was "after hours",
  which may read as not applying at 13:50 on a closed Sunday). The script copies the kit's
  procedures, replaces rules 1 and 2, and stops if "22:00", "06:00", "night" or "after hours"
  is left. 11 Mar 2018 is a Sunday.
- **Committed:** the script, the tests, and its outputs `site.real.yaml` and `context/real/`
  (small text, so the reviewer can read the site). `clips/sequences/` and `site_real/` stay
  gitignored.
- Extra tests: `test_sequence_offsets_with_lead_in`, `test_make_sequence_matches_its_offsets`,
  `test_evaluate_creates_each_alert_at_its_detection_time`.
- **Spot check** (frames from `site_real/cams/CAM-04.mp4`): at the Kneel window start (13:57:01.5)
  the frame is the Kneel clip's first frame (a person standing, no fall); at Kneel + 1 s
  (13:57:22.5) the person is kneeling; at FallForward + 2 s (13:56:38) the person is lying on
  the floor.
- Not changed: `AlertStore` stores `created` to the whole second, so labels starting on a
  half second show a time to alert of 9.5 s instead of 10 s (stub median 9.95 s on the real site).
- Run 1's dismissed intruders on the placeholder site (coloured rectangles, so the video model
  said "not a person" and the agent took no second look) are not addressed; run 2 measures the
  agent as it is.

---

# Session 3 (21 Nov 2026): fixes after run 2, and `--repeats`

Run 2 (`runs/triage/20261121-160152/`) prompted these. Agreed in plan mode, with three additions from
the user (the INSTRUCTIONS opening, the neighbour-clip window, the privacy sentence).

## Fix: site context (public opening, CAM-04 zone)
- Run 2 escalated both CAM-06 look-alikes (unattended objects in the Lobby) at high priority because the
  agent saw people in a "closed" lobby. `ROSTER` in `scripts/make_real_site.py` gets the row
  `13:00,15:00,Visitors (public opening),Visitors,Lobby; Waiting area,...` (the user's text; no commas in
  the note, so no CSV quoting). CAM-05 and CAM-06 only carry `unattended_object` labels, so no label
  changes; the note says an unattended object there still needs an alert.
- CAM-04's zone is "Staff room" (was "Warehouse aisle"): the CAUCAFall clips show a small room with a
  desk, a TV and a chair.
- INSTRUCTIONS open with "The site is closed, except for the people and zones the roster lists."
  (was "The site is closed."), so the opening does not contradict the roster.
- The script's docstring mentions the public opening. Nothing else on the site changed: regenerated
  `site.real.yaml` and `context/real/` differ only in the zone and the roster row; `site_real/` rebuilt.
- Tests: `test_roster_has_the_public_opening`, `test_instructions_open_with_the_roster_exception`, and the
  CAM-04 zone in `test_site_config_has_7_cameras_and_17_labels`.

## Fix: linking compares descriptions; reasons never mention gender, age or ethnicity
- Run 2 linked CAM-02-2 (a white car, 13:52:24) to A-002 (CAM-01's red pickup): the task showed only
  the neighbouring alert's id, type, first-seen time and priority. `task_message` now adds
  `reason: "<first 200 characters>"` to each neighbour line (`NEIGHBOUR_REASON_CHARS = 200`, newlines
  folded to spaces, `...` when cut, so each alert stays on one line).
- INSTRUCTIONS: route step 4 says to compare the neighbour's reason with what was seen; the `linked`
  bullet says to link only when the reason describes the same kind of vehicle or person (type and colour
  match) and the timing fits, and to escalate instead when it differs or is unclear. Instructions only;
  `apply_rules` is unchanged (the code still checks only that the target is an open neighbour alert).
- Privacy (user addition): run 2's bag alert reason said "a woman in a blue jacket", copied from the
  video check. The last bullet now reads: never identify people or describe their face; "The reason never
  mentions gender, age or ethnicity, even when ask_video's answer does; write "a person"", with the blue
  jacket example. Note: the reasons now shown in the task come from earlier alerts, so a slip there would
  also reach the next alert's task.
- The opening sentence from the previous fix is rewrapped (same words).
- Tests: `test_task_message_shows_the_start_of_each_neighbour_reason`,
  `test_instructions_link_only_on_matching_description`,
  `test_instructions_reason_never_mentions_gender_age_or_ethnicity`.

## Fix: short clips (first clip, neighbour clips, 60 s limit)
- Run 2's CAM-04-6 cut a 90 s first clip (13:59:13-14:00:43), and neighbour clips of 53 s and 105 s;
  16 frames over 90-105 s miss short events.
- `VideoChecker(max_clip_s=60.0)` (was 120). This covers ask_video and second_look; second_look's
  window is at most 30 s, so it is not affected. A longer clip gets the existing error ("Clip is 70 s;
  frame checks need 60 s or less. Ask for a shorter window.") and the agent can retry.
- `AgentTools.ask_video` docstring (the agent's tool description): "Clips must be 60 s or shorter; the
  usual window (20 s before first seen to now) is 30 s, or 50 s for unattended objects."
- INSTRUCTIONS: step 1 says the first clip runs from 20 s before first seen to now, and that more context
  comes from a neighbouring camera, not a longer clip; "ask_video takes clips of 60 s or less"; and (user
  addition) "A neighbouring camera's clip is 60 s or less, centred on the neighbouring alert's first-seen
  time". Added by me: "(with no alert there, on this alert's first-seen time), and never past now", since
  a neighbour may have no open alert.
- **Changed existing test:** `test_missing_clip_and_long_clip_raise_value_error` asserted the 120 s
  message; it now uses a 70 s clip and expects "need 60 s or less".
- New tests: `test_fifty_second_clip_is_accepted` (passed before the change too; kept as a guard for the
  unattended-object window), `test_ask_video_description_gives_the_60_s_limit`,
  `test_instructions_keep_clips_short`.

## Video column: what the video model said about the alert
- New `first_video_answer(trace, camera_id, kind)` in `agentlab/triage_agent.py`. Clip paths are matched
  to cameras through the successful `get_clip` steps (`args.camera_id` → `result.path`). It takes the
  first **successful** ask_video on a clip of the alert's own camera and looks at that answer's events
  of the alert's type: any real → `"real"`, only look-alikes → `"look-alike"`, none of that type →
  `"none"`. No such ask_video → `None`. Errored ask_video calls, ask_video on neighbour clips, and
  second_look are not counted. When ask_video escalated to Sonnet, this is the Sonnet answer (the one
  the agent saw).
- `AgentTriage.stats[cid]["video"]` holds it, so it is in each run file's `stats` too (no run-file
  parsing). `evaluate.STAT_COLUMNS` gets `"video"`; the agent table has a `video` column before
  `cost $` (`-` for None). The stub table is unchanged.
- `FakeChecker` in the tests takes `events=` (default `[]`, so older tests are unchanged).
- Tests: `test_first_video_answer`, `test_stats_record_the_first_video_answer`,
  `test_agent_table_has_a_video_column`; `test_evaluate_with_scripted_agent` checks the `video` key.
