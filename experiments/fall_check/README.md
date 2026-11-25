# person_on_floor: the system describes, it does not interpret

**Status (branch `feature/fall-check`, offline only).** The design is integrated in `src/`:
- `person_fell` is replaced by `person_on_floor`;
- the code checks the facts with a neutral dense probe and follow-ups;
- every person on the floor becomes an alert for the guard;
- the facts appear in `report.md` and `report.html`, with a posture timeline.

No live run has been made. The frozen KPI tables are unchanged. Still to do after the check-in: freeze a new version, freeze the truth of new never-seen videos, then the A/B live test.

## Principle

Perception reports `person_on_floor` ("a person sitting or lying directly on the floor") and never "a fall". The code then measures:

| Fact | How |
|---|---|
| How the person reached the floor | measured seconds from the last `standing` frame to the first floor frame, with the postures in between. If not seen: "not observed", plus what was seen before. No words such as "sudden" or "gradual". |
| Posture on the floor | sitting / lying, with every change and its time |
| Time on the floor | first to last floor frame, measured; "at least" when the observation stops |
| Then | standing again at a given time (with the postures in between); still on the floor at the end of the video; last seen in a given posture; or follow-up stopped |

**"Facts verified"** means:
- on the floor for at least 2 s;
- moving at most 10 % of the image width;
- **and** either a standing frame observed before reaching the floor, **or** a follow-up still showing the person on the floor.

Otherwise the alert is **to review** and is never dismissed. Kneeling is never "on the floor": kneeling with no floor posture gives no alert and is only described in the chronology.

The rules (`src/security_augmented/floor_rules.json`, version 2) were written before any live run.

## Flow (`src/security_augmented/floor_check.py`)

1. `person_on_floor` candidates (and `insufficient_evidence` observations suspecting it) are taken out of the agents' input. **Verification never judges them.**
2. **Neutral probe** (prompt `floor-v1`), about 20 frames: 8 every 250 ms before the first cited floor frame, 12 every 420 ms after it. The question asks, for each image, the posture of every visible person (imposed vocabulary), an identifier and an approximate position. The candidate's description and the word "fall" are never sent.
3. **Follow-ups**: while the person is still on the floor at the end of a call, another call of 20 frames at 1 per second. Each follow-up links the person by position, within 15 % of the width.
4. Limits: at most 3 follow-ups per incident and 6 checks per video. Beyond that, the alert stays to review and the text says "follow-up stopped" or "budget used up".
5. Candidates within 2 s of an incident's observed span join it, so a person still on the floor in the next window does not create a duplicate alert.
6. The checks pass through the same HTTP media budget as the other requests: the CLI raises that limit by 6.
7. Output:
   - `analysis.floor_incidents`: the postures for each frame and the facts;
   - `person_on_floor` events (supported only if the facts are verified);
   - `review.floor_alerts` (verified or to review) and the rows of `alerts.csv`;
   - a `## Personnes au sol` section at the top of `report.md`;
   - a "People on the floor" section in `report.html`, with the facts, a posture strip and the key images.
8. **Archived runs**: `person_fell` remains readable (reports, review queue, KPI) but is no longer requested from Perception and no longer triggers a check.

## Labelled real cases (`labels.json`, `fixtures/`)

Postures were labelled by eye every 250 ms (every 500 ms over the getting-up spans); identity and position come from the CAVIAR XML. [build_fixtures.py](build_fixtures.py) runs the real `check()` against a simulated Perception that answers from these labels, and records every call: requested times and answers. `tests/test_floor_check.py` replays these transcripts without the videos. The expected facts were written before running; one was corrected afterwards and the correction is recorded (Wiggle: my expectation had left out the second sitting phase that the labels contain).

| Case | Facts measured | Status |
|---|---|---|
| Rest_FallOnFloor | sitting on the floor 00:27.56, then lying; standing → floor in 1.2 s via bending and kneeling; on the floor until 00:35.68 (8.1 s); standing at 00:38.68 | **verified** |
| Rest_WiggleOnFloor | standing → floor in 1.2 s; lying 20 s, sitting again at 00:48.64; standing at 00:51.64 | **verified** |
| Fight_OneManDown | standing → floor in 0.24 s; sitting then lying; 6.1 s on the floor; standing at 00:22.16 after kneeling and bending | **verified** |
| Rest_SlumpOnFloor, real slump | sitting on the floor 00:27.56–00:32.16 (4.6 s); reaching the floor not seen (before: kneeling); standing at 00:36.16 | to review: not corroborated |
| **Rest_SlumpOnFloor 2.5–3.0 s (former false confirmation)** | the close check shows the people standing throughout | **to review, never verified** |
| Rest_InChair | sitting on a seat | to review: seated |
| Browse1 (image-edge exit); LeftBag and PickedUp (4 bag stoops) | standing throughout / nobody on the floor | to review |

## Noise injected into the answers

| Test | Result |
|---|---|
| 1 or 2 wrong floor labels, any frame and any person, when nobody is down (exhaustive) | 0 verified |
| Up to 5 consecutive wrong "lying" labels on the person at the candidate | 0 verified |
| Random label noise at 5–20 % (tested), and 30–40 % (explored) | 0 verified |
| Real cases with one frame wrongly labelled bending, kneeling or seated | still verified |
| **Exploration: 6 to 20 consecutive wrong "lying" labels on a person who barely moves** (840 runs) | **343 wrongly verified (41 %)**. Blocked by the 2 s duration: 171; immobility: 116; the prudent rule (reaching the floor not seen and no follow-up): 105; time distance from the candidate: 60 |

**Residual risk.** A false "verified" needs Perception to be wrong in a **consistent** way for about 2 s about a person who barely moves (seated, slow, stretching), right after seeing them standing. Isolated or random errors never produce it.

## Known limits

- The slow slump stays "to review": the person was already crouched when the probe started, and the first follow-up already showed them kneeling. That is the price of the prudent rule.
- Follow-ups sample at 1 per second: standing-up times are accurate to about 1 s, and brief intermediate postures can be missed.
- When several people are on the floor at the same time and place, they are merged into one incident. Link-by-position may mix up two people side by side.
- One annotator. Nobody kneels for real in these clips (people stoop), so the kneeling rule is tested synthetically. The fixtures simulate a probe that answers correctly: only a live test will show whether Perception answers the posture question well.
- The KPI tables do not yet read `floor_alerts`; the KPI rules for the new version are part of step e.
