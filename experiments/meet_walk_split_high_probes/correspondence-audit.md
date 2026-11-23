# Investigation correspondence audit

The [archived decision](live.bGCsdz/continuation/decision.json) had one STOP candidate, four delegated IDs and seven dispositions. The archived schema in [the request plan](live.bGCsdz/continuation/input.json) accepts it under JSON Schema. The [recorded result](live.bGCsdz/continuation/result.json) rejected the fourth disposition. Its outer status was `associated`, its pair status was `different_events`, and its pair carried a non-null shared frame. All observation references were in the current context.

`AgentRun._triage` requires a visible, unique disposition ID and a delegated candidate. It calls `assess_correspondence` with the candidate as seed and only the disposition observation as the other member. The pair's identifier and quotes passed those checks. The non-null anchor on `different_events` raised the recorded error before the association-specific check. With a null anchor, that pair would still fail `_triage` because association requires `same_event`. The runtime behaved as intended. The response schema had reused the generic pair schema, which also serves Verification. The Investigation prompt already described association as same-event.

## Compatibility matrix

| Wire disposition | Pair status | Candidate reference | Anchor | Outcome and invariant |
|---|---|---|---|---|
| Delegation via `ids` | Absent | The ID is itself a candidate | Absent | Eligible for verification. Visible canonical IDs must be unique and within the four-candidate limit. |
| `deferred` | Absent | Absent | Absent | Observation remains open. Requires a visible, unassigned ID and reason. |
| `excluded` | Absent | Absent | Absent | Records exclusion from the investigation with a reason. It does not establish that the event did not happen. |
| `deferred` or `excluded` | Any supplied pair | Supplied pair or candidate | Any | Rejected. These dispositions allow only ID, status, and reason. |
| `associated` | `same_event` | A delegated ID; pair ID equals disposition ID | Non-null canonical frame cited by both | Eligible association. The quotes must occur in the respective descriptions. The association remains open until separately resolved by Verification. |
| `associated` | `same_event` | Not delegated, or pair ID names another observation | Any | Rejected by triage or the restricted pair lookup. |
| `associated` | `same_event` | Valid | Null or outside either citation | Rejected. Both citations must include the anchor. |
| `associated` | `different_events` or `unresolved` | Valid | Non-null | Rejected by generic pair grounding and by the association schema. |
| `associated` | `different_events` or `unresolved` | Valid | Null | Rejected by triage and by the association schema. A non-associating disposition can preserve the observation. |

In Verification's generic pair assessment, `different_events` means the model assesses distinct events and `unresolved` means it cannot establish correspondence. Both require grounded excerpts and a null same-event anchor. A null anchor does not mean the events cannot appear simultaneously. Verification retains all three pair statuses.

The schema now specializes only the association branch to require `same_event` and a string anchor. Visible canonical ID enums remain in place. Cross-field equality, actual delegation membership, duplicate IDs across records, exact quote matching, pair-specific frame intersection, and completeness accounting remain runtime responsibilities. Shared frames and exact excerpts provide inspectable grounding for a model judgment. They cannot prove that the judgment is visually correct.

## Local visual check

The two movement observations (`ac83682…` and `83b23ba…`) cite the same ten frames from 10.000 to 14.520 s. The shared anchor is display index 250, PTS 128000 with time base 1/12800, and RGB24 SHA-256 `317f76b388c42bb9c4c02202e4c78c7bee2f464db253d2679443dd621e6c1a2e`. Local decoding matched the archived PTS and pixel digests for all ten frames. Adjacent frames 249, 251 and 364 were decoded and reviewed with the cited sequence. Frame 250 shows two distinguishable people near the left of the atrium. Across the sampled sequence they occupy separate positions and appear to take different paths around the seating area. This supports two simultaneous individual movements within a shared scene. The common frame does not identify which description belongs to which path or establish uninterrupted identity outside the visible sequence. The scene can also be described at the broader granularity of joint activity; that does not make two individual movement claims interchangeable. The visual assessment is provisional and the archived decision has been preserved.

## Reproduction

From the repository root:

```sh
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_probe.py tests/test_evidence_semantics.py
```

The primary test replays the exact decision and changes one relationship condition at a time. Its positive control keeps the three existing same-event proposals and defers the disputed movement as a separate observation. It validates triage and canonical references, without treating that fixture as a new model judgment or a verification of its visual claims.
