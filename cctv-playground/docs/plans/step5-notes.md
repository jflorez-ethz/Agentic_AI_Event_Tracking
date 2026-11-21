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
