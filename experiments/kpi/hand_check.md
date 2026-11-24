# Hand check, written before the first KPI computation

The values come from grep or awk on the XML, the run's own `frame_pts`, and direct reading of `analysis.json`. No KPI code was used. `kpi.py` must reproduce them exactly (`test_kpi.py`).

## Rest_FallOnFloor, run fall_live.Q2OExt

- XML: object 2 has context "drop down" from frame 480 (19.44 s, still walking). Its situation changes from moving to inactive at frame 655, **26.44 s**. That is the fall instant.
- Run: `person_fell` supported over 25.52–28.04 s. review: supported_security 1, needs_review 0.
- Expected: 1 critical XML event, found, 0 missed; 1 human-facing item, 1 real; report produced.

## LeftBag_PickedUp, run LeftBag_PickedUp_live.kocJd7

- XML (same rule as stationary_objects): bag placed at **20.36 s**, removed at **40.88 s**.
- Run: `object_placed` supported over 18.52–19.52 s, which is 0.84 s from 20.36, inside ±2 s. There is no `object_removed` at any phase and no review alert.
- Expected: 2 critical XML events, 1 found (placement), 1 missed (removal, cause `never_seen`); 1 human-facing item, 1 real.
