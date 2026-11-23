# Report specificity replay

The replay uses the same [events and decisions](verification.Uk6X57/run/result.json) and [original report](verification.Uk6X57/run/report.md). No event was re-verified.

## Reporting contract

Verification proposes a verdict, reason and evidence references. The controller validates the verdict, retains its evidence and stores the bounded model reason in `Event.reason`. This reason is prose rather than a set of individually verified claims. Reporting receives the same event summary as before and selects a lead and emphasis. The renderer keeps the generic category label and adds the retained reason on a separate line labeled **Verification rationale (model assessment)** for supported events with a nonempty reason. It normalizes whitespace and escapes Markdown control characters. The verdict, interval, citations, lead and unresolved lines stay as in the original. The deterministic baseline uses its existing rendering path.

Before:

> **00:00.000000–00:09.520000** A person moved within view. supported

After:

> **00:00.000000–00:09.520000** A person moved within view. supported
>
> Verification rationale (model assessment): The inspected frame sequence clearly demonstrates the movement of the person in a dark shirt and lighter trousers from the sunlit aisle into the central atrium area.

The same source citations follow this line. With all four rationale lines removed, the revised replay is byte-for-byte equal to the archived report.

## What the four records establish

The four archived verdicts are supported under the direct-movement contract. All eight selected transition endpoints were decoded locally and matched the recorded display index, PTS and RGB24 hash. The visual assessment is provisional.

| Interval | Endpoints | Retained detail and limit |
|---|---|---|
| 0–9.52 s | 0, 238 | Sunlit aisle toward the central atrium is the model's reading. The frames show activity in both areas. The endpoint pair alone cannot uniquely identify the person at both ends. |
| 3.52–9.52 s | 88, 238 | The rationale describes diagonal movement from the lower right toward the upper left. Positions and visible movement support a narrower description than a claim that the two people joined. The stored rationale is cut off at the existing 240-character limit. The renderer preserves its retained text. |
| 10–14.52 s | 250, 363 | Movement toward the upper-left corridor is the model's reading. Two people are visible at the start. The rationale mentions clip corroboration, but the final Event cites the original frame sequence. The clip is an inspection record, not a citation added by this report. |
| 20–24.52 s | 500, 613 | The rationale describes left-to-right walkway movement and clothing color. Glare and occlusion limit review of those specifics. The targeted clip returned zero observations. The archived verdict relies on the initial frame sequence. |

The four events carry distinct, reportable model assessments. The data model supplies no per-detail evidence status, so direction, clothing, exact path, and continuity cannot be promoted separately to verified facts. Unresolved associations remain separate entries. A blank rationale falls back to the category label and source citation.

Run the archive replay offline from the repository root:

```sh
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_verification.py -k preserves_archived
```
