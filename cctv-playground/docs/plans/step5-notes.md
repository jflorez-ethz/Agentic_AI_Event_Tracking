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
