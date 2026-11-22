# D3 and D5 design: review step, audit log and incident reports

21 Nov 2026, Member 4. Status: approved 21 Nov. Approach A for D3.

## Why
The triage agent (step 5) checks each alert, but its verdict is only a recommendation. D3 puts a person in charge:
- every escalated alert waits for a guard's decision;
- nothing is "done" without approval;
- everything is logged.

D5 then turns an approved alert into an incident report drafted from the evidence.

Together with step 5 they complete the loop the pitch promises:

```
alert ─▶ checked with evidence ─▶ a person decides ─▶ report drafted ─▶ all of it logged
```

This is the concrete demo for the 25 Nov check-in. It covers KPI 6 (override rate) and starts KPI 5 (report effort).

## Goals
- **Keep each agent run reviewable.** `evaluate.py --triage agent` keeps its alerts and evidence clips in the run folder, so a run can be reviewed and reported on at any time after it finishes.
- **A review step in the terminal:**
  - **Pending alerts:** the guard approves the proposed action, or dismisses the alert with a required reason.
  - **Alerts the agent closed itself** (dismissed or linked): the guard can confirm them or reopen them with a reason.
- **Proposed actions** come from the site procedures, in code. Approving one logs it as a simulated dispatch. The system never contacts anyone by itself.
- **An append-only audit log per run:** one entry per agent verdict, per human decision, per approved action and per report. A summary prints the counts and the **override rate**.
- **An incident report for an approved alert:**
  - facts collected in code;
  - text written by Haiku from those facts only;
  - a checker that flags anything the facts don't support;
  - markdown in a site template, with a still frame at the event time.

## Not in this step
- Approval inside the agent (approach B: Pydantic AI pausing a tool call until a person approves). It's a later upgrade once D3 works.
- The Streamlit inbox, the investigator agent (D4), site memory (D6; the audit log already stores the dismissal reasons D6 will read), real dispatch or notifications, and PDF export.
- Measuring "approved without major edits" (KPI 5's second half), which needs people editing real drafts, and the manual report baseline (task B5).

## Must never happen
- An action logged without a person's approval.
- A person's dismissal or reopening without a reason.
- A report time, camera or event that isn't in the evidence, presented as fact without a flag.
- A report that describes a person's gender, age or appearance beyond clothing needed to tell events apart (the procedures say: do not identify people).
- An audit entry changed or deleted after it was written.

## How it works

### Keeping the run (change to `evaluate.py`, agent runs only)
- The run's alert store lives in the run folder: `alerts.jsonl` and `decisions.jsonl` (the kit's existing format, so the old screen could still read them).
- The evidence clips and frames of each alert are copied to `evidence/<alert id>/`. The alert's `evidence` paths point at the copies, relative to the run folder.
- One audit entry of type `verdict` is written per alert. It holds:
  - the alert id, candidate, camera, zone and type;
  - the verdict, priority, reason, evidence and link;
  - the model, cost, requests, tool calls, tool errors and rule overrides;
  - the name of the run file.
- With `--repeats`, each repeat's folder holds its own set.

### Proposed actions (code, mirrors the procedures)

| Event type | Proposed action |
|---|---|
| person_down, fire | Send the nearest guard to {zone} now. The guard decides whether to call emergency services. |
| after_hours_person, after_hours_vehicle | The guard on duty checks {zone} and decides on dispatch. The system never contacts the police. |
| unattended_object | A guard checks the object in {zone} in person. It is not moved before it is checked. |
| blocked_exit | The supervisor has the exit in {zone} cleared before the next shift. |
| anything else | The guard on duty reviews the clip. |

The site procedures gain a rule for unattended objects: "alert the control room, priority medium; a guard checks it in person".

### Review (`review.py`)
- `python review.py --run <run folder>` shows the pending escalations, highest priority first, then by time. For each one it shows:
  - the camera, zone, type and first-seen time;
  - the priority and the agent's reason;
  - the evidence files and the proposed action.
- **Keys:**
  - `a` approve the action;
  - `d` dismiss, with a required reason;
  - `o` open the first evidence clip in the default player;
  - `s` skip;
  - `q` quit.
- `--closed` walks through the alerts the agent closed itself, with `c` to confirm and `r` to reopen (reason required).
- **Scripted use** for the demo and tests, for example `--decide A-011=approve --decide A-009="dismiss:Kneeling, not a fall"`.
- **Each decision is written twice:**
  - to the kit's `decisions.jsonl`;
  - as an audit entry of type `decision`, with the decision, reason, reviewer (default "Guard on duty"), wall-clock time, the alert's site time, the agent's verdict, and whether the person agreed with the agent.
- An approval also adds an `action` entry with the proposed action text.
- **Agreement:**
  - approving an escalation, or confirming a closed alert, is agreement;
  - dismissing an escalation, or reopening a closed alert, is an override.
- `--summary` prints the counts:
  - alerts, escalated and decided;
  - approved, dismissed, confirmed and reopened;
  - actions logged and reports written;
  - the **override rate** = overrides / decisions.

### Reports (`report.py`, `agentlab/report_writer.py`)
`python report.py --run <run folder> --alert A-011` works only on an approved alert, unless `--force` is given.

1. **Facts, collected in code from the run:**
   - the site, alert id, camera, zone, type, first seen, detected and created times;
   - the agent's verdict, priority and reason;
   - the video-check events, converted to site times using the clip's start;
   - the badge-log and roster rows the agent read;
   - any link;
   - the evidence files;
   - the guard's decision and approved action.

   Each fact carries the time it refers to.
2. **Draft:** Haiku, through Pydantic AI with a typed output, writes a title, a summary of 2 to 4 sentences, a timeline (site time and what happened), the context checked, the action taken and any open points. Its instructions say: only these facts, times only from the facts, and "a person", never gender or age.
3. **Check, in code:**
   - every time in the draft must match a fact within 2 s;
   - every camera id must be one of the facts;
   - gender and age words are flagged (the bag alert's reason in run 2 says "a woman", copied from the video check).

   Flags are listed at the bottom of the report; the report is still written.
4. **Render:**
   - the header table comes from the facts, not from the model;
   - the sections come from the draft;
   - evidence is linked by relative path, with one still frame taken from the evidence clip at the main event time;
   - the footer reads "Draft: needs sign-off by the reviewer".

   Output goes to `reports/<alert id>.md` in the run folder, plus an audit entry of type `report` (model, cost, seconds, flags).

The template is `context/report_template.md`, a generic site incident form. Cost is about $0.002 to $0.01 per report.

## The demo for 25 Nov
1. Run the agent on the real-clip site.
2. Review in the terminal:
   - approve the abandoned bag and one fall;
   - dismiss the kneel with "Kneeling, not a fall";
   - reopen nothing.
3. Draft the bag and the fall reports.
4. Print the audit summary, with the override rate.

A short walkthrough with the exact commands goes in `docs/demo/`.

## Cost
Review is free. Reports cost about $0.01 each. The demo needs one agent run (about $0.16) plus a few reports, under $0.25 in total. Tests make no paid calls.

## Details decided 21 Nov

1. **The review screen** is plain terminal text, one alert at a time. The priority word is coloured (red high, yellow medium, dim low) when the terminal supports colour. The phone-and-laptop interface is a separate, later task (E1, the alert inbox); it gets designed on its own, with mock-ups first. Layout:

```
A-012  HIGH  unattended_object  CAM-05 Waiting area  first seen 13:58:57
Agent: escalate. A black bag was set down beside the rear-right bench and left there ...
Evidence: evidence/CAM-05-1/CAM-05_20180311-135837_135927.mp4
Proposed action: A guard checks the object in Waiting area in person. It is not moved before it is checked.
[a] approve   [d] dismiss   [o] open clip   [s] skip   [q] quit
```

2. **The report template** is a standard incident form, in this order:
   - a header table with incident id, site, camera and zone, event type, first seen (site time), priority, agent verdict, and the decision and who made it;
   - Summary;
   - Timeline;
   - Evidence;
   - Context checked;
   - Action taken;
   - Open points;
   - Checks (the checker's result);
   - a sign-off line: "Reviewed by: ____  Date: ____".
3. **The still frame** is taken at the start of the first event of the alert's own type in the video check, preferring a real event over a look-alike. If the check found none, it is taken at the alert's first-seen time. Either way it comes from the saved evidence clip.
4. **The time of a human decision.** The replay clock is gone once the run ends, so a decision has no site time of its own. It records the real clock time when the guard decided, plus the alert's own site time, and is shown as "decided 17:42 (real time) for the alert first seen 13:58:57 (site time)". Alerts can be named by their alert id (A-012) or their camera event id (CAM-05-1).

## Ideas for later (out of scope now, 21 Nov)

| Idea | Builds on |
|---|---|
| An interface that works on a phone and a laptop: the alert inbox, the review, the reports | E1, E2 and E4: a responsive web app, designed with mock-ups first |
| Live labels on the camera view, with a threat level for each detection | C1 (the real detector with zones), plus the interface |
| Asking "what is happening?" through WhatsApp or Telegram | D4 (the investigator agent) behind a messaging bot. Only text summaries, with no identification; check Swiss and EU data-protection rules for these channels. |
| Talking to it by voice, like a voice assistant | D4, plus speech-to-text and text-to-speech |
