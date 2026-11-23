# Local event-relative retrieval

The video-first workflow already stores a supported timeline, unresolved events, and observations from initial and targeted inspections. Existing local retrieval filters supported events by category and by overlap with explicit source times. It does not invoke any of the three agents. The old parser could treat the movement words in a relative question as category filters for the entire timeline.

The local resolver handles “What happened before/during/after X?” with a cited supported anchor. It matches a literal category label or looks for the description in both an event's retained rationale and a linked observation. Direction and scene wording must match in order. This is conservative lexical retrieval over validated records. It does not independently verify their semantic content. Unknown or ambiguous anchors return a clarification rather than a time estimate. Person relationships such as joining, approaching or separating have no validated predicate in the current event categories, so the resolver preserves uncertainty for such anchors and for continuity questions such as “Did the two people separate afterward?”

Intervals are source-relative and half-open. Before requires the result to end at or before the anchor begins. After requires it to begin at or after the anchor ends. During requires the whole result bracket to be contained within the anchor and excludes the anchor itself. Results use chronological source order and surface unresolved records separately. The structured answer retains the anchor, results, and their complete existing citations. The relative path never automatically runs source inspection.

## Archived replay

Run from the repository root:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/retrieval.py
.venv/bin/python experiments/meet_walk_split_high_probes/retrieval.py \
  --question 'What happened after movement in the sunlit aisle?'
```

The harness checks the source identity and rehydrates the saved Verification events and original observations. No media inference, LangGraph run, or image decoding is needed.

| Query | Outcome |
|---|---|
| After the two people approached each other | No grounded anchor. The cited movement event is not a validated approach relationship. |
| Before the person entered the atrium | No grounded physical entry anchor. There is a supported movement description near the atrium. |
| Between 10 and 15 seconds | Existing behavior returns the 10–14.52 s movement and its source-frame citation. |
| Did the two people separate afterward? | Insufficient evidence of person correspondence or continuity. |
| After an event that never occurred | No grounded matching event or fabricated timestamp. |
| After movement in the sunlit aisle | Resolves 0–9.52 s, excludes the overlapping 3.52–9.52 s movement, and returns later supported and unresolved records in order. |

The replay preserves the archived 20–24.52 s supported verdict despite the later provisional audit questioning it. This retrieval path does not amend or re-verify an archived verdict. The matcher does not provide general paraphrase understanding or cross-event person tracking.

## Current video workflow

The main CLI now supports local questions against a saved `analysis.json` using `--saved-analysis`. In runs containing a validated typed relationship, direct, time-range and event-relative questions can return that relation's own interval and frame citations even when its host movement is insufficient. The earlier movement-only archive above still has no approach anchor. The resolver accepts a limited set of observable predicates and preserves unresolved identity. [Commands and example answers](../README.md)
