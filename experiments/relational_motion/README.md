# Pair movement evidence contract

The prototype is offline and does not run inside Security, Augmented. The production default stays at 2 FPS. No model configuration, agent prompt, validator, event category, report or retrieval behavior changed.

## Where the relationship is missing

| Stage | Existing contract | Archived behavior |
|---|---|---|
| Perception | Category, description, uncertainty and cited frames. Relationship wording can appear in prose. | The archived diagonal-motion observation `da6fdebc…` mentions joining. The dense sampling arm mentions meeting and walking together but does not describe later divergence. |
| Investigation | Selects existing observations. Associations represent same-event correspondence between observations. | Delegates diagonal motion. Linking its first-visibility observation does not establish whether two people interacted. |
| Verification | For direct motion, selects one frame observation and two ordered distinct frames. A separate correspondence structure links observations, not people through time. | It requested a clip to verify movement and joining. The accepted verdict retained diagonal motion. Later, two clip descriptions described separate paths toward the corridor and seating. Verification retained one movement; it did not issue a two-person relation verdict. |
| Event, Reporting, retrieval | Event retains category, interval, verdict, cited observations and rationale. Reporting attributes the rationale to the model. Retrieval refuses person-relationship anchors in prose. | The serialized movement verdict is complete under its contract. No accepted relational field was discarded. |

Perception sometimes misses or overstates a relationship. The determining contract limitation is that Verification cannot accept a structured two-person proposition and Event cannot carry one. Better prompts or more frames alone cannot supply that missing contract.

## Provisional source assessment

The test replays eight cited frames and checks original video identity, display index, PTS, source timestamp and RGB24 hash. The native source images were also reviewed alongside the two sampling-arm outputs. Independent reviewers were unavailable.

| Bracket | Decisive display indices | What the images establish |
|---|---|---|
| 6–8 s | 150 (6.00), 163 (6.52), 175 (7.00), 188 (7.52) | Two figures close apparent image-plane distance. Their silhouettes overlap around 7 s and are distinguishable again later. This supports apparent convergence and nearby movement. Purpose, social joining and exact correspondence through overlap remain unestablished. |
| 10–14.52 s | 250 (10.00), 300 (12.00), 325 (13.00), 350 (14.00), 363 (14.52) | Two visible paths become distinguishable near the corridor and seating area. The end of the bracket is harder to resolve along the boundary. This supports visible local divergence. Carrying the same two individuals through the earlier overlap and into the later paths remains a separate claim. |

See the [approach audit](../meet_walk_split_high_probes/approach-anchor-audit.md) and [sampling audit](../meet_walk_split_high_probes/sampling-live.4GdQOj-audit.md) for canonical references and contact sheets. CAVIAR group labels are useful independently authored evaluation references. They are not agent inputs and do not make the archived verdict relational.

## Minimum proposed extension

Use an optional, separately verified relation record for a candidate, containing a narrow relation, cited views with two distinguishable local marks, and a continuity assessment. Its evidence bracket is derived from source citations. Keep it separate from any accepted individual-movement verdict. Attach it to Event only after validation, and render or retrieve only its accepted meaning with the relevant uncertainty.

The experiment-only validator explores that boundary. A visible approach requires a marked decrease in apparent spacing exceeding the supplied marking uncertainty. Visible divergence requires reviewed distinct paths and a robust increase in apparent spacing within the window. Nearness and distinguishable paths may be reported locally. Neither establishes social coordination or behavioral independence. Same-pair separation adds a cited nearby start and both person links for every adjacent reviewed view, including intermediate cited views. Unassessable overlap blocks a same-pair verdict. The prototype does not infer world distance, person identity, interaction, intent, joining or a shared destination. Visual marks, near/path judgments and the pair links still require semantic review. Sparse samples cannot prove continuity between unseen frames.

No production integration is justified yet. Before adding a Verification output field, get blinded judgments on the five cases below. In particular, do not turn a structurally valid bundle or reviewer boolean into automatic semantic proof.

## Offline controls and evaluation gate

| Control | Evidence supplied | Expected contract result |
|---|---|---|
| Approach | Two distinguishable visible people with robustly decreasing projected spacing | Support apparent approach; continuity unresolved |
| Visible divergence | Two reviewed distinct paths and robustly increasing spacing | Support local divergence; continuity to the earlier pair unresolved |
| Same-pair separation | Nearby start, robust divergence and both reviewed links through each cited view | Support only under the reviewed input contract |
| Ambiguous crossing | Overlap or missing/intersecting uncertainty and an incomplete link chain | Insufficient for same-pair separation |
| Joining | Apparent approach without additional evidence of a social relation | Insufficient; outside the contract |

These positive and negative controls use synthetic marks to test the rules. They are not dataset labels. The saved WalkSplit output has no marks or pair links and remains insufficient for relational verdicts in replay.

For the next evaluation, independently annotate the exact production-rate views first. Label visible approach, nearby movement and later divergence separately. Lock person correspondences and justified abstentions before revealing archived prose or group labels. Review a complete local sequence separately to see which judgments depend on extra frames. Include a separate verified same-pair separation and an ambiguous crossing if reliable examples can be found in existing footage. Compare baseline prose and the proposed contract on the same cited evidence. Count missed visible relations, false same-pair links, justified abstentions and valid citations. Keep unadjudicated cases open and report per-case results. Use the existing observations, perception tool and three roles if a validated production pilot is later authorized.

```sh
.venv/bin/python -m pytest -q experiments/relational_motion/test_contract.py \
  experiments/meet_walk_split_high_probes/test_retrieval.py
```
