# Independent relational investigations

## Archived task boundary

The saved WalkSplit handoff delegated the corridor movement (`ac83682fb5…`) and deferred the reception path (`83b23ba3db…`). Verification saw the second observation as an additional lead and accepted the first movement with ordered frame endpoints. The graph's accepted movement verdict routed directly to candidate completion. There was no relational task in the queue. The saved response did not explain whether Gemini considered an inspection.

The offline primary test reuses that exact parsed movement decision with the two archived observations. A scripted delegation exercises both modes under the same budget. The movement Event, completion count, and observation dispositions are identical. In the opt-in case, the graph starts a separate pending task afterward.

## Experimental interface

With `--autonomous-relations --relational-tasks`, Investigation may include `relational_tasks` on its existing `delegate` decision. Each row supplies only `observation_ids`. Runtime normalizes the order, rejects duplicates, and derives a stable task ID, source ID, common temporal scope and a neutral objective. Source, observation-to-frame citations and their time brackets are checked. Each observation must have a source frame inside the common interval, with at least two distinct sampled times across the set. Excluded or unaccounted observations are ineligible. A referenced deferred observation keeps its disposition and its individual evidence remains unverified.

An individual movement or relational task each uses one slot of the existing candidate budget. For example, the original four-movement queue at the archived limit has no spare task slot. LangGraph runs the movement queue first, then the separately assigned tasks. Both use the existing Verification role, call budget, inspection budget, iteration cap, and recovery policy.

Verification receives the task IDs, evidence scope, original observation context and retained dispositions. It can request the existing relational frame inspection with a specific question inside the task scope, select a proposal from that task's own inspection, or return insufficient. It cannot close the task with an individual verdict. A separately supported relation is one Event with the specific relation, its canonical citations and continuity status. There is no synthesized movement finding. Reversed-ID duplicate tasks fail delegation. A valid proposal closes its task once. Repeated inspections retain the existing global duplicate guard.

`completion.relational_tasks` records task outcomes independently of movement checks. Pending tasks remain unfinished, and exhausted budgets or insufficient evidence terminate the task as unresolved. Reporting displays unresolved tasks and supported relations. Event-relative retrieval uses the existing typed relation anchor. A task may remain unresolved if another candidate already consumed an identical inspection request. The experimental path does not cache or reassign that proposal across task scopes.

**Negative findings are unavailable in the pilot.** The current media contract can abstain or produce an unresolved or invalid proposal. None of those establishes absence in an adequately covered scope. Both an uninspected negative and a negative attempted after a no-proposal inspection remain unresolved. A future negative contract would need the exact inspected scope, visibility and coverage sufficient for the question, and affirmative visual evidence supporting the scoped negative. The divergence threshold and person-continuity requirements are unchanged. The autonomous schema still excludes `distinct_paths` as a supported claim.

## Replay and request capture

```sh
.venv/bin/python -m pytest -q \
  experiments/meet_walk_split_high_probes/test_relational_tasks.py \
  --basetemp /tmp/sa-independent-relations
```

To query a saved experimental result without running an agent, pass its result path:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/retrieval.py \
  --result /tmp/sa-independent-relations/test_sdk_payload_and_archived_0/run/result.json \
  --question 'What happened after the two people approached each other?'
```

The mock SDK test captures the serialized text contexts, response schemas and instructions in `mock-requests.json`. The Investigation context exposes task creation with observation IDs. Verification initially receives the neutral scope and no image marks, expected relationship fields or human reference judgments. The original archived model observations can still suggest a relationship in prose. For the positive control, the test replays the saved raw approach response only at the media-response boundary and reproduces its saved inspection manifest. A selected proposal then reaches Event, Reporting and Retrieval. Other controls replay insufficient divergence and exercise unresolved correspondence and invalid negative verdicts. These fixtures demonstrate the API and graph contract. They provide no measurement of Gemini's autonomous task-generation rate or visual accuracy.

## One separately authorized live evaluation

Use the same archived 500 ms observations and existing model settings. When this flag is present, Investigation runs live over the archive rather than replaying its prior decisions. No task is preselected by the runner. Only after separate authorization to send observation text and targeted media, execute:

```sh
.venv/bin/python experiments/meet_walk_split_high_probes/verification.py \
  --autonomous-relations --relational-selection --relational-tasks \
  --authorize-observation-text-transfer --authorize-footage-transfer \
  --question 'What happens in this video? Reconstruct the sequence of visible events, including relationships between movements when supported by evidence. Explicitly identify uncertainties.' \
  --output experiments/meet_walk_split_high_probes/independent-relational-tasks-live
```

The initial scan is reused locally. The cap is 14 logical role calls and four targeted inspections, or **32 physical requests** at the existing limit of two attempts per role call and one per media call. Evaluate separately whether Investigation delegates a warranted task, Verification selects a useful inspection or abstains, the relation passes validation, and a blinded reviewer can defend the finding from the submitted frames. Preserve uncertainty about identity. The saved workflow and judgments are suitable for a descriptive case study. This command was not executed.
