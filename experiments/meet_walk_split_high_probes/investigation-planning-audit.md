# Investigation planning audit

The live Investigation call committed four individual movement checks after seeing eight of eleven archived observations. It had search and optional relational delegation available. The interface disclosed the count of observations outside the current context and gave no indication of the intervals they covered. This is a concrete information gap. The run does not establish whether filling it would change the model's decision.

[Saved run](independent-relational-tasks-retry-live/result.json) · [Observation ledger with complete descriptions, IDs, citations, saved context and parsed decision](investigation-planning-ledger.json) · [Source archive](../meet_walk_split_high.uGljGL/run/analysis.json)

| Observation ID prefix | Cited times (s) | Frames | Archived description, summarized | Outcome |
|---|---:|---:|---|---|
| 7347dcf6e0 | 0 | 1 | Blue top and dark trousers visible near the lower-right edge | Associated with a0edff0f46, unresolved |
| a0edff0f46 | 0–1 | 3 | Blue top walks toward the lower-right edge | Delegated, incomplete |
| c7fda2e68f | 0 | 1 | Dark shirt and lighter trousers visible in the left sunlit corridor | Associated with 3bfb1c56bb, unresolved |
| 3bfb1c56bb | 0–9.52 | 20 | Movement from the sunlit aisle toward the upper-left corridor | Delegated, supported after recovery |
| 2182a33ced | 3.52 | 1 | Dark-clothed person becomes visible at the lower-right edge | Associated with da6fdebc40, unresolved |
| da6fdebc40 | 3.52–9.52 | 13 | Diagonal motion toward the upper left, described in the archive as “joining” | Delegated, incomplete |
| ac83682fb5 | 10–14.52 | 10 | Dark-clothed person moves toward the upper-left corridor | Delegated, supported |
| 83b23ba3db | 10–14.52 | 10 | Second dark-clothed person moves toward left reception seating | Deferred, “Candidate budget limit reached.” |
| 7628163245 | 16–16.52 | 2 | Person becomes visible in the lower-left sunlit walkway | Outside Investigation context, omitted |
| 7f18178dd6 | 16.52–19.52 | 7 | Rightward movement along the lower corridor | Outside Investigation context, omitted |
| 433e142005 | 20–24.52 | 10 | Claimed left-to-right traversal by a purple-clothed person | Outside Investigation context, omitted. Prior provisional visual audit disputed this claim |

Times show the cited frames. The exact half-open intervals and canonical frame IDs are in the ledger. The original scan completed. An omission here means Investigation did not receive an existing observation.

## Decision boundary

The context included eight observations in archive order with descriptions, uncertainty, visibility limits, and source references, plus the video duration of 24.96 s, total count of eleven, availability flag, four-slot limit, and a null tool result. The linked artifact preserves the parsed decision and context. Exact HTTP request bytes are unavailable. The request schema and instructions can be reconstructed from the local implementation.

The base prompt asks for meaningful observable candidates and disposition of visible evidence. The opt-in instruction adds one slot per relational task and accepts only IDs, with no expected relation. The runtime checks source compatibility, canonical frame references and temporal overlap. It calculates each relational scope from intersecting citations. Deferred evidence remains a lead. The planner receives neither an explicit coverage objective nor a rule instructing it to take the first four eligible movements.

Investigation had one local time-range search available. Search could bring up to eight overlapping unseen records into a second decision before delegation. The saved model returned “Delegating movement observations as event candidates, associating initial appearance observations with their respective movement events, and deferring remaining observations due to budget limits.” It issued no search and omitted the optional relational field. A valid delegate immediately commits the queue and records the unseen IDs as omitted. Four movements left zero relational slots. Eight of eleven observations were accounted for and two of four checks completed.

[Context and search loop](../../src/security_augmented/agents.py#L700) · [Task scope and budget validation](../../src/security_augmented/agents.py#L643) · [Relational delegation instructions](../../src/security_augmented/agents.py#L413)

## Opportunities visible before delegation

| Evidence available to the model | Open question | Slot trade-off |
|---|---|---|
| ac83682fb5 and 83b23ba3db, same ten cited frames, 10–14.52 s | What spatial relationship, if any, can be established between the visible movements in this interval? | Replacing the corridor movement check would give up its separate individual verdict. Keeping it and replacing the brief lower-right check would give up coverage of the initial edge movement. |
| 3bfb1c56bb and da6fdebc40, overlapping references, 3.52–9.52 s | What, if anything, can be established about the relative motion of the two visible trajectories during their overlap? | Replacing the diagonal movement check would give up a separate verdict on that trajectory. The archive’s “joining” wording is a cue to investigate. It establishes neither social interaction nor continuity. |

With hindsight, the three unseen records extend the set of candidate evidence past 14.52 s. Their timestamps motivate checking coverage. They provide no basis for linking the later people to the earlier trajectories.

## Separate movement-verification reliability issue

Five completed decisions claimed movement support and omitted the before/after transition. Two omissions concerned a0edff0f46, one concerned 3bfb1c56bb and two concerned da6fdebc40. The provider schema allows a direct-movement verdict to omit the transition. The prompt asks for it, and the runtime correctly rejects support when it is missing. The archived parsed decisions show the omissions. There is no evidence of parsing or finalization stripping a supplied transition.

Three candidates entered recovery. The first recovery requested an ordinary frame inspection and still failed to supply a transition. The aisle movement recovered using an ordered pair. The diagonal movement did not recover. The corridor movement supplied a valid pair on its first decision. The transition requirement remains intact.

[Optional verdict schema field](../../src/security_augmented/agents.py#L203) · [Required evidence for supported movement](../../src/security_augmented/agents.py#L1045) · [Transition validator](../../src/security_augmented/agents.py#L1097)

## Smallest next evaluation

Keep the existing planner as the control. Test one prompt-neutral context change first: expose the merged citation time ranges and record counts of unseen archived observations, with no text, IDs, or reference labels for those observations. This makes local search addressable and preserves the option to delegate immediately. A search adds one Investigation decision round and zero media requests. Under the fixed shared call budget, that round can displace a downstream decision. Published coverage metadata alone adds input tokens and no requests.

A separate alternative would ask Investigation to weigh individual and relational checks by what each could resolve before allocating slots. This changes the planning instruction and does not reveal where unseen evidence lies. The current search loop already permits reconsideration before delegation. A draft-and-commit phase would add state and potentially a call, with no trace evidence that a second commitment mechanism is needed.

Compare paired decisions on the same archives using the four-slot cap, identical role and media budgets, stable model settings, and no reference answers in the requests. Include unrelated co-visible movements and cases with no unseen evidence. Record visibility at delegation, time ranges and counts retrieved, redundant searches, questions justified by visible evidence, evidence-bearing intervals left open, which movement checks lose slots, completed and unresolved checks, requests, tokens and latency. Assess the usefulness of questions independently from the number of relations selected. Counterbalance runs and repeat decisions before interpreting a change as stable. Scripted acceptance and completion tests establish interface behavior only.

No production change was made. This run establishes a planning information gap and a separate schema-to-runtime transition mismatch. It does not establish which context change improves task selection or whether another delegation would have produced valid relational evidence.

## Offline verification

- Exact saved Investigation decision replay matched the archived context and reproduced four movement candidates, zero relational tasks, one deferred observation and three omissions.
- The default offline suite passed with 119 tests and 32 subtests via `.venv/bin/python -m pytest -q`.
- The focused probe suite passed 31 tests across `test_relational_tasks.py`, `test_investigation_diagnostic.py`, `test_relational_selection.py`, and `test_verification.py` under this directory. The tests exercised independent task completion, preserved deferral, rejected excessive and invalid task references, and retained the movement transition requirement.
