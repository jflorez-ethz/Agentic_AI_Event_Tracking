# Step 5 design: the triage agent (task D2, experiment 3)

21 Nov 2026, Member 4. Status: approved 21 Nov, with run 2 on the real-clip site after run 1.

## Why
The kit's triage (`fakecctv/triage_stub.py`) is a set of fixed rules. It never looks at the video. Step 5 replaces it with an agent that checks each detector alert the way an operator would. The agent watches the clip, checks who was expected, looks at neighbouring cameras, and sends a person only what needs one, with a reason and evidence. This is the core of KPI 1 (alerts reaching a person), KPI 2 (no missed person-down), KPI 3 (time to alert) and KPI 7 (cost). It follows approach A from the 21 Nov decision: one agent decides, and a stronger model takes a second look only when needed.

## Goals
- Drop-in replacement. `triage(candidate, tools, open_alerts)` returns `{verdict, priority, reason, evidence, linked_to}`, the same as the stub, so `evaluate.py` only needs a switch.
- The agent touches the site only through the kit's `AgentTools`: now, list_cameras, get_clip, get_frame, access_log, roster, procedures and ask_video. It also gets one new tool, second_look.
- `ask_video` works. It runs Claude Haiku 5.5 on 16 frames with prompt `event_check_v2`, as measured in experiment 2.
- Every run can be read afterwards. Each run keeps:
  - the tool calls, with their arguments and results;
  - the agent's messages;
  - the final verdict and any rule that changed it;
  - tokens, cost and seconds for each alert.
- The step plan's checks pass:
  - the trace shows tool calls;
  - a request for footage after "now" gets the error, and the agent carries on;
  - the verdict always has the right format.

## Not in this step
- Comparing agent brains (Sonnet, Gemini 3.8 Flash) and the single-prompt baseline. That is experiment 3, once this works.
- The approval step (D3), the investigator agent (D4), reports (D5), site memory (D6), search, the Streamlit screen and `run_replay.py`.
- The real detector (C1). `OracleDetector` stays.

## Must never happen
- A person-down or fire alert that is not sent to a person.
- A verdict without a reason.
- A description that identifies a person.
- Footage or log entries read after "now".
- A silent failure. If the agent breaks, the alert goes to a person.

## How it works, for each alert
1. **Task message, built in code.** It holds:
   - the alert: camera, zone, event type, first seen and detected at;
   - the site time now;
   - the open alerts on neighbouring cameras (id, camera, type, first seen).
2. **The agent decides which tools to call.** The brain is Claude Haiku 5.5 in Pydantic AI, with a typed output. Its instructions give the usual route:
   1. cut a clip from 20 s before first seen to now;
   2. call ask_video on it;
   3. check the access log for the zone's doors over the last 10 minutes, and the roster at first seen;
   4. check whether an open alert on a neighbouring camera covers the same event;
   5. give a verdict.

   The agent may leave this route. For example, it can cut a neighbouring camera's clip, or ask a narrower question.
3. **`ask_video(clip_path, question)`** takes 16 frames spread evenly over the clip. A typical clip is about 30 s long, so the frames are about 2 s apart. It sends them with the v2 prompt, plus the agent's question as a "focus" line, and returns the event list.

   A rule in code sends the same clip to Sonnet 5.5 on 16 frames in three cases:
   - the alert is an unattended object;
   - Haiku's answer contains an unattended_object event;
   - Haiku's answer has no event of the alert's type.

   The result says which model answered and why.
4. **`second_look(camera_id, around, question)`** is the agent's own choice, for when the evidence conflicts. For example, the video shows no one but nobody badged in. It cuts the window from 15 s before to 15 s after the given time, ending no later than now, and runs Sonnet on 16 frames. It is allowed at most twice per alert, and it is not used if ask_video already escalated to Sonnet.
5. **Rules applied in code after the agent's typed verdict:**
   - A person-down or fire alert is always escalated, with priority high, whatever the agent said. The reason notes the override.
   - `linked_to` must name an open alert on a neighbouring camera. Otherwise the verdict becomes escalate.
   - `evidence` lists the clips and frames the tools actually produced, taken from the trace, never paths the model typed.
   - If anything goes wrong (an error, invalid output after the retries, or the budget is used up), the verdict is escalate, priority medium, with the reason "agent could not finish: ...".
6. **Budget per alert:** at most 12 model requests and 2 second looks.

The brain does not see images itself in this step. `get_frame` returns a path, which is used as evidence.

## Code
- `agentlab/triage_agent.py`: the agent, its instructions, the output model, the `triage()` wrapper with the rules above, and the run file.
- `agentlab/video_check.py`: ask_video and second_look on frames. It reuses `event_check.py` (frame extraction, the Claude call, parsing). The wrapper builds one checker per alert, so the escalation rule knows the alert's type.
- `fakecctv/tools.py`: `ask_video` calls the checker when one is set and keeps today's "not connected" error otherwise. A new `second_look` method cuts its clip through the recorder, so the clock rule and the trace still apply.
- `evaluate.py`:
  - `--triage stub|agent`, with stub as the default;
  - alerts are handled one at a time, because the open alerts depend on order;
  - new columns: cost, model requests, tool calls, tool errors, overridden;
  - one run file per alert in `runs/triage/<stamp>/`.
- Cost logging: every model call goes through `agentlab/usage.py`, both the brain (from Pydantic AI's usage count) and every video check.
- Tests that cost nothing, using Pydantic AI's scripted test models:
  - the agent calls tools;
  - a request for a future clip gets the error and the run still returns a valid verdict;
  - the person-down override;
  - the fallback on failure;
  - `evidence` comes from the trace.
- Dependency: pydantic-ai 2.x (2.71.0 released 18 Nov 2026). Version 2 changed some APIs, so the code is checked against the V2 docs when it is written.

## Runs and cost
- **Run 1, the kit's placeholder site.** It has 6 alerts and its clips are coloured blocks, so this tests the plumbing. ask_video will mostly find nothing and escalate to Sonnet. Estimate: under $0.30.
- **Run 2, a site built from our real clips (approved, after run 1).** These are the first meaningful verdicts. Estimate: under $1. Site described below.

## Run 2's site
The placeholder clips can show that the agent works, but not that it decides well. `site.real.yaml` builds a Sunday site from the clips we already have, about 18 alerts:

| Camera | Zone | Clip |
|---|---|---|
| CAM-01 | Drop-off loop | MEVA G336 |
| CAM-02 | Car park, neighbour of CAM-01 | MEVA G328: the red pickup tests linking across cameras |
| CAM-03 | Hall | MEVA G330 |
| CAM-04 | Warehouse aisle | The 6 CAUCAFall clips joined into one file |
| CAM-05 | Waiting area | MEVA G331: the abandoned bag |
| CAM-06 | Lobby | MEVA G421: the attended set-downs |
| CAM-07 | Stairwell door | MEVA G326 |

A small access log and roster would make two of the after-hours events expected, for example the grey car as the guard arriving with a badge. The agent then has to dismiss them from context. In the site file these two are marked "real: false". It would be an early version of task B4, and Member 1 can replace it. The detector would wait 30 s before raising an unattended object, because a bag only counts as left behind after a while.

## Left to the builder
The exact wording of the instructions, the frame width (1024 px, as in the experiments), the format of the run file and how open alerts are summarised.
