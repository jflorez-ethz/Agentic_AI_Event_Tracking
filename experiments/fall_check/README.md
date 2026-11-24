# Dense posture check for person_fell (offline prototype)

**Status.** The decision function, its rules, the labelled cases and the regression tests are done, offline. **Nothing is wired into the system yet**: `src/` is unchanged, so the live system can still confirm a fall the old way until the integration step below. No live run, no model call. The frozen KPI tables are untouched.

## Why

In the held-out Rest_SlumpOnFloor run, the report confirmed a fall at 2.52–3.04 s while a person was only walking. Verification never sees pixels: its calls are text only. For `person_fell` it could confirm from Perception's own two-frame claim, read back as text. It also ignored two targeted inspections that answered "walking, upright". In the 16 KPI runs, Perception claimed 8 falls; the 2 false ones rested on exactly 2 frames.

## Design (validated)

1. A **neutral probe**. For each `person_fell` candidate, the code itself asks Perception: "for each image, give the posture of each visible person (imposed vocabulary), a stable identifier (P1, P2…) and an approximate position". Perception never receives the original description or the word "fall".
2. **About 20 frames in one call**: 8 every 250 ms over the 2 s before the candidate's "after" frame, then 12 every 420 ms from it (about 4.6 s). See `probe_times`.
3. **The code decides** ([decision.py](decision.py), thresholds in [rules.json](rules.json), committed before any live run). The verdict is `supported` only if a person near the candidate in place and time shows:
   - a last `standing` frame, then a first on-ground frame (`sitting_on_floor` or `lying_on_floor`) at most **2.5 s** later, with any frames in between;
   - on the ground for at least **2 s**, with at most one isolated non-upright frame in the run; a `standing` frame ends the run;
   - movement of at most **10 % of the image width** during those 2 s.
4. **`kneeling` is never the ground** (people putting down or picking up a bag). Persistent kneeling stays "to review".
5. **Everything else gives `insufficient`**: a person upright throughout, seated, bending, already down when the probe starts, too slow, too short, moving, not near the candidate, or a malformed probe. The alert then goes to review; a fall is never dismissed.
6. Budget: 1 probe per candidate, at most 3 per video. This is the only path to `supported` for `person_fell`.
7. The posture sequence is kept in `analysis.json` and shown in `report.html` as a timeline (standing → on the ground, with times). This is part of the integration step.

## Labelled known cases

Identity and position come from the CAVIAR XML boxes (production reader). Posture was labelled by eye on frames every 250 ms ([labels.json](labels.json), sheets in [evidence/](evidence/)). [build_fixtures.py](build_fixtures.py) turns them into the probe answer a correct Perception would give ([fixtures/](fixtures/)). Expected outcomes were written before running the decision.

| Case | What the images show | Decision |
|---|---|---|
| Rest_FallOnFloor, 25.5–28.0 s | walks, collapses onto the knees, lies still | **confirmed** (upright 26.32 s → ground 27.56 s, moves 0.02) |
| Rest_WiggleOnFloor, 27.0–29.0 s | stumbles, goes down, wiggles in place | **confirmed** (27.28 → 28.52 s, moves 0.01) |
| Fight_OneManDown, 12.5–14.5 s | knocked down within about 0.3 s, lies until 19.4 s | **confirmed** (12.80 → 13.04 s, moves **0.089**) |
| **Rest_SlumpOnFloor, 2.5–3.0 s (the false confirmation)** | 3 people, all upright | **insufficient: upright throughout** |
| Rest_SlumpOnFloor, real slump at 26 s | crouches about 2 s, then sits on the floor | insufficient: already low when the probe starts; 2.76 s > 2.5 s |
| Rest_InChair, 19.5 s | sits in an armchair | insufficient: seated |
| Browse1, 7.5–8.5 s | walks out through the image edge | insufficient: upright throughout |
| LeftBag 1.5–5.5 s; LeftBag 37.5 s; PickedUp 20.5 s and 40 s | people stoop to put down or pick up a bag | insufficient: no ground |

## Noise injected into the probe answers (`test_decision.py`, 48 tests)

| Test | Result |
|---|---|
| 1 or 2 wrong "on the ground" labels anywhere, on any person, when nobody is down (exhaustive) | 0 false confirmations |
| Up to 5 consecutive wrong "lying" labels on the person at the candidate | 0 false confirmations |
| Random label noise at 5 %, 10 % and 20 % when nobody is down (fixed seed) | 0 false confirmations |
| True falls with one frame wrongly labelled bending, kneeling, seated or not visible | still confirmed, 20/20 positions |
| True falls with one frame wrongly labelled standing | may lose the confirmation (safe side: stays to review) |
| Exploration, not asserted: 6 or more consecutive wrong "lying" frames (about 2 s) on a person who barely moves | **can confirm** (slow walker, seated person, person stretching) |
| Exploration: random noise at 30 % when nobody is down | 1 false confirmation out of 2,800 |

## Known limits

- **Residual risk.** A false confirmation now needs Perception to mislabel the same, nearly still person as on the ground for about 2 s, right after an upright frame. The immobility check only protects against people who really move. A seated or slow person misread consistently is not caught.
- **Slow slumps are not confirmed** (the real Slump case): they stay "to review", never confirmed.
- **Fight is close to the movement threshold** (0.089 for 0.10). The box centre shifts with spread limbs. Perception's positions will be rougher than the XML boxes, so some real falls may be withheld. The threshold is not tuned here.
- **One annotator.** There is no real kneeling case in these clips (people stoop), so kneeling is covered by synthetic tests. The fixtures simulate a correct probe: whether Perception answers the posture question well is only known after a live test.
- **Anchor.** The probe needs the candidate's "after" frame and position. Today only Verification's transition provides a frame pair, and nothing provides a position. Integration must ask Perception for both, the after frame and a position, on `person_fell` candidates. They are used only to know where to look, never to decide.

## Next step (not done here)

Integration in `src/`, then a new frozen version:
- a neutral probe request with the imposed vocabulary;
- an automatic trigger and a dedicated budget;
- Verification validation so that `supported` for `person_fell` requires `decide(...) == supported`;
- `analysis.json` storage and the `report.html` timeline.

After that comes the paired live test (current version against the new one) on never-seen videos, with frozen truth and the criterion written before running:
1. no false confirmed fall;
2. every real fall reaches a person;
3. at least half of the real falls are confirmed;
4. added cost and time are reported.

Estimated cost: about $0.03–0.04 per probe at the launch rate, and 15–40 s per candidate.
