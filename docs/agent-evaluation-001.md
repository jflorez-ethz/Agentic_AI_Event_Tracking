# Controlled Gemini role evaluation

## Scope

Run the deterministic baseline and Gemini role decisions from one locally verified snapshot of seven attempts in the first E1 comparison and Window A clip retry. Video ingestion, media replay, and citation validation happen locally. The evaluation entry point passes only an archive lookup to the role controller. It never passes an observation provider, and neither search nor frame/clip inspection dispatches video inference. Both modes start from the video without a question.

## Data sent to Gemini, after authorization

All external calls are text-only `generateContent` requests for `gemini-3.5-flash-lite`. Every request includes the role instructions and a JSON action schema. Depending on role, the prompt can contain the video duration, source-relative microsecond intervals, observation and inspection IDs, modality, archived observation category and description (up to 400 characters), and visibility and uncertainty text (up to 240 characters each). Verification can also receive the delegated observation ID, remaining inspection and iteration budget, and a prior tool result containing matching observation IDs and counts. Reporting gets finding IDs, categories, verdicts, intervals and citation counts. API credentials are used only for authentication.

The request does not contain video or image bytes, the original video path or hash, XML annotations, full archive files, raw archived responses, or source frame pixel data. Archived artifacts stay local. Consider observation descriptions and derived source metadata part of the data transfer being authorized.

## Limits

Expect about five role calls for a two-candidate run with one inspection, or six if Investigation also searches. Six calls is the hard cap, with the final slot reserved for Reporting. A run may stop sooner. There are at most two candidates, one search, two archive inspections, and two verification decisions per candidate. Requests for exact duplicate tools or invalid evidence, intervals and actions are rejected. The first new model, validation or tool execution failure stops further model calls and leaves unresolved findings or a deterministic report. Historical failed records are tracked separately when suitable successful archive evidence is available.

The client uses LOW thinking, a configured maximum output of 1,024 tokens per call, a 90-second request timeout, and one HTTP attempt. Automatic continuation is disabled. Prompt token use is bounded indirectly by the fixed snapshot, text truncation and call cap. Actual usage comes from response metadata when available. The output includes a partial cost estimate using the E1 preflight reference rates (USD 0.30 input and USD 2.50 output per million tokens, including reported thinking tokens). It labels how many calls contributed and does not establish actual charges.

## Run

From the workspace root, use the following command only after explicit authorization to transmit the observation text and derived metadata, with an API key available to the process:

```sh
.venv/bin/python -m security_augmented.agent_eval data/raw/LeftBag.mpg \
  --archive experiments/e1_comparison_001 \
  --archive experiments/e1_comparison_001_a_clip_retry_001 \
  --output experiments/e1_agent_evaluation_001 \
  --live --authorize-observation-text-transfer
```

For an offline baseline run, omit the last line and use a different new output directory. A completed live evaluation writes `baseline-report.md`, `gemini-report.md`, and `evaluation.json`. The JSON includes both decision traces, selected tool arguments, results, handoffs, findings, resolved evidence, model IDs and revisions where returned, per-call usage and latency, and sanitized error statuses. Raw model reasoning and credentials are excluded.

## Acceptance and interpretation

1. Compare both modes against the same seven archive attempts. Confirm zero video-perception requests and compliance with all execution limits. A completed API response with invalid or rejected actions is an execution failure, not an accepted decision.
2. Match the supported placement to the reviewed Window A event and its original frame and clip citations. Require actual corroborating cited source frames. Missing the placement counts as a missed positive even if the output is valid. Check the reason for any missing or irrelevant inspection.
3. Retain Window B handling as unresolved and keep Window C free of unsupported placement or removal. Neither the report nor the abandonment query may present abandonment, unattended duration or intent as established.
4. Resolve every finding citation to the corresponding archived inspection and original source frame PTS. Review the actual cited visual evidence before scoring support. A structurally valid citation alone does not establish the event.
5. Compare event and uncertainty outcomes first, then relevant tool choices, duplicate or rejected actions, model calls, latency, reported tokens and partial estimated cost. Record technical failures separately from perceptual or decision errors. A single run is a feasibility check and cannot establish improved agent performance.

## First live StateGraph run

Use the same source and archive directories from the first evaluation and only switch the controller. Use a fresh output directory. After explicit text-transfer authorization and with credentials available, run from the workspace root:

```sh
.venv/bin/python -m security_augmented.agent_eval data/raw/LeftBag.mpg \
  --archive experiments/e1_comparison_001 \
  --archive experiments/e1_comparison_001_a_clip_retry_001 \
  --output experiments/e1_agent_langgraph_001 \
  --controller langgraph --live --authorize-observation-text-transfer
```

The graph path adds structured validation feedback and recorded graph transitions to the local artifacts. Any feedback transmitted to Verification contains the missing-corroboration code, a short validator message, candidate ID and remaining recovery allowance. The next prompt can include archived observations returned by the tool. Role instructions, JSON schemas, derived observation text, evidence IDs, source-relative intervals, visibility and uncertainty, limits, tool results and finding summaries are the only application data sent. There is no observation provider on this path. The existing SDK sends one text part per call. Video, clip and frame bytes, local paths, source hashes and XML annotations stay local.

### Budget decision

Keep the six-request maximum. The scripted graph used one Investigation delegation, three turns for placement verification (premature verdict, inspection and revised verdict), one turn for the ambiguous candidate and one Reporting selection. Direct retrieval can complete the same two findings in five calls, leaving room for one Investigation search. Combining that extra search with a full recovery on placement requires seven calls. Under the approved cap, the controller may then leave a candidate unresolved or stop when the remaining slot is reserved for Reporting. That is an observable outcome. Do not expand the budget after evaluating the result.

The graph allows three Verification turns per candidate, one recovery per candidate, up to one search and two inspections, and one terminal execution failure. Output remains capped at 1,024 tokens per role request. SDK retries and continuation remain disabled. Report whether retrieval happened directly or after feedback. Direct, appropriate retrieval is a successful decision, while a run without recovery leaves live recovery untested.

### StateGraph acceptance and failure categories

- Investigation delegates the relevant placement observation. Verification obtains corroboration through a relevant local archive tool, cites new source frames, and returns a valid revised verdict when evidence warrants it. Either direct retrieval or recovery from a valid insufficiency rejection meets this criterion.
- Reporting receives validated verdicts only, retains the ambiguous handling as unresolved, and includes source-resolvable citations. Compare with the deterministic baseline on the same seven attempts. Reject unsupported abandonment and removal claims. Review the cited footage locally to adjudicate semantic support.
- Log API/transport errors in the per-call record, non-JSON or incomplete output as invalid output, and controller schema/tool/verdict rejections in the trace with their validation stage. Missing corroboration has its own feedback and recovery events. A legal but irrelevant tool choice or missed candidate is a decision error for human review. No decision is replaced by the offline fixture. A deterministic render may still display the actual accepted and unresolved findings after a failure.
- Record graph transitions, handoffs, recovery attempts, tool results, citations, role latency and reported usage from `evaluation.json`. Cost remains an estimate at the previously documented reference rates. A single live run tests feasibility.
