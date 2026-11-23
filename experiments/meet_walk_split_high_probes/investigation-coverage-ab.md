# Investigation coverage A/B protocol

## Offline result

The saved Investigation decision was replayed against the eleven archived findings it drew from. It delegated four individual movements, created zero relational tasks, and left three observations outside its context. On separate fresh replays, searching the first disclosed range returned two unseen observations and searching the second returned one. The one-search budget means these two narrow searches cannot both run in the same Investigation. A model may choose a broader interval or delegate immediately.

A preserves the recorded first Investigation context. B adds only `unseen_observation_coverage`. The experiment sorts the half-open canonical citation intervals of unseen observations and merges overlapping or touching intervals. Each record contributes once to the count of its merged interval. A range describes archived citation bounds. It does not establish continuous visual coverage inside those bounds.

| B's additional interval in microseconds | Unseen observations |
|---|---:|
| [16,000,000, 19,520,001) | 2 |
| [20,000,000, 24,520,001) | 1 |

The SDK captures in [request A](investigation-coverage-ab-offline/request-A.json) and [request B](investigation-coverage-ab-offline/request-B.json) have identical system instructions, generation configuration and response schema. The structured diff and replay results are in [replay.json](investigation-coverage-ab-offline/replay.json). These are reconstructed request bodies captured by a mock transport. They contain archived observation text and stay local. The mock returns the saved decision unchanged to both arms. No model behavior is measured.

From the repository root, choose a fresh output directory.

```bash
.venv/bin/python experiments/meet_walk_split_high_probes/investigation_coverage_ab.py --output /tmp/investigation-coverage-ab
.venv/bin/python -m pytest -q experiments/meet_walk_split_high_probes/test_investigation_coverage_ab.py experiments/meet_walk_split_high_probes/test_investigation_diagnostic.py
```

## Preregistered interpretation for a separately authorized trial

Use the same restored archive, model, prompt, schema, and local runtime for both arms. At each Investigation decision B recomputes the field from evidence still unseen. Both arms use a maximum of one archived search, four shared candidate slots, and the archived shared agent and media budgets. Validate actions identically. Record any transport errors, invalid decisions, and incomplete tasks. Keep the mandatory movement transition check and report transition failures separately.

Start with one fresh pair of real decision trajectories, stopping at validated delegation or Investigation failure. Let each arm perform its optional local search and continuation. This requires at most two Investigation decisions per arm when each decision has one physical attempt and validation failures terminate the probe. The selection-only ceiling is four physical requests per pair and zero media requests. A search adds one decision and consumes one shared model-call slot that could otherwise serve downstream verification. Compare projected remaining downstream budget at this stage. Selection-only results cannot establish which checks would actually finish.

Preserve the arm assignment privately and counterbalance order across any later repeats. Ask independent reviewers to assess each plan with the same archived evidence and citations, with arm names, prompts, and model rationales that reveal the arm withheld. Record disagreements before adjudication. Review each retained task and each displaced alternative using the same three checks:

1. Does it ask a concrete, source-grounded question that existing evidence leaves open?
2. Is there an available inspection or cited evidence that could answer it under the remaining budget?
3. Does it address a material unresolved question or cover relevant evidence left out by another task?

Per pair, record visibility and cited time ranges at delegation, search interval and new records, four-slot allocation, useful checks displaced, rejected decisions, requests, tokens and latency. If a later authorized trial executes the queue, also record completed checks, unsupported or unresolved findings, and unused budget. Use an archive with unrelated co-visible movements and an archive with no unseen evidence as controls before generalizing beyond WalkSplit.

Count B as preferable for a pair only when the blinded review finds a useful investigation added or a material omission removed, without an equally important investigation lost through slot or call displacement. Compare B wins, ties and losses and retain the paired explanations. A single pair is a feasibility check. Repeated paired behavior and independent agreement are needed to support a planning benefit. More searches, more observations retrieved, or more relational tasks alone do not constitute success.

## Commands for separate authorization

Run from the repository root. Use an unused pair directory and set `GEMINI_API_KEY` or `GOOGLE_API_KEY` privately. The flag explicitly authorizes transfer of archived observation text and source references to Gemini. Both arms must use the same directory. Each arm reserves its own subdirectory and refuses to overwrite it. Preserve failures in the pair instead of restarting an arm.

```bash
probe=experiments/meet_walk_split_high_probes/investigation_coverage_ab.py
pair=experiments/meet_walk_split_high_probes/investigation-coverage-ab-live
.venv/bin/python "$probe" --live-arm A --pair-dir "$pair" --authorize-observation-text-transfer
.venv/bin/python "$probe" --live-arm B --pair-dir "$pair" --authorize-observation-text-transfer
```

Each arm makes at most two physical requests, with one reserved for a continuation after a valid local search. There are no retries. Only archived model observations and source references are sent. The runner does not load the human review, start another role, or send media. The first request in each arm must match its saved mock SDK capture before it can be sent. Continuations naturally differ if the first decisions retrieve different evidence. B recalculates its field after the search.

Each arm saves `A/result.json` or `B/result.json` in the pair directory. These include the submitted bodies, HTTP status, complete raw successful HTTP response text including incomplete or invalid model candidates, parsed decisions when available, finish reasons, usage and latency, validation trace, search results, movement IDs, relational task IDs and scopes, slot usage, dispositions, unseen and omitted IDs, and remaining model-call budget. Credentials and headers are excluded. Keep the files local.

Generate the descriptive comparison offline after both arms finish.

```bash
.venv/bin/python "$probe" --compare --pair-dir "$pair" > "$pair/comparison.json"
```

Use the artifacts to prepare the blinded task review described above. The comparison contains arm identities and should remain with the experiment operator. The runner stops at delegation, so this pair measures planning choices and their opportunity costs. It does not measure downstream task completion.
