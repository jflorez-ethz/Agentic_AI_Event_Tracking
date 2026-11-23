# Approach anchor diagnosis

The four-candidate [Verification archive](verification.Uk6X57/run/result.json) contains a supported single-person movement at 3.52–9.52 s. It contains no validated two-person approach predicate. The local resolver also declines relationship descriptions before lexical matching. Both are observable constraints. Neither is evidence that the supplied video lacks an approach.

## Evidence ledger

| Stage | Record and implication |
|---|---|
| Source video | Provisional local review shows two distinguishable figures moving diagonally, their apparent image-plane separation decreasing from frames 145–163, overlapping around 175, and appearing close but distinguishable again around 188–193. This supports apparent convergence and brief nearby movement. The projection gives no calibrated distance, and the overlap limits assignment of a continuous individual track. The sequence does not establish an interaction, intent to join, or persistent joint movement. |
| Initial perception | [Archived observation](../meet_walk_split_high.uGljGL/run/analysis.json) `observation-da6fdebc…` describes diagonal movement toward the upper left and adds “joining the other walking individual.” The category is `person_moved`. |
| Investigation | [Accepted delegation](live.CIW3cs/continuation/decision.json) preserves that observation and associates `2182a33c…`, a first-visibility observation, with the diagonal movement using frame 88. That association concerns whether two observations describe the same event. It does not validate a relation between two people. |
| Targeted Verification tool | Verification explicitly asks to check diagonal movement and joining in the clip over [3.52, 9.52) s. The recorded result has two appearance descriptions and two movement descriptions. `74a538a6…` describes lower-right to upper-left movement. Another describes the left-side person moving alongside the first. These are model observations. The archive records the source frame mapping and requested 2 fps. The original submitted WebM and provider sampling record are absent. |
| Verification verdict | The rationale supports diagonal motion only. The transition identifies one observation and its two frames, 88 and 238. The `different_events` assessment refers to the appearance observation `2182a33c…`, not to different people. The proposed verdict lists `74a538a6…` too, but the accepted direct-transition witness is the original frame observation. |
| Event construction | `AgentRun._visual_transition` checks provenance, witness and ordered distinct frames, then retains the seed and selected witness. The persisted `Event` has category `person_moved`, interval [3520000, 9520001) µs, supported verdict, reason and initial-sequence citations. No relation was accepted prior to construction. A verified field was not dropped. |
| Query resolution | The resolver sees this Event and the archived observation prose. Its person-relationship guard declines the anchor before lexical matching. Even injecting “the two people approached each other” into both prose fields leaves the response unchanged. Removing the guard would make prose eligible for matching despite the missing relational verdict. |

## Decisive frame references

The 13 cited display indices are 88, 100, 113, 125, 138, 150, 163, 175, 188, 200, 213, 225 and 238. The provenance regression checks each against decoded RGB24 SHA-256 and source PTS. Source time base is 1/12800. The close-approach crop below was reviewed separately from the cited sequence and includes uncited frames.

| Display index | PTS | Source time | Role in review |
|---:|---:|---:|---|
| 88 | 45056 | 3.52 s | Recorded transition start, lower-right movement |
| 150 | 76800 | 6.00 s | Both figures remain distinguishable with visible separation |
| 163 | 83456 | 6.52 s | Figures draw closer in the projection |
| 175 | 89600 | 7.00 s | Silhouettes overlap |
| 188 | 96256 | 7.52 s | Two nearby silhouettes can be distinguished again |
| 238 | 121856 | 9.52 s | Recorded transition end, both visible on the atrium floor |

The [prior frame manifest](supported-findings-frame-manifest.json) records full identifiers and hashes. Independent blinded review was unavailable. The visual reading is provisional and reviewer agreement is unmeasured.

## Counterfactual checks and decision

- **Supported relational positive:** Unavailable under the existing contract. There is no approach event category. The production schema accepts the actual movement verdict and rejects an added relationship field on either the verdict or its transition. This checks representability without inventing another event record.
- **Ambiguous relationship:** The archived approach question has no anchor. A prose-only counterfactual still yields no anchor. Separation afterward likewise returns insufficient evidence. Apparent convergence is visually plausible, while the stronger interpretations and a separately verified approach remain unestablished.
- **Nonexistent record:** The handshake query has no matching anchor. The system supplies no timestamp.
- **Movement control:** “What happened after movement in the sunlit aisle?” returns later records chronologically. It retains the disputed 20–24.52 s entry as a **recorded supported finding** and omits its unconfirmed purple clothing and left-to-right trajectory details from the answer. The answer states that ordering cannot establish identity or continuity.

The minimum action is to keep the current uncertainty response. No accepted relational evidence is lost in serialization, so no production change is needed. For relational anchors to become part of the MVP, a verifier would need a structured observable predicate with two locally distinguishable participants, cited frames showing decreasing apparent separation, an evidence bracket, and explicit treatment of occlusion or correspondence uncertainty. A separate semantic review should judge that narrow claim before considering interaction or intent. The current MVP can deliver cited movement retrieval without that additional contract.

## Reproduction

```sh
ffprobe -v error -select_streams v:0 -show_entries stream=time_base,r_frame_rate data/raw/Meet_WalkSplit_pts.mp4
ffmpeg -v error -i data/raw/Meet_WalkSplit_pts.mp4 -vf "select='between(n,145,193)*not(mod(n-145,2))',crop=196:120:56:71,scale=294:180:flags=neighbor,tile=5x5" -frames:v 1 /tmp/sa-approach-audit.png
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_retrieval.py
.venv/bin/python -m pytest -q tests experiments/meet_walk_split_high_probes/test_retrieval.py experiments/meet_walk_split_high_probes/test_probe.py experiments/meet_walk_split_high_probes/test_verification.py
```
