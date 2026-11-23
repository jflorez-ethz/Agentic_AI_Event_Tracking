# Relational inspection selection audit

## Recorded decisions and reconstructed requests

The live baseline is `experiments/meet_walk_split_high_probes/verification-autonomous-live/result.json`. Its eight parsed Verification responses, two inspected clip manifests and tool outcomes are recorded. The wire requests and original successful clip-response bodies were unavailable. The differential test replays the saved decisions and reconstructs the two media responses from their parsed findings. The current SDK serializes each request into a mock HTTP transport. The replay reproduces the archived Events, completion state and 11 physical requests. It does not make a model call. The request captures are reconstructions.

| Verification call | Candidate ID prefix | Baseline evidence and decision | Remaining role calls / inspections / iterations |
|---|---|---|---|
| 1 | `3bfb1c56bb` | Seed and associated first-visibility observation. Requested an ordinary clip in [0, 9.52) s to check one movement. The overlapping diagonal description containing “joining” was unavailable in this call. | 11 / 4 / 4 |
| 2 | `3bfb1c56bb` | Four new clip observations describing two people’s individual appearances and paths. Returned a single movement verdict. | 10 / 3 / 3 |
| 3 | `da6fdebc40` | Archived “joining the other walking individual” cue, associated appearance and two overlapping clip movement descriptions. Returned a single movement verdict. | 9 / 3 / 4 |
| 4–5 | `ac83682fb5` | Only the upper-left corridor movement. Deferred `83b23ba3db` described the concurrent path toward reception seating. It was missing from both calls. First verdict lacked the required transition pair. Recovery supplied the pair without a new inspection. | 8 / 3 / 4, then 7 / 3 / 3 |
| 6–8 | `433e142005` | Only the later walkway movement. Requested an ordinary clip in [20, 24.52) s. It returned no observations. Runtime rejected the repeated clip request. Recovery used archived frames for an individual movement verdict. | 6 / 3 / 4, 5 / 2 / 3, 4 / 2 / 2 |

All eight reconstructed contexts indicated that inspection and reconsideration were possible. The original experimental instruction described `modality: frames` with optional `relational: true`, and the schema serialized that boolean. The model could have chosen an overlapping interval. Nothing in the recorded trace establishes why it did not. The prior instruction both scoped the verdict to the delegated observation and permitted relational inspection when warranted. Whether that wording encouraged early closure is a hypothesis. The absent concurrent path in calls 4 and 5 is a demonstrated handoff gap. The first two candidates show that supplying more evidence alone is unlikely to explain every missed choice.

## Opt-in correction

Add `--relational-selection` alongside `--autonomous-relations` in the archive runner. Regular production, the earlier autonomous mode, prepared records, model settings and 500 ms sampling follow their existing paths.

- **Evidence access.** Verification receives up to four temporally overlapping archived person observations absent from its existing evidence, ranked by overlap duration. Excluded observations stay out. IDs, intervals, frame references, descriptions and dispositions are preserved. These leads can guide the choice of inspection. They cannot be cited for a verdict or merged into the original candidate. The deferred reception path appears in calls 4 and 5 without a disposition change.
- **Action design.** In this mode, the schema distinguishes ordinary inspection from a relational inspection branch. The latter requires `modality: frames`, `relational: true`, the interval, a reason describing the evidence gap, and a short `visual_question`. The runtime checks that the question is present before spending a tool slot. The instruction asks Verification to consider a concrete unresolved visual question before closing a movement check, and says mere co-visibility does not warrant inspection. The agent still chooses whether to inspect. The question is recorded for audit. The media request retains its generic pixel-grounded prompt and receives no candidate-specific question or answer cue.
- **Instrumentation.** Experimental `result.json` records the exact role context beside the resulting Verification decision, along with the existing trace, raw relational media response when available, citations, and usage. Record actual tool selection from the returned action. When a verdict offers no explanation of its relational decision, whether the model considered an inspection remains unknown.

The replay differences are two experimental context fields, an appended instruction, and the explicit inspection branch. The existing evidence map, inspection and role budget fields, movement validators, and model settings do not change. Scripted controls run the accepted, invalid, ambiguous and abstention paths through both autonomous modes. The archived responses replay unchanged, including the single-person and co-visible movement-only decisions. Dedicated controls reject a missing question, duplicate interval, and exhausted inspection budget.

## Offline reproduction

```sh
.venv/bin/python -m pytest -q \
  experiments/meet_walk_split_high_probes/test_relational_selection.py \
  experiments/meet_walk_split_high_probes/test_autonomous_relations.py \
  tests/test_agents.py tests/test_graph_workflow.py \
  --basetemp /tmp/sa-selection-audit
```

The differential test writes `baseline/reconstructed-verification-requests.json` and `revised/reconstructed-verification-requests.json` in its temporary directory. These retain each reconstructed context, instruction, schema, and recorded decision. The enhanced synthetic controls are interface tests, with no measurement of tool selection by Gemini.

## One separately authorized live evaluation

Use the same archived handoff, budget, model settings and neutral retrieval question as the prior run. No prepared relationship records, scripted decisions or mandatory inspections.

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/verification.py \
  --autonomous-relations --relational-selection \
  --authorize-observation-text-transfer --authorize-footage-transfer \
  --question 'What happens in this video? Reconstruct the sequence of visible events, including relationships between movements when supported by evidence. Explicitly identify uncertainties.' \
  --output experiments/meet_walk_split_high_probes/verification-relational-selection-live
```

The cap remains 28 physical requests, including up to four targeted media requests. The existing archive replaces the initial video scan and Investigation calls. Only run after authorization to send observation text and targeted media. The question is evaluated locally after the run. The traces distinguish whether a relation survived into Event and Reporting from whether the neutral retrieval query actually returns it.

Count a selection only when the model itself emits an admissible targeted frame action with a specific question, evidence gap and interval. Independently judge whether the question was warranted and whether the interval could answer it. Compare the first appearance of the proposal in the raw media response, the validator outcome, the downstream results, and extra token, latency, and media costs. Cases where no worthwhile question exists may appropriately abstain. Treat any difference from the original run as descriptive. This one follow-up combines evidence-access and action-interface changes, so attribution would need additional controlled runs.

## Archived follow-up and finalization replay

The subsequent live run in `verification-relational-selection-live/result.json` requested one relational inspection and selected the returned approach proposal on two turns. Both turns reached LangGraph's verdict validation. Each returned a supported movement verdict without `transition`, so the movement validator requested recovery. Once recovery was exhausted, the graph had `completed: false` and passed no relation action to finalization. The archived proposal passed the standalone relation check, but neither selection reached that check in the live graph.

With autonomous relations enabled, LangGraph now validates the selected proposal from each schema-accepted verdict before running the movement validator. The graph retains the separately validated finding in candidate state across recovery and finalizes it alongside the movement outcome. A repeated ID is checked at most once per candidate. The first supported relation is retained for that candidate. A validated insufficient relation remains unresolved and may be superseded by a separately validated proposal before a supported relation is retained. Each candidate starts with empty relation state. Movement completion accounting remains unchanged.

Reproduce the exact replay locally:

```sh
.venv/bin/python -m pytest -q \
  experiments/meet_walk_split_high_probes/test_relational_selection.py::test_exact_live_relation_survives_failed_movement \
  --basetemp /tmp/sa-relation-finalization-audit
```

The SDK mock uses the saved parsed decision objects without changes and the original relational media response text. Verification contexts match the saved live contexts. The recreated inspection record matches the archive, including canonical source timestamps, PTS and RGB24 hashes. The outputs retain one `approach` relation at [3.520000, 7.040001) s with eight exact source frames and unresolved person continuity. The parent movement remains insufficient and completion remains 2/4. Reporting describes the relation and event-relative retrieval returns it as an anchor. The mock tests the preservation boundary rather than Gemini's visual accuracy. The overlap-endpoint marks remain provisional, and support under the geometric contract supplies no claim of joining or same-pair separation.
