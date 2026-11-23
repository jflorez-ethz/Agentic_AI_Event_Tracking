# Relational question handoff

Run from the repository root:

```sh
.venv/bin/python experiments/relational_question_handoff/evaluate.py
.venv/bin/python -m pytest -q experiments/relational_question_handoff
```

The harness uses the production LangGraph, the ordered observations from `experiments/mvp_live.6R7h4T/run/analysis.json`, the archived budgets and model configurations, and HTTP mock transport for every SDK call. It decodes frames from the local WalkSplit video. `evaluate.py` has no live mode. The separate [`visibility_live.py`](visibility_live.py) runner sends live Verification and Perception requests only with explicit authorization, or uses a mock transport offline. Its single recorded run is described in [visibility-live.md](visibility-live.md). Individual supported controls use archived transition-frame references inside scripted verdicts. Candidate choices, dispositions, tool choices and model responses are fixtures. This is not an exact replay of either the production Investigation decision or its dispositions.

Two runs per allocation compare the existing generic objective to the experimental handoff. Within a pair the observation members, task ID, individual checks, inspection interval and rate, returned perception result and verdict policy are fixed. This isolates whether a question survives assignment and continuation. The optional relational task requires a question only in the experimental interface. The production validator still owns membership, source compatibility, time overlap, slot accounting and proposal acceptance. Only the textual task metadata is extended.

| Allocation | Uncertainty being investigated | Opportunity cost |
|---|---|---|
| Recorded selection of four movements | Each individual before/after transition | The two overlapping movements receive no independent joint assessment. |
| Three movements plus spacing question | What change, if any, in relative image spacing is visible? | Gives up the independently supported 0–1 s lower-right movement. Retains both early trajectories and the later reception movement. |
| Three movements plus visibility question | In which frames, if any, are both silhouettes distinguishable? | Gives up the independently supported 10–15 s reception movement, reducing later temporal coverage. |
| Disjoint control | Three individual checks at separate times | A joint task would lack a common evidence interval. |
| Appearance control | Early appearance and motion plus a later walkway movement | The first two descriptions concern one apparent mover. They supply no specific two-trajectory question. |

The relational allocations reference the same two observations overlapping from 3.52 through 9.52 s. In each, Verification is scripted to inspect [6.03, 7.03) s. The offset exercises novel frames at either rate under the production redundancy check. Spacing uses 250 ms and visibility uses 500 ms. This is not a comparison of rate effectiveness. A mock response returns no proposal, so both tasks remain unresolved. The experiment also tries using the question as a proposal ID and checks the report and retrieval outcome. No real-world identity label is assigned.

The question field makes the two assignments distinguishable to Verification even though they have the same canonical members and task ID. It cannot create a second slot for a duplicate pair. The schema description calls for neutral wording; runtime bounds length and checks open-question form. A grammatically open question can still presuppose an answer. The two actual fixtures were checked for that separately. Do not use wording checks as a semantic validator.

For a usefulness decision, blind a reviewer to the interface and ask which visual uncertainty each assignment communicates, which frames could settle it, and whether the displaced movement was more valuable. The scripted assignments measure neither Gemini's propensity to select the task nor any gain in visual understanding.
