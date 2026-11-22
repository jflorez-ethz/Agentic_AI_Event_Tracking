# D3/D5 build notes: where the code differs from the plan

Session 4, 22 Nov 2026. Changes to `2026-11-21-d3-d5-plan.md`, agreed in plan mode (checked against the
code, the 74 alerts in the five existing run folders, and pydantic-ai-slim 2.71.0 with the v2 docs).
Built on branch `d3d5`; not merged, not pushed.

## Follow-ups for step 5

Recorded only; no code was changed for them in this session.

1. **`AgentTools.get_clip` should return the clip's real (clamped) start and end.** It returns the
   requested times, while `Recorder.cut_clip` clamps them to the camera's recording. In all four
   real-site runs CAM-03-1 asked for 13:49:40 and got a 10 s clip starting at 13:50:00. The agent adds
   the video model's "seconds from the start of the clip" to the time it asked for, so its site times
   there can be 20 s off. `second_look` already returns the clamped times.
2. **Check the agent's own reasons for times after detection.** This happened in 3 of 74 alerts, where
   no footage existed yet:

   | Run folder | Alert | Detected | Time in the reason |
   |---|---|---|---|
   | `20261121-165846-r1` | CAM-04-2 | 13:57:31 | 13:57:43 |
   | `20261121-165846-r2` | CAM-04-2 | 13:57:31 | 13:57:43 |
   | `20261121-165846-r3` | CAM-04-1 | 13:56:46 | 13:56:55 |

   The count covers HH:MM:SS times only. A check must allow roster end times such as 15:00, which
   are legitimately later than detection.

## Task 1: keeping the run
- **`keep_run` is opt-in** on `evaluate.run` and `evaluate.run_repeats`, and `main()` sets it for
  `--triage agent`. The plan kept every run with a `run_dir`, which broke two existing tests that
  assert a run folder's exact contents (`test_evaluate_with_scripted_agent`, `test_repeats_aggregate`).
  `test_main_keeps_every_agent_run` covers the wiring, with and without `--repeats`.
- A folder that already has `alerts.jsonl` is refused before any model call.
- `latest` is the newest `alerts.jsonl` by modification time. A review changes a folder's own time, and
  names misorder `-r10` and `-r2`.
- `resolve_run_dir` creates nothing (`AlertStore` creates missing folders, so it must run first), and
  has its own messages for a folder that does not exist and for no kept run at all.
- The run files (`<candidate id>.json`) still hold the temporary evidence paths; `alerts.jsonl` and
  the audit hold the copies.
- `tests/d3d5_helpers.py` is shared by the new test modules. Its autouse `no_env` fixture fails any
  test that reaches `load_dotenv`.
