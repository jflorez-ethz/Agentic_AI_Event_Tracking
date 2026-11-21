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
