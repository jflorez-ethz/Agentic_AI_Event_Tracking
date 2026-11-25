# person_on_floor: the system measures and signals doubt, the guard decides

**Status (main, offline only).**
- `person_fell` is replaced by `person_on_floor`.
- The code checks the facts with a neutral dense close check (probe) and follow-ups.
- **Since rules v3/v4, the code no longer decides "facts verified".** It measures the facts and shows objective **doubt signals**. Every person on the floor goes to the guard. A case with at least one signal is marked **Look closely** and comes first.
- A text-only model call may add one sentence labelled **System's assessment**. It is an unverified opinion and changes nothing.

No live run has been made with this version. The frozen KPI tables are unchanged.

## Important: one signal was added after seeing the results

The v3 rules (thresholds and criterion) were frozen before any computation (commit `0907be1`). The offline computation on the 11 labelled cases and the 2 demo runs (commit `6dbd8f8`, [doubt_offline.py](doubt_offline.py)) **did not meet the criterion**: 7/9 known false alerts were marked. The two unmarked ones were suspicions where the close check saw nobody on the floor.

The **`no_floor_seen`** signal ("the close check shows nobody on the floor") was then added in v4 (commit `2bf6392`). **It was written after seeing the results on these 15 cases, so these cases cannot validate it. It must be confirmed on never-seen videos**, with the truth frozen before the run.

## Principle

Perception reports `person_on_floor` ("a person sitting or lying directly on the floor") and never "a fall". The code then measures:

| Fact | How |
|---|---|
| How the person reached the floor | measured seconds from the last `standing` frame to the first floor frame, with the postures in between. If not seen: "not observed", plus what was seen before. No words such as "sudden" or "gradual". |
| Posture on the floor | sitting / lying, with every change and its time |
| Time on the floor | first to last floor frame, measured; "at least" when the observation stops |
| Then | standing again at a given time (with the postures in between); still on the floor at the end of the video; last seen in a given posture; or follow-up stopped |

## Doubt signals (`floor_rules.json` v4, `doubt_signals`)

The thresholds only decide whether a signal is **shown**. There is no score and no decision.

| Signal | Shown when |
|---|---|
| Disagreement | the first look reported someone on the floor and the close check shows nobody on the floor; or the first look only suspected it and the close check shows someone on the floor |
| Nobody on the floor (v4) | the close check shows nobody on the floor |
| Few floor frames | fewer than 4 close-check frames on the floor |
| Short time on the floor | less than 2 s, then seen off the floor |
| Reaching the floor not seen | not seen standing before being on the floor |
| Small person | median box height on the floor frames under 30 px |
| Image edge | box within 8 px of the border on a floor frame |
| Moving on the floor | more than 10 % of the image width in the first 2 s on the floor |
| Seat nearby | "seat next to the person" on a floor frame, or a `sitting_on_seat` answer |
| Changing posture | on the floor, then not, then on the floor again |
| Uncertain identity | two or more people near the last known position in a follow-up frame |
| No close check | the close check failed or the video's budget was used up |

Each signal is shown with its measured value, for example "Small in the image (19 px tall)" or "A seat next to the person (seen at 00:03.80)". "No doubt signal measured" is written with "this does not mean it is true".

## System's assessment

- One text-only call per incident (prompt `floor-assess-v1`, thinking LOW), only when a close check ran.
- **Input:** the timed postures and the measured facts. Never the first look's description, never the doubt signals.
- **Code check before display:** one sentence, at most 240 characters. No health, intent, identity, age or gender words. "Fall" (or "collapse", "trip"…) only together with "consistent with", "may", "could"…
- A rejected or failed assessment shows "No system assessment". It never changes the status or the order.

## Flow (`src/security_augmented/floor_check.py`)

1. `person_on_floor` candidates (and `insufficient_evidence` observations suspecting it) are taken out of the agents' input. **Verification never judges them.** Whether the first look reported or only suspected is recorded (`first_look`).
2. **Neutral close check** (prompt `floor-v2`), about 20 frames: 8 every 250 ms before the first cited floor frame, 12 every 420 ms after it. For each image, each visible person gets:
   - a posture from the imposed vocabulary;
   - an identifier;
   - an approximate centre and **box size**;
   - **"seat next to the person"** (true / false).

   The candidate's description and the word "fall" are never sent.
3. **Follow-ups**: while the person is still on the floor, another call of 20 frames at 1 per second, linked by position (within 15 % of the width). At most 3 per incident and 6 checks per video.
4. Candidates within 2 s of a time someone was seen on the floor, at the reported moment, join that incident.
5. Output:
   - `analysis.floor_incidents`: postures, facts, `seen`, `first_look`, `doubt_signals`, `status` (`look_closely` / `no_doubt_signal`), `assessment`;
   - `person_on_floor` events, **never "supported"**;
   - `review.floor_alerts` (Look closely first) and the rows of `alerts.csv`;
   - a section at the top of `report.md` and of `report.html`. Each card shows the measured facts, the System's assessment, the doubt signals, the posture strip, and the images before / during / after.
6. Questions about the floor and `experiments/kpi/kpi.py` read the floor alerts directly (`floor:look_closely` / `floor:no_doubt_signal`).
7. **Archived runs** (stored before v3) are read with their signals computed on load. The old prompt asked no box and no seat, so those signals can only come from `sitting_on_seat` answers.

## Results on the labelled cases and the demo runs

[build_fixtures.py](build_fixtures.py) runs the real `check()` against a simulated close check that answers from the posture labels, the XML boxes, and the seat truth written in `labels.json` before computing. The demo runs are real Gemini answers. The expected facts were converted mechanically from v2 statuses into what the close check saw (`seen`), as recorded in `labels.json`.

| Case | Source | Seen | Doubt signals | Card |
|---|---|---|---|---|
| Rest_FallOnFloor | simulated | on the floor 8.1 s, standing again | — | no doubt signal |
| Rest_WiggleOnFloor | simulated | on the floor 21 s | — | no doubt signal |
| Fight_OneManDown | simulated | on the floor 6.1 s | — | no doubt signal |
| Rest_SlumpOnFloor, real slump | simulated | on the floor 4.6 s | reaching the floor not seen | **Look closely** |
| Rest_SlumpOnFloor 2.5–3.0 s (former false confirmation) | simulated | standing throughout | disagreement, nobody on the floor | **Look closely** |
| Rest_InChair | simulated | on a seat | disagreement, nobody on the floor, seat | **Look closely** |
| Browse1 (suspicion, image-edge exit) | simulated | standing throughout | nobody on the floor (v4) | **Look closely** |
| LeftBag and PickedUp (4 bag stoops) | simulated | nobody on the floor | disagreement, nobody on the floor | **Look closely** |
| Demo Rest_FallOnFloor 00:11 (suspicion) | live | kneeling | nobody on the floor (v4) | **Look closely** |
| Demo Rest_FallOnFloor 00:27 | live | on the floor 9.2 s | — | no doubt signal |
| Demo Rest_SlumpOnFloor 00:04 | live | on a seat | disagreement, nobody on the floor, seat | **Look closely** |
| Demo Rest_SlumpOnFloor 00:25 | live | on the floor 6.7 s | — | no doubt signal |

- Criterion (re-checked, not validated): **9/9 known false alerts marked**, **0 of the 3 clear real falls** marked.
- Cards marked: 10 of 15. Real people on the floor marked: 1 of 6.
- The "small person" signal never fired on a real person on the floor. Lying people measure 34 to 70 px (median of their boxes), above the 30 px threshold.

## Noise injected into the answers

In these tests, follow-ups answer the truth: when nobody is on the floor, they show the people standing.

| Test | Result |
|---|---|
| 1 or 2 wrong floor labels, any frame and any person, when nobody is down (exhaustive) | always Look closely |
| Up to 5 consecutive wrong "lying" labels on the person at the candidate | always Look closely |
| Random label noise at 5–20 % when nobody is down | always Look closely |
| Real cases with one frame wrongly labelled bending, kneeling or seated | still on the floor. The time on the floor stays within 1 s, except when the wrong label is on the last close-check frame (no follow-up is then asked). It can add "changing posture" or "seat". |
| **6 to 20 consecutive wrong "lying" labels when nobody is down** (840 runs, [residual_risk.py](residual_risk.py)) | **220 with no doubt signal (26 %)**, whether the follow-up shows the truth, repeats the error or fails. Before (v2): 343 wrongly "facts verified" (41 %). |

**Residual risk.** A card with no doubt signal when nobody is on the floor needs Perception to be wrong in a consistent way for about 2 s or more. The person must also be large enough, away from the image edge and from any seat, still, and seen standing just before. A failed follow-up is not a doubt signal in the frozen rules.

## Known limits

- `no_floor_seen` was added after seeing these cases: it must be confirmed on never-seen videos.
- One wrong label on the last close-check frame stops the follow-up, so the time on the floor is shorter.
- The box and seat answers are new (prompt `floor-v2`). Only a live test will show whether Perception answers them well. Here they are simulated from the XML and from my seat labels.
- Follow-ups sample at 1 per second: standing-up times are accurate to about 1 s.
- When several people are on the floor at the same time and place, they are merged into one incident. Link-by-position may mix up two people side by side.
- One annotator. Nobody kneels for real in these clips (people stoop), so the kneeling case is tested synthetically.
- Objects (`object_placed`, `object_removed`) still get "facts verified" from Verification. The same principle is planned for them (PROJECT_STATE.md).
