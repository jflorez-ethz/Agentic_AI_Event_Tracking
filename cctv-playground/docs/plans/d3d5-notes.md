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

## Task 2: actions and rule 7
- Built as planned. Regenerating changed only rule 7: `site.real.yaml` and both sequence files are
  byte-identical, so `site_real/` did not need a rebuild (it reads `context/real/` in place).
- Rule 7 changes what the agent reads through `procedures`, so the next run's numbers may differ from
  run 2's for a reason other than chance.

## Task 3: review
- **`decisions.jsonl` uses the kit's words**: `approved`, `dismissed by guard`, and the new `confirmed`
  and `reopened`. `AlertStore.open_alerts` and `app.py` read these; with the plan's `approve`, an
  approved alert left the open alerts. The audit keeps `approve/dismiss/confirm/reopen`.
- Write order is audit decision, then action, then `decisions.jsonl`. Action entries carry
  `simulated: true`.
- All `--decide` values are checked before any is applied (exit code 2 and nothing written). A decision
  refused later (already decided, wrong verdict) prints, the rest continue, and the exit code is 1.
- End of input and Ctrl-C leave the screen cleanly. Model text is shown on one line without control
  characters. `o` opens the first `.mp4`, not a still. A linked alert shows its target, and closed
  alerts show no proposed action.
- `reports` in the summary counts alerts with a report, so a second draft is not a second report.

## Task 4: facts and checker
- **Clip camera and start come from the file name**, not from what `get_clip` returns (follow-up 1).
- **`fact_times` comes from structured fields only**: alert times, clip windows, video events, context
  queries and rows, and the linked alert's first-seen time. The plan's "every HH:MM:SS above" took in
  the agent's free-text reason, so an invented time would have checked itself (follow-up 2).
- `check_report(texts, facts, timeline_times=())`: each timeline time must be a site time, otherwise
  "unknown" or "shortly after" passed with no flag.
- Times match without overlaps (`13:58` is not found inside `13:58:59`; `1:58 pm` gives one flag).
- Allowed cameras are every camera in the evidence plus the link target, as the spec says. The plan's
  narrower rule flagged neighbour clips the agent really used. Letter ids (`CAM-A`) work too.
- The word list gains the plurals and `young`.
- Extra fact keys: `cameras`, `linked_alert`, `evidence_missing`, and per event `camera`, `clip`, `offset_s`.
- An empty badge or roster lookup is a fact. A list that the trace cut at 5 rows says so.
- **Found while building (not in the agreed plan).** A replay of the checker over the 74 existing
  alerts showed an inverted badge window becoming a fact: in `20261121-165846-r3`, CAM-07-1 asked
  14:52:25 to 14:02:35 and got an empty list. Such lookups are now left out, and a roster question
  about a time after the alert adds no fact time. `AgentTools.access_log` still accepts an inverted
  window and answers "no entries"; that is unchanged.
- The same replay flagged the known bad times (13:49:40, 13:57:43, 13:56:55) and both "woman" reasons.

## Task 5: report
- **"Action taken" is written by code** (choice B; departs from spec step 4). An approval is a simulated
  dispatch, and a model given the action text would report it as done. `action_taken` is not in
  `ReportDraft`; without an approval the section says "No action approved."
- **Gender and age nouns in the writer's input are neutralised** (choice C). Two runs of 21 Nov say
  "a woman" for the demo's bag alert, in the reason and in the video answer. Pronouns are left to the
  checker, which still runs on the draft.
- The writer gets no real-clock times and no file paths, and is told that free text is no source of times.
- The still uses only the alert's own camera. A seek past the last frame takes the last frame. An
  unreadable clip gives no still.
- Links are `../evidence/...` (reports are one folder down). Model text is rendered as one plain line,
  so it cannot add a heading, an image or a table cell.
- A second report is `A-012-2.md`; an earlier one is never overwritten.
- `retries=2` and `UsageLimits(request_limit=3)`. A failed draft is still logged with `log_call`.
- `report.py` refuses before it loads `.env`, so a refusal needs no key.
- Small refactor of Task 3's `decided_line(entry, first_seen)`, so the report can reuse it.

## Task 6: walkthrough
- Commands use `.venv/bin/python`. The walkthrough says what to do if the bag is not escalated.
- **Dry run beyond the plan** (free): no existing run folder has `alerts.jsonl`, so run
  `20261121-165846-r3` was replayed through a scripted brain, fake checker and scripted writer on
  `site_real`, with network and `.env` blocked and all output outside `runs/`. Decisions, refusals, both
  reports, the summary and both stills worked. The screen was also tried in a real terminal.
- The fall's still shows the person going down, not yet lying: the spec takes the start of the event.

## Not verified, and open
- **The report writer has never called the real API.** Wording, flag rate, cost and seconds are
  unknown until the first paid report. An offline build of the request shows `tool_choice: auto`
  (Pydantic AI does not force the output tool while Haiku's thinking is on, although the profile
  supports forcing), so a plain-text reply costs one of the two retries. This corrects the remark on
  forced tool choice in the session plan.
- A reopened alert has no next step in the spec: it cannot be approved and gets a report only with `--force`.
- The checker tests times, cameras and a word list. It cannot judge whether a description is true, or
  catch appearance and ethnicity in general. The still frames show people as recorded.
- A fact time supports any sentence: the checker does not tie a time to the event it is written next to.
- One reviewer at a time: there is no file lock.
- The spec's example `A-011=approve` is the bend look-alike in detection order; the bag is A-012.
