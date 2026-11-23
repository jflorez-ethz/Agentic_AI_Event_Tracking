# Investigation planning comparison

Run from the repository root. The full case reconstructs the first Investigation context from the ordered observations and budget in `experiments/mvp_live.6R7h4T/run/analysis.json`. The archive contains the accepted dispositions and trace rather than the original wire body. Both arms use the same current production serializer. B appends exactly the requested sentence to the system instruction on each logical decision. Each run captures both first requests offline, checks equality after the one insertion, then checks the live first request before transmission.

Cases:

- `full` uses the same eight initially visible observations, with three further observations available through the ordinary optional search.
- `disjoint` uses archived movements at 0–1, 10–15 and 16.52–19.52 seconds. Three direct checks fit the budget. These intervals have no overlap for a relational task.
- `appearance` uses the short blue-top appearance and movement plus the later walkway movement. The first two descriptions provide a lead about one person's visibility and motion. The later observation has a separate time interval. Review whether an extra task would answer anything beyond the individual checks.

The controls are deliberately filtered software/evaluation cases, not new videos or independent ground truth. Their complete stores contain three observations each. Within each case A and B have identical evidence and tool availability. No case names, rationale for selection, human evaluations or coverage field enter the SDK request.

## Execute

Offline preparation writes a manifest with both first SDK requests to a new directory:

```bash
.venv/bin/python experiments/investigation_planning/compare.py prepare /tmp/planning-preview
.venv/bin/python -m pytest -q experiments/investigation_planning
```

For the authorized comparison, configure your existing Gemini API key privately and run:

```bash
pair=$(mktemp -d experiments/planning-live.XXXXXX)
for case in full disjoint appearance; do
  .venv/bin/python experiments/investigation_planning/compare.py live "$pair/$case" \
    --case "$case" --authorize-observation-text-transfer || break
done
```

The full pair costs at most four physical Investigation requests, allowing one search and one continuation per arm. Each control has no unseen observations and permits only delegation in its initial SDK schema. Its physical cap is one request per arm. The complete three-case evaluation is capped at eight physical requests, with SDK retries disabled. Only archived observation text, provenance references, planning instructions and schemas are sent. The experiment does not load media or execute delegated tasks. The output ceiling is 20,480 per call, HIGH thinking. A and B run in a recorded randomized order. After a search the contexts can diverge as a legitimate consequence of the decisions.

## Review before unblinding

Give the reviewer only each case's `review.json`. It contains the plans in shuffled order and archived descriptions and citations. Keep the manifest and arm diagnostics separate until the review is written. An invalid or interrupted plan is an execution outcome and cannot win on task usefulness.

1. Compare task sets by canonical observation ID for individual checks and sorted member IDs for relational checks. List the tasks unique to each plan and the ones shared. If several tasks differ, evaluate the tradeoff between sets without guessing a one-to-one displacement. Record unused slots.
2. For each unique task, record the concrete uncertainty it could settle, which cited views could distinguish the alternatives, and what would remain unresolved. Rate it **useful**, **redundant**, or **unclear**, with one evidence-linked sentence. Use the same standard for movements and relations. Overlap allows a question but does not establish an answer.
3. Give a paired judgment: **first plan / second plan / tie / insufficient basis**. Identify the most valuable displaced check and explain why the chosen set is worth its cost. On controls, explicitly record whether the plan preserved useful independent checks.
4. Lock the judgment before opening A.json and B.json. Compare the plans with the recorded validated movements and task member IDs to identify the winning arm; identical plans tie. Record searches, retrieved IDs, unexamined observations, validation failures, request counts, role usage and latency alongside the judgment.

A favorable full-case result with defensible tradeoffs and no control regression warrants replication. One generation per arm on a development video measures a planning difference only. These results cannot establish downstream verification accuracy.
