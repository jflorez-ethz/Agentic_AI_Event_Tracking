# CAVIAR reference audit

The comparison used decoded frame indices and XML object IDs. The corrected reader takes integer center and size exclusively from the direct object/box element. Person and bag role handling is preserved. Counts below are changed person boxes divided by all person boxes, first at original cadence and then at the pilot stride of five. Across the available XMLs, zero bag boxes changed.

| Clip | Role | Full cadence | Scored cadence |
|---|---|---:|---:|
| Walk2 | Tuning | 0/2914 | 0/584 |
| LeftBag | Tuning | 0/1879 | 0/376 |
| LeftBag_PickedUp | Initial test | 0/1062 | 0/213 |
| LeftBag_AtChair | Initial test | 0/1468 | 0/294 |
| LeftBox | Initial test | 0/1084 | 0/217 |
| Rest_FallOnFloor | Initial test | 0/1196 | 0/241 |
| Meet_WalkTogether1 | Initial test | 0/847 | 0/169 |
| TwoEnterShop1front | Initial test | 2792/3241 | 559/648 |
| Meet_WalkSplit | Initial test | 1656/1788 | 332/358 |
| Meet_WalkTogether2 | Held out | 1477/1484 | 297/298 |
| Walk1 | Held out | 0/1559 | 0/312 |
| LeftBag_BehindChair | Held out | 0/1523 | 0/305 |
| Walk3 | Nano ×3 test | 0/1039 | 0/207 |
| Meet_Split_3rdGuy | Nano ×3 test | 641/1733 | 128/348 |
| Browse_WhileWaiting1 | Nano ×3 test | 0/1306 | 0/262 |

Only XMLs that annotate `<body>` landmarks (head, shoulders, hands, feet) are affected: the old regular expression let the last landmark's `xc`/`yc` overwrite the box center. LeftBag_BehindChair (`lbbcgt.xml`) and LeftBag_PickedUp (`lbpugt.xml`) have no landmarks.

## Measurements that used the old reader

The production parser (`src/security_augmented/annotations.py`) and everything built on it (`experiments/mvp_evaluation`, the CAVIAR references and the MVP tests) read the direct `<box>` element and were never affected. Three experimental readers shared the regular expression:

| Measurement | Reader | Affected clips used | Status |
|---|---|---|---|
| Person tracking, original seven test clips | `person_tracking/pilot.py` (now fixed) | TwoEnterShop1front, Meet_WalkSplit | **Changed**: Nano 0.352 → 0.501, no stitching 0.334 → 0.488, oracle 0.869 → 0.942. Five-clip subset, tuning, detector comparison and owner checks unchanged. |
| "XML offset" on TwoEnterShop1front (≈20 px) and Meet_WalkSplit ((−12, −7) px) | same | same | **Withdrawn**: reader artifact, not an annotation error. |
| Person tracking, three held-out clips | same | Meet_WalkTogether2 | **Changed**: Meet2 0.017 → 0.314 (oracle 0.689 → 0.986); pooled 0.277 → 0.385 (oracle 0.880 → 0.976). |
| Stationary objects, trial 1 "XML (perfect)" person filter | `stationary_objects/pilot.py` | TwoEnterShop1front, Meet_WalkSplit | **Unchanged**, verified by rerun with corrected boxes ([check](../stationary_objects/xml_reader_check.py)): 0 and 6 false alarms at 25 fps, 0 and 4 at 5 fps. Object boxes were never affected. |
| Tracking pilot (C1) | `tracking_pilot/pilot.py` | none (LeftBag_PickedUp only) | Unchanged. |
| `meet2_audit/legacy_reader.py` | archive | Meet_WalkTogether2 | Kept on purpose to reproduce the superseded numbers. |

The original XML and MPEG hashes for Meet_WalkTogether2 match the manifest. At frame 195 (PTS 7.9597 s), XML ID 1 has center (154,41) and size 30×23. The old reader used (165,44) from the last annotated foot. Best raw detection IoU changes from 0.432 to 0.892. [Decoded frame and stage overlays](meet2_audit/frame_195.png).

All six source hashes matched the original manifest. Walk1 and LeftBag_BehindChair detections were regenerated at the frozen Nano ×2 settings. Meet_WalkTogether2 used the prior replay cache. The historical reader reproduced the saved frame counts, per-track summaries and Nano metrics on every clip. The historical manifest contains track endpoint timestamps but no per-frame timestamp array. The corrected oracle rerun uses corrected boxes as tracker inputs.

At confidence 0.1 and IoU 0.5, one-to-one matching maximized the number of valid pairs and then their overlap. Raw detections covered 446 of 915 reference observations with 6,184 unmatched predictions. ByteTrack lost 144 matched observations and gained zero. Stitching preserved all 302 remaining matches and raised identity credit from 235 to 245. Static filtering removed 179 boxes and preserved all spatial matches. The corrected tracking scores and lack of independent event-attribution evidence support keeping tracking outside the MVP. [Per-stage counts, identities and exhibit coordinates](heldout_audit/counts.json) · [Reproduction script](heldout_audit/audit.py).

## Frozen results

| Clip or pool | Nano default | Default oracle | Nano ×2 | ×2 oracle |
|---|---:|---:|---:|---:|
| Walk2 | 0.591 | 0.970 | 0.609 | 0.963 |
| LeftBag | 0.528 | 0.995 | 0.628 | 0.995 |
| LeftBag_PickedUp | 0.479 | 0.966 | 0.940 | 0.964 |
| LeftBag_AtChair | 0.529 | 0.970 | 0.696 | 0.970 |
| LeftBox | 0.766 | 0.991 | 0.767 | 0.991 |
| Rest_FallOnFloor | 0.662 | 0.990 | 0.844 | 0.990 |
| TwoEnterShop1front | 0.433 | 0.926 | 0.479 | 0.937 |
| Meet_WalkSplit | 0.262 | 0.859 | 0.252 | 0.858 |
| Meet_WalkTogether1 | 0.498 | 0.970 | 0.498 | 0.970 |
| Initial five | 0.581 | 0.977 | 0.770 | 0.977 |
| Original seven | 0.501 | 0.942 | 0.616 | 0.945 |
| Meet_WalkTogether2 (held out) | — | — | 0.314 | 0.986 |
| Walk1 (held out) | — | — | 0.300 | 0.982 |
| LeftBag_BehindChair (held out) | — | — | 0.531 | 0.959 |
| All three held out | — | — | 0.385 | 0.976 |

On the original seven, the historical default-resolution scores for Nano, no stitching and oracle were 0.352, 0.334 and 0.869. Their corrected scores are 0.501, 0.488 and 0.942. Nano ×2 keeps all four owner checks, but its seven-clip pooled score of 0.616 fails the 0.700 threshold. Its five-clip score of 0.770 is unchanged. The tuning grids and YOLO comparisons used only unaffected references. The historical held-out Nano and oracle totals (0.277 and 0.880) are superseded. Meet_WalkTogether2 previously scored 0.017 and 0.689 respectively.
