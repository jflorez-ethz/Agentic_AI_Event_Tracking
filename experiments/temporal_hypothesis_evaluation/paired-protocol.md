# Paired temporal inspection evaluation

**Status:** prepared offline. Neither arm has an observed model decision or perception result.

The harness rehydrates the same saved Meet Walk Split observations and citations for A and B, verifies their decoded pixels and PTS against the source, and exposes the same focal 10–14.52 s movement. Both arms receive the same serialized context. The plan writes an input SHA-256 for comparison. Both arms use a shared experiment-only selection prompt and schema. It exposes one optional frame inspection or explicit abstention. Only B gets the instruction to explicitly consider temporal hypotheses and identify a distinguishing visual clue. This setup evaluates a controlled selection decision, not the full autonomous production investigation.

Both arms use Gemini 3.6 Flash for reasoning and Gemini 3.5 Flash-Lite for perception. Each may use one selection decision, one verification decision and one reporting decision, plus one optional inspection with 500 ms frame sampling. The cap is six physical role attempts and one single-attempt media request per arm. The follow-up must overlap the focus and be no longer than ten seconds. The harness writes both selections before executing any selected inspection. Local routing hands off the fixed focus and previously selected inspection through the existing LangGraph controller. Verification and reporting use the production validator and renderer. Further inspections and recovery loops are disabled for equal opportunity. A supported verdict about the original movement is not evidence of what happened afterward.

## Commands

Run from the repository root. The first command is offline and prepares the common input and settings. The second test uses an injected mock decider and media adapter and checks equal inputs, equal caps, abstention, and commitment of both decisions before either inspection.

```sh
plan_dir=$(mktemp -d /tmp/sa-paired-plan.XXXXXX)
.venv/bin/python experiments/temporal_hypothesis_evaluation/paired.py --output "$plan_dir/plan"
.venv/bin/python -m pytest -q experiments/temporal_hypothesis_evaluation/test_paired.py
```

Only after explicit authorization for both observation text and sampled footage, with the Gemini API key configured:

```sh
run_dir=$(mktemp -d experiments/temporal_hypothesis_evaluation/paired.XXXXXX)
.venv/bin/python experiments/temporal_hypothesis_evaluation/paired.py \
  --live --authorize-external-transfer --order AB --output "$run_dir/run"
```

Use `--order BA` in a separately authorized fresh run to check order sensitivity. No calls from either arm are shared with the other. Role requests can send the saved observation text, citation and source-frame metadata, and returned observations from that arm. Perception requests can send source PNG frames, timestamp labels, instructions and schema. Provider metadata and response text are stored locally from available results. Paid calls can total six logical reasoning calls, twelve physical reasoning attempts, and two single-attempt media requests for the pair.

## Score independently

Use the local [review rubric](reviewer-rubric.md) and `review-sequence.mkv`. Two reviewers should label trajectories and observability before seeing selections. None were available during preparation. Treat judgments as provisional until independently reviewed. Score the selected interval blind to arm where feasible. A valuable follow-up shows trackable evidence that discriminates among plausible outcomes, or establishes why those outcomes remain unobservable. A justified abstention can be appropriate. Report instruction adherence separately from interval quality. Score the final conclusion against cited frames and the source annotation separately from inspection quality.

| Arm | Hypotheses and rationale | Selection | Information gained | Justified conclusion | Cost |
|---|---|---|---|---|---|
| A | Pending | Pending | Pending | Pending | Pending, cap 3 logical + 1 media |
| B | Pending | Pending | Pending | Pending | Pending, same cap |

Read `selection.json` for the decision and rationale, `supplied-frames.json` and `perception.json` for executed inputs and provider outputs, and `verification-decision.json` and `verification.json` for proposed and validated outcomes. Usage, latency and role attempts are recorded by the SDK wrapper; `execution-cost.json` reports the role calls and a media-attempt upper bound, since a local preparation failure can occur before a send. Missing output is not a model verdict.

One pairing on one clip measures feasibility. Model sampling, provider variation, and ambiguous trajectories can dominate it. The known source visibility limits may make even a well-chosen interval inconclusive. Record reordering and repeated trials as separate experiments. Do not interpret the mock as agent performance.

## First live pair diagnosis and revised selection interface

The original pair is archived in `paired.8x7R3L/run`. Its harness appended an experiment instruction to the production Investigation prompt, which still explicitly asked for candidate delegation and dispositions for all visible observations. The actual response schema allowed ordinary nonempty delegation. A followed that contract, while the experiment validator only meant empty delegation as abstention. No tool ran.

B returned HTTP 200 and usage including 1,009 candidate tokens against the configured 1,024 output-token cap. The SDK wrapper rejected before parsing JSON because it did not see exactly one candidate with finish reason STOP. The archived trace retained neither candidate count nor finish reasons. A token limit is plausible but unconfirmed. Both arms had one HTTP attempt. Unfinished generation and invalid JSON are outside the transport retry loop.

The revised harness replaces the selection-stage prompt and schema in both arms with an explicit `inspect(start_us, end_us, reason)` or `abstain(reason)` choice. The only arm-specific instruction remains B's hypothesis requirement. Inputs, models, temperature settings, token cap, request limits and the follow-up tool are unchanged. The production role prompts and schema still apply during verification and reporting. The harness records configuration, candidate count, finish reasons and completion status when a response exists, alongside the SDK request-attempt trace and any parsing or selection error. No retry is added for invalid model output. The commands above also run the corrected harness; use a fresh directory.
