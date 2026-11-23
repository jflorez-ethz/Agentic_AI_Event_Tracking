# Opt-in relational Verification

The existing relational validator now lives in `src/security_augmented/relations.py`. The experiment imports that same implementation. An opt-in Verification verdict can reference one offered `relation_review_id`. Each local review record supplies its claim, explicit half-open interval, canonical frame references, visible marks and, when applicable, the local path judgment or both person links. Verification receives these structured records and the ordinary textual evidence context. It cannot supply arbitrary coordinates or substitute a frame by changing its decision. This first integration depends on locally supplied visual review. It does not detect pair marks or links automatically.

The runner independently validates the relation against the source citations visible to Verification. The prototype checks apparent spacing, marking uncertainty and continuity prerequisites. For separation, the validator requires every known view in the bracket, and the integration additionally abstains across a gap greater than 550 ms on the archived 500 ms grid. The 50 ms tolerance accommodates source timestamp quantization. This is a conservative implementation choice for the pilot. It does not establish visibility between samples. Long gaps and unassessable views remain open. Review records must describe what was visible, and a syntactically complete link chain is not independent proof of correct identities.

The optional typed Event field preserves the reviewed claim, exact time bracket, canonical frame evidence, validator status, and separate continuity status. A rejected relation leaves the independently validated movement intact. The report labels image-plane relationships and displays unresolved correspondence. Event-relative retrieval recognizes a limited set of relationship phrases and uses only matching supported typed records. Multiple distinct review records remain ambiguous. Queries asking for same-pair separation require reviewed continuity. Existing movement anchors and movement verdicts follow their original path.

## Archived offline replay

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/relational_replay.py /tmp/walksplit-relational-replay
.venv/bin/python -m pytest -q experiments/relational_motion experiments/meet_walk_split_high_probes/test_retrieval.py
```

The replay uses 500 ms evidence and the actual archived Investigation delegation. It verifies the assigned source indices, PTS, timestamps and decoded RGB24 hashes before running the graph locally. The generated `reviews.json` records provisional marks, while `replay.json` keeps scripted decisions, Event records, trace and retrieval answers separate. The scripted independent movement verdicts are deliberately insufficient. The report is in `report.md`.

| Verification choice | Source display frames | Validator → Event → report | Retrieval |
|---|---|---|---|
| `approach` | 150, 163 | Supported apparent convergence at 6.00–6.52 s. Continuity unresolved. | “After the two people approached each other” resolves to that typed anchor. |
| `divergence` | 250, 325 | Supported local divergence at 10.00–13.00 s. Continuity unresolved. | “After local divergence” resolves to the typed anchor. |
| `overlap` | 163, 175, 188 | Relationship unresolved at 6.52–7.52 s. | “After the same two people separated” has no anchor. |

The dated archived model run did not make these relational decisions. The replay uses existing provisional single-reviewer marks for local visual claims. Independent blinded review of the exact cited frames is still needed to evaluate semantic accuracy. The synthetic accepted separation control tests compatibility of a complete two-person link chain. It makes no identity finding about WalkSplit.

## One separately authorized live evaluation

Use `data/raw/Meet_WalkSplit_pts.mp4` and the existing archive `experiments/meet_walk_split_high.uGljGL/run/analysis.json`. The accepted Investigation input, decision and result are under `experiments/meet_walk_split_high_probes/live.CIW3cs/continuation/`. The runner checks the handoff and source before opening the client. Have independent reviewers inspect the same source frames blind to model outputs. Copy their agreed records into the format of the generated `reviews.json`, with disputes represented as unresolved. Save that reviewed input as `/tmp/walksplit-reviewed-relations.json`.

Only after separate authorization, run:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/verification.py \
  --relational-reviews /tmp/walksplit-reviewed-relations.json \
  --question 'What happened after the two people approached each other?' \
  --question 'What happened after the same two people separated?' \
  --authorize-observation-text-transfer --authorize-footage-transfer \
  --output experiments/meet_walk_split_high_probes/verification-relational-live
```

Use one new output directory. The run replays the archived scan and Investigation locally. Gemini receives Verification observation text, frame references and the offered structured local reviews, plus Reporting's finding summaries. If Verification requests a targeted inspection, the existing media path can send source images sampled at 500 ms or a targeted clip configured at 2 FPS. The questions run locally. The archived budget allows four candidates, four Verification iterations per candidate, and 14 logical role calls including the two replayed Investigation calls. The cap is 24 physical reasoning requests plus four targeted media requests, **28 total**. The existing role retry and media payload limits remain in force. Audit the saved `result.json` and `report.md` against the exact review input. Successful operation includes justified abstention. A single run measures operational feasibility, and its chosen relations still require independent semantic adjudication.
