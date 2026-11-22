# CCTV Playground

Test bench for the agent layer of *Security, Augmented*: an agent checks each CCTV alert before it reaches a guard, and a person approves every action. Recorded clips are replayed as a live site, and the agent sees footage only up to the replay clock's "now".

Member 4 (agent layer). Earlier name: fake-cctv. How the replay kit works: [docs/kit.md](docs/kit.md).

## Best setup so far (22 Nov 2026)

```
detector alert
 → triage agent (Claude Haiku 5.5): reads the badge log, roster, procedures and neighbouring cameras
 → video check: Haiku on 16 frames; Claude Sonnet 5.5 for objects, or when Haiku finds nothing
 → rules in code: a possible fall or fire always reaches a person; any failure escalates
 → a person approves, dismisses or reopens → report draft → audit log
```

On a 17-alert site built from real clips: 14 of 17 verdicts right in each of 4 runs, all 10 real events kept, no fall missed, median time to alert 22 to 25 s, about $0.01 per alert. A guard's decisions and two report drafts ran on the real model on 22 Nov.

## KPIs

Targets are placeholders until the group agrees them.

| # | KPI | Target | So far | Status |
|---|---|---|---|---|
| 1 | Alerts reaching a person | 70% fewer, 95% of real events kept | 23.5 to 29.4% fewer, 100% kept | This site can't show it (a) |
| 2 | Missed falls or fires | 0 | 0 falls missed | Met for falls; fire not tested |
| 3 | Time to alert | 30 s or less | median 22 to 25 s | Met for falls and people (b) |
| 4 | Time to evidence (search) | under 30 s, 80% in top 5 | not yet | Not started (Member 3) |
| 5 | Report effort | 70% less time | 2 drafts, 11 to 14 s each | Drafts work; not timed against writing by hand |
| 6 | Override rate | lower after feedback | the demo's 3 decisions only | Built, not measured |
| 7 | Cost | per camera per month | about $0.01 per alert | See (c) |

(a) 10 of the 17 alerts are real and the 3 fall look-alikes must reach a person, so 4 of 17 (23.5%) is the most any system can cut here. KPI 1 needs a site where most alerts are false.
(b) Includes the stand-in detector's delay: 10 s, or 30 s for objects. Vehicles take 25 to 42 s (the agent also checks the neighbouring camera), objects 46 to 62 s.
(c) The video check costs $0.002 per clip with Haiku and $0.033 with Sonnet. If 2% of footage is checked (an assumption), that is about $2.50 per camera per month, or $7 if 1 clip in 10 goes to Sonnet.

## What we tested

### 1. Video check: which model reads a clip best

18 labelled clips (MEVA public CCTV, CAUCAFall falls): vehicles and people on a closed site, falls and fall look-alikes, unattended objects. One JSON prompt (`agentlab/prompts/event_check_v2.md`). A real event counts as found if the type matches and it starts within 5 s of the label; a look-alike is right if no real alarm is raised. 3 runs per clip: 576 calls, $6.32.

| Setting | Correct | Falls (of 9) | Abandoned bag (of 3) | Seconds | Cost per clip |
|---|---|---|---|---|---|
| Claude Haiku 5.5, 16 frames | 89% | 9 | 0 | 6.8 | $0.002 |
| Claude Sonnet 5.5, 8 frames | 85% | 9 | 3 | 4.4 | $0.020 |
| Gemini 4 Hydrogen, thinking Low | 83% | 9 | 0 | 6.3 | $0.012 |
| Gemini 3.8 Flash, thinking Low | 78% | 9 | 0 | 4.3 | $0.003 |
| Gemini 3.5 Flash-Lite | 76% | 9 | 0 | 1.5 | $0.0014 |

- Every setting found every fall and raised no alarm on any fall look-alike.
- Only Sonnet finds the abandoned bag reliably (6 of 6, with 8 or 16 frames). Haiku found it once in 6 runs.
- Thinking High adds no accuracy over Low.
- One clip fails for every setting (a person leaving a car while others walk past): the prompt needs zones.

Tables: `results/step4_*.md`.

### 2. Who decides: one agent, a vote or a judge

Replaying the 486 logged answers, with no new calls: a majority vote scores 81%, Haiku alone 89%, and a cascade (Haiku, then Sonnet for objects or empty answers) 94% at $0.0057 per clip. The models share blind spots, so a vote removes the one right answer, and a judge that doesn't see the clip can't tell a right answer from a confident wrong one. We chose the cascade, with one agent deciding. Its rule was set after seeing these clips, so new clips must confirm it.

### 3. Triage agent on a real-clip site

7 cameras, 14 minutes of a Sunday when the site is closed. 17 alerts: 10 real (4 vehicles, 2 people, 3 falls, 1 abandoned bag) and 7 look-alikes (a guard's car and cleaners, explained by the badge log and roster; kneeling, picking something up, sitting down; 2 bags their owners keep). A stand-in detector fires on every labelled event without saying which is real. The baseline is the kit's fixed rules, which never look at video.

| | Rules, no video | Agent, 3 runs |
|---|---|---|
| Correct | 12 of 17 | 14 of 17 in every run |
| Real events kept | 10 of 10 | 10 of 10 |
| Falls missed | 0 | 0 |
| Look-alikes dismissed | 2 of 7 | 4 of 7 |
| Sent to a person | 12 | 13 |
| Median time to alert | 10 s | 22 to 24 s |
| Cost per alert | $0 | $0.011 |

- Every alert got the same verdict in all 3 runs.
- The 3 misses are the fall look-alikes: the video check named them, but the safety rule sends any possible fall to a person. 14 of 17 is the best possible under that rule.
- The agent's gain over the rules: it looked at the two bags their owners keep and dismissed them.
- The rules merge any alert from a neighbouring camera within 5 minutes; the agent merges only matching descriptions. In these 3 runs it merged none, so the red pickup seen on two cameras reached the guard twice.
- 1 of 51 reasons used a gender word. Reports already replace and flag these; triage reasons need the same check.

A 4th run on 22 Nov, after adding a procedure for unattended objects, gave the same 14 of 17. This time the agent linked the red pickup correctly, so 12 alerts reached a person. Median time to alert 25 s, $0.0097 per alert, no gender words.

Per alert, runs 1 to 3: `results/triage_real_site_3runs.json`.

### 4. Approval and reports (built and first run 22 Nov)

`review.py`: approve, dismiss with a reason, or reopen. Every decision goes into an audit log, and `--summary` gives the override rate. Dispatch is simulated. `report.py`: code writes the facts and the action, Haiku the text, and a checker flags unsupported times, cameras, gender words and filler. 260 tests pass offline.

First run on the real model, in run 4: 3 decisions, 2 simulated actions and 2 reports were logged in order. Both reports had every time and camera right and no flags, at about $0.0014 and 11 to 14 s each. Their open points still need cleaning: they list search windows and blank approval reasons as unknowns.

## Limits

- 18 clips and one 17-alert site: enough for direction, not for final KPI numbers.
- Daytime footage only; one real abandoned bag, no blocked exit, falls by one person.
- The detector is a stand-in that knows the labels.

## Next

- Compare agent brains (Sonnet, Gemini) and a single prompt without tools.
- Zones per camera, shared with the detector (Member 2).
- More object and blocked-exit clips (Member 1), and a site where most alerts are false (KPI 1).
- Investigator agent on the search index (Member 3, KPI 4); time reports and real reviews (KPIs 5 and 6).
- Clean up report open points; blur faces in report stills before any use on a real site.

## Run it

Python 3.14 and ffmpeg. The clips aren't in the repo (too large); their file names are in `labels.csv`. Without them, use the placeholder site in [docs/kit.md](docs/kit.md).

```
pip install -r requirements.txt -r requirements-agent.txt
pytest -q                                          # 260 tests, no API key needed
python scripts/make_real_site.py                   # needs the clips under clips/
python scripts/build_site.py site.real.yaml --out site_real
python evaluate.py --triage agent --index site_real/index.json   # paid, about $0.20; ANTHROPIC_API_KEY in .env
python review.py --run latest
python report.py --run latest --alert CAM-05-1     # paid, $0.01 or less
```

## Repo map

- `cctv_playground/`: the replay site and the agent's tools
- `agentlab/`: video check, triage agent, review, reports, scoring, cost log
- `scripts/`: site and test-clip builders, model comparison
- `context/`: badge logs, rosters, procedures
- `results/`: test results
- `docs/`: kit reference, designs, plans, the demo guide
