# Demo for the 25 Nov check-in: a person decides, a report is drafted, all of it is logged

```
alert ─▶ checked with evidence ─▶ a person decides ─▶ report drafted ─▶ all of it logged
```

Run every command from the `fake-cctv` folder. Steps 1 and 3 are paid (Claude API, key in `.env`), under
$0.25 together. Steps 2 and 4 are free. Run step 1 before the meeting: it takes about 5 minutes.

The expected lines come from a free dry run on 22 Nov that replayed run `20261121-165846-r3` through a
scripted model. A new agent run can differ, see "If the run differs". The reports' wording and cost
have not yet been tried on the real model.

## 1. Run the agent on the real-clip site (paid, $0.17-0.21)

```
caffeinate -i .venv/bin/python evaluate.py --triage agent --index site_real/index.json
```
Expect: a 17-row table, about 13 alerts sent to a person, 0 missed critical events, and a `run files:` folder.

`--run latest` below is this run: the kept run whose alerts were written last. Pass that folder instead
if you run the agent again before the meeting.

## 2. Review (free)

On screen, one alert at a time:

```
.venv/bin/python review.py --run latest
```
Expect: high priority first, each with the agent's reason, evidence and proposed action; `o` plays the clip.

Use `s` to skip to the alerts below. The bag is medium priority, so it comes after the high ones.

| Alert | What it is | Key |
|---|---|---|
| A-008 CAM-04 13:56:36 | a fall | `a` |
| A-009 CAM-04 13:57:21 | a kneel | `d`, then `Kneeling, not a fall` |
| A-012 CAM-05 13:58:57 | the abandoned bag | `a` |

Or the same three decisions, scripted:

```
.venv/bin/python review.py --run latest --decide CAM-05-1=approve --decide CAM-04-1=approve --decide "CAM-04-2=dismiss:Kneeling, not a fall"
```
Expect: three lines like `A-012 approve: decided 17:42 (real time) for the alert first seen 13:58:57 (site time)`.

Running it again is safe: each prints `A-012 was already decided (approve).` and adds nothing to the log.

To show the alerts the agent closed itself (reopen nothing; `q` quits):

```
.venv/bin/python review.py --run latest --closed
```
Expect: about 4 dismissed alerts, the first being the cleaners in the Hall, with `[c] confirm   [r] reopen`.

## 3. Draft the two reports (paid, $0.01 or less each)

```
.venv/bin/python report.py --run latest --alert CAM-05-1
```
Expect: `report: .../reports/A-012.md`, the checks (no flags, or each flag), then seconds and cost.

```
.venv/bin/python report.py --run latest --alert CAM-04-1
```
Expect: `report: .../reports/A-008.md`, with the same lines.

Open both in a markdown preview (the still frame shows there). Point out three things:

- the header and "Action taken" come from the log, not from the model;
- "Checks" lists anything the evidence does not support, so a flag there is the checker working;
- the report waits for a signature.

A dismissed alert gets no report. This costs nothing and needs no key:

```
.venv/bin/python report.py --run latest --alert CAM-04-2
```
Expect: `A-009 is not approved; approve it in review.py first, or use --force.`

## 4. The audit summary (free)

```
.venv/bin/python review.py --run latest --summary
```
Expect: 17 alerts, 3 decisions, 2 approved, 1 dismissed, 2 actions, 2 reports, override rate 33.3%.

The log itself is `audit.jsonl` in the run folder, one line per verdict, decision, action and report.

## If the run differs

- **The agent did not escalate the bag.** Approving it is refused. Use
  `.venv/bin/python review.py --run latest --decide "CAM-05-1=reopen:Bag left unattended"` to show an
  override, and report the fall only. A reopened alert cannot be approved yet (an open spec decision).
- **The falls and the kneel** always reach a person at high priority (safety rule in code).
- **A report has flags.** Show them. Running `report.py` again costs another call and writes `A-012-2.md`.
- **A question about "Camera 03" in the fall still.** That label is burned into the CAUCAFall source
  clip; on this site it is CAM-04.

## What this shows

- **Step 1, KPI 1 (alerts reaching a person):** `alerts reduction pct`. The three fall look-alikes count
  against it by design, because of the safety rule.
- **Step 1, KPI 2 (no missed person-down):** `missed critical events` and `real events kept pct`.
- **Step 1, KPI 3 (time to alert):** `median time to alert s`, with the agent's own seconds included.
- **Steps 2 and 4, KPI 6 (override rate):** overrides over decisions. Three hand-picked decisions show
  that it is measured; 33.3% is not a result.
- **Step 3, KPI 5 (report effort), started:** seconds to a checked draft. "Approved without major edits"
  and the manual baseline (task B5) are not measured yet.
- **Steps 1 and 3, KPI 7 (cost):** cost per alert and per report, logged in `runs/usage.jsonl`.

Approvals are simulated dispatches. The system contacts no one.
