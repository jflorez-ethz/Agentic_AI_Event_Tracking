# Autonomous relational proposals from targeted frames

The archive runner's `--autonomous-relations` option reuses the WalkSplit 500 ms scan and accepted Investigation handoff. It excludes `--relational-reviews`. The regular workflow, prepared review mode, model settings, and request budgets retain their existing behavior.

## Evidence contract and ownership

| Boundary | What crosses it |
|---|---|
| Investigation → Verification | The archived observation descriptions and canonical citations. Initially the proposal list is empty. Verification may request an ordinary inspection or set `relational: true` on a targeted frame inspection. |
| Targeted frame inspection → Gemini | PNGs encoded from the sampled RGB24 source frames, request-local F labels, timestamps, dimensions, and generic visual instructions. This call receives no archived observation text, prepared record, expected relation interval, human marks, or person links. |
| Gemini → parser | Optional `relation` beside ordinary observations. It contains a claim, the exact half-open source interval, ordered F labels, two visible pixel marks and their uncertainty radii per assessable view, and the path or proximity judgment if applicable. A null relation abstains. An `unresolved` result can cite a view with unavailable marks. |
| Parser → Verification | The parser resolves F labels to immutable source IDs and runs the existing validator. A malformed or misaligned relation is dropped and logged independently of valid ordinary observations. The candidate-scoped proposal ID is the inspection ID. The raw media response, the normalized proposal, and the canonical source-frame inspection are saved in `result.json`. |
| Verification → Event | Verification can select an offered `relation_proposal_id`, request another inspection within the existing budgets, or omit the ID. It cannot supply or replace marks. The runtime revalidates the exact submitted inspection frames and bracket. Typed claims and unresolved evidence keep the `targeted_perception` source designation. The ordinary movement verdict stays separate. |

Apparent convergence and local divergence concern projected image-plane distances. A proximity judgment is scoped to one cited view and does not establish motion in that view. The parser and validator can check frame membership, geometry bounds, uncertainty margins, the reported temporal bracket, and the supplied path judgment. They cannot verify that Gemini actually found the right pixels or estimated the radii accurately. Two paths appearing to diverge do not establish identity after overlap. This pilot leaves autonomous same-pair separation out of the proposal schema and rejects identity links sent to it. The existing validator and prepared/synthetic complete-link controls retain their original requirements. Do not treat a positive mocked result as evidence of recognition quality.

Changes are in `src/security_augmented/{agents,gemini,observation,relations,workflow}.py`, `experiments/meet_walk_split_high_probes/{verification,test_autonomous_relations}.py`, and this note. LangGraph reuses its existing inspect → decide → finish nodes.

## Reproduce the offline traces

```sh
.venv/bin/python -m pytest -q \
  experiments/meet_walk_split_high_probes/test_autonomous_relations.py \
  experiments/meet_walk_split_high_probes/test_verification.py \
  experiments/meet_walk_split_high_probes/test_retrieval.py \
  experiments/relational_motion \
  --basetemp /tmp/sa-autonomous-traces
```

Use a fresh dedicated temporary directory for `--basetemp`. For the approach and unresolved fixture cases, read each `autonomous/mock-requests.json`, `autonomous/result.json`, and `autonomous/report.md`. The mock capture contains the serialized media request with image bytes omitted and the Verification content/schema captured before and after inspection. The fixture uses three actual WalkSplit images and supplies scripted marks. In the approach case, the media response cites F1–F2 (6.00–6.52 s), Verification selects the inspection's proposal, continuity remains unresolved, and the retrieval answer gets an approach anchor. In the ambiguous case the second view has null marks and produces an explicitly unresolved report with no approach or separation anchor. Other controls cover local divergence, nearby, abstention, an unknown proposal ID, an invalid frame, a shifted interval and an unsupported identity proposal. No Gemini connection is used in these tests.

## One separately authorized live run

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/verification.py \
  --autonomous-relations \
  --authorize-observation-text-transfer --authorize-footage-transfer \
  --question 'What happened after the two people approached each other?' \
  --question 'What happened after the same two people separated?' \
  --output experiments/meet_walk_split_high_probes/verification-autonomous-live
```

Use a new output directory. The input is `data/raw/Meet_WalkSplit_pts.mp4`, the archived scan `experiments/meet_walk_split_high.uGljGL/run/analysis.json`, and the accepted handoff under `experiments/meet_walk_split_high_probes/live.CIW3cs/continuation/`. The runner sends at most 24 physical reasoning requests and four targeted media requests, 28 total. It does not run a new initial scan. Targeted 2 FPS source media and role context can leave the machine after authorization. The questions run locally after the investigation. Review `result.json` for the role decisions, raw autonomous media outputs, frame references, failure diagnostics and proposed/validated relation trace. Use `report.md` and the saved answers to audit scope and abstention.

For evaluation, require the exact label, bracket and marks to first appear in the targeted media response. The archived observation starting `da6fdebc40` already says that a person was “joining the other walking individual,” and `ac83682fb5` and `83b23ba3db` describe different paths. A matching relation may be visual corroboration of evidence that guided Verification toward an inspection. It cannot establish discovery of an unsuspected event. Have independent reviewers assess the exact submitted frames blind to model output, then compare provenance, visible support, timing, continuity, and abstention separately. Preserve disagreement as unresolved. A later visual control can preserve the prompt, frame count, timestamps and selection context while using a separate provenance-tracked sequence without the relative motion. Compare whether the model withdraws the proposal. Do not mix the control into the source manifest or infer reliability from a single live run.
